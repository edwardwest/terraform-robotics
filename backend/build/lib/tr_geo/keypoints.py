"""Keypoint candidates along primary valleys.

In keyline design a keypoint is where a primary valley's floor changes from the steeper upper slope
to the flatter lower slope. Along each valley's long profile we smooth the elevations, take the
downhill gradient, and pick the point of greatest concavity (fastest drop in gradient) away from the
ends. Candidates are scored by how sharp the change is; the user confirms them in the app.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d


@dataclass
class KeypointCandidate:
    path_position: int  # index into the valley path
    cell: int  # flat cell index
    elevation: float
    gradient_above: float  # mean downhill gradient above the point (m/m)
    gradient_below: float  # mean downhill gradient below the point (m/m)
    score: float  # 0–1: relative drop in gradient


def find_keypoint(
    path_cells: list[int],
    elevation: np.ndarray,
    res: float,
    smooth_m: float = 15.0,
    edge_fraction: float = 0.12,
    min_drop: float = 0.2,
) -> KeypointCandidate | None:
    """Best keypoint on one valley path (head → outlet), or None if the profile has no clear break."""
    n = len(path_cells)
    if n < 12:
        return None
    flat = elevation.reshape(-1)
    z = flat[np.asarray(path_cells)]
    if np.any(np.isnan(z)):
        return None

    rows_cols = np.array([divmod(c, elevation.shape[1]) for c in path_cells], dtype=float)
    step = np.hypot(*np.diff(rows_cols, axis=0).T) * res
    s = np.concatenate([[0.0], np.cumsum(step)])

    # resample to an even spacing so smoothing and derivatives mean the same everywhere
    spacing = res
    s_even = np.arange(0, s[-1], spacing)
    if s_even.size < 12:
        return None
    z_even = np.interp(s_even, s, z)
    z_smooth = gaussian_filter1d(z_even, sigma=max(smooth_m / spacing, 1.0), mode="nearest")
    gradient = -np.gradient(z_smooth, spacing)  # positive going downhill
    concavity = -np.gradient(gradient, spacing)  # positive where the gradient is dropping

    lo = int(edge_fraction * s_even.size)
    hi = int((1 - edge_fraction) * s_even.size)
    if hi - lo < 3:
        return None
    k = lo + int(np.argmax(concavity[lo:hi]))
    above = float(np.mean(gradient[:k])) if k > 0 else 0.0
    below = float(np.mean(gradient[k:])) if k < gradient.size else 0.0
    if above <= 0:
        return None
    score = (above - below) / above
    if score < min_drop:
        return None

    pos = int(np.argmin(np.abs(s - s_even[k])))
    return KeypointCandidate(
        path_position=pos,
        cell=int(path_cells[pos]),
        elevation=float(z[pos]),
        gradient_above=above,
        gradient_below=below,
        score=float(np.clip(score, 0, 1)),
    )
