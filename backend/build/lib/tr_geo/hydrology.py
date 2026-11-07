"""Surface hydrology on a gridded DEM: depression breaching/filling, D8 flow, accumulation, channel extraction.

Pure numpy. Grids up to roughly 1.5 million cells run in seconds; larger sites are resampled first
(see `dem.working_resolution`). WhiteboxTools can replace these routines later behind the same functions.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

# D8 neighbour offsets (row, col), clockwise from north.
OFFSETS = np.array([(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)])
DIST = np.array([1.0, np.sqrt(2), 1.0, np.sqrt(2), 1.0, np.sqrt(2), 1.0, np.sqrt(2)])


def fill_depressions(z: np.ndarray, epsilon: float = 1e-4) -> np.ndarray:
    """Priority-flood fill (Barnes et al. 2014) with a small gradient so every cell drains to an edge.

    NaN cells are treated as outside the data; cells beside them or on the grid edge are outlets.
    """
    rows, cols = z.shape
    valid = ~np.isnan(z)
    filled = z.copy()
    closed = ~valid  # never visit nodata
    edge = np.zeros_like(valid)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    beside_nodata = ndimage.binary_dilation(~valid, structure=np.ones((3, 3))) & valid
    seeds = (edge | beside_nodata) & valid

    heap: list[tuple[float, int]] = []
    for flat in np.flatnonzero(seeds):
        heap.append((float(filled.flat[flat]), int(flat)))
        closed.flat[flat] = True
    heapq.heapify(heap)

    flat_filled = filled.reshape(-1)
    flat_closed = closed.reshape(-1)
    while heap:
        elev, i = heapq.heappop(heap)
        r, c = divmod(i, cols)
        for dr, dc in OFFSETS:
            nr, nc = r + dr, c + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue
            n = nr * cols + nc
            if flat_closed[n]:
                continue
            flat_closed[n] = True
            if flat_filled[n] <= elev:
                flat_filled[n] = elev + epsilon
            heapq.heappush(heap, (float(flat_filled[n]), n))
    return filled


def d8_downstream(filled: np.ndarray) -> np.ndarray:
    """Flat index of each cell's steepest-descent neighbour; -1 where flow leaves the grid or data."""
    rows, cols = filled.shape
    padded = np.pad(filled, 1, constant_values=np.nan)
    best_drop = np.zeros(filled.shape)
    best_dir = np.full(filled.shape, -1, dtype=np.int64)
    for k, (dr, dc) in enumerate(OFFSETS):
        neighbour = padded[1 + dr : 1 + dr + rows, 1 + dc : 1 + dc + cols]
        drop = (filled - neighbour) / DIST[k]
        drop = np.where(np.isnan(drop), -np.inf, drop)
        better = drop > best_drop
        best_drop[better] = drop[better]
        best_dir[better] = k
    rr, cc = np.indices(filled.shape)
    has = best_dir >= 0
    nr = np.where(has, rr + OFFSETS[np.clip(best_dir, 0, 7), 0], -1)
    nc = np.where(has, cc + OFFSETS[np.clip(best_dir, 0, 7), 1], -1)
    downstream = np.where(has, nr * cols + nc, -1)
    downstream[np.isnan(filled)] = -1
    return downstream.reshape(-1)


def flow_accumulation(filled: np.ndarray, downstream: np.ndarray) -> np.ndarray:
    """Number of cells draining through each cell, itself included. NaN where there is no data."""
    valid = ~np.isnan(filled.reshape(-1))
    acc = np.where(valid, 1.0, 0.0)
    order = np.argsort(-np.where(valid, filled.reshape(-1), -np.inf), kind="stable")
    for i in order:
        if not valid[i]:
            continue
        d = downstream[i]
        if d >= 0:
            acc[d] += acc[i]
    acc = acc.reshape(filled.shape)
    acc[~valid.reshape(filled.shape)] = np.nan
    return acc


@dataclass
class Channel:
    cells: list[int]  # flat indices, upstream → downstream
    max_accumulation: float


def trace_channels(accumulation: np.ndarray, downstream: np.ndarray, threshold: float) -> list[Channel]:
    """Vectorise the channel network: cells with accumulation ≥ threshold, split at confluences."""
    acc = np.nan_to_num(accumulation.reshape(-1), nan=0.0)
    is_channel = acc >= threshold
    channel_idx = np.flatnonzero(is_channel)
    if channel_idx.size == 0:
        return []

    upstream_count = np.zeros(acc.size, dtype=np.int64)
    ds = downstream[channel_idx]
    flows_to_channel = (ds >= 0) & is_channel[np.clip(ds, 0, None)]
    np.add.at(upstream_count, ds[flows_to_channel], 1)

    starts = channel_idx[(upstream_count[channel_idx] != 1)]  # heads (0 upstream) and confluences (≥2)
    channels: list[Channel] = []
    for start in starts:
        cells = [int(start)]
        cur = int(start)
        while True:
            nxt = int(downstream[cur])
            if nxt < 0 or not is_channel[nxt]:
                break
            cells.append(nxt)
            if upstream_count[nxt] != 1:  # reached a confluence: end this segment there
                break
            cur = nxt
        if len(cells) >= 2:
            channels.append(Channel(cells=cells, max_accumulation=float(acc[cells[-1]])))
    return channels


def longest_flow_paths(
    accumulation: np.ndarray, downstream: np.ndarray, threshold: float, mask: np.ndarray | None = None
) -> list[list[int]]:
    """For each channel head at `threshold`, the full path down to where it leaves the grid or mask.

    Used for main valleys: one continuous line per head rather than confluence-split segments.
    """
    acc = np.nan_to_num(accumulation.reshape(-1), nan=0.0)
    inside = np.ones(acc.size, dtype=bool) if mask is None else mask.reshape(-1)
    is_channel = (acc >= threshold) & inside
    idx = np.flatnonzero(is_channel)
    has_upstream = np.zeros(acc.size, dtype=bool)
    ds = downstream[idx]
    ok = (ds >= 0) & is_channel[np.clip(ds, 0, None)]
    has_upstream[ds[ok]] = True
    heads = idx[~has_upstream[idx]]
    paths = []
    for h in heads:
        path = [int(h)]
        cur = int(h)
        while True:
            nxt = int(downstream[cur])
            if nxt < 0 or not inside[nxt] or len(path) > acc.size:
                break
            path.append(nxt)
            cur = nxt
        paths.append(path)
    return paths
