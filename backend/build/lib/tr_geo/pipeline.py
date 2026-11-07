"""Stage 1 terrain analysis: one call from a projected DEM and a site boundary to every layer the app shows."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString, Point, Polygon

from . import hydrology, keypoints, terrain
from .dem import Dem, polygon_mask

Feature = tuple[object, dict]  # (shapely geometry in DEM CRS, properties)

GRADE_LIMITS_M = {"design": 1.0, "planning": 10.0}  # source resolution at or below → grade


def grade_for(resolution_m: float, source_kind: str) -> str:
    """Data-quality grade of a source. Only surveyed sources (LiDAR, survey DEM) can be design grade."""
    surveyed = source_kind in {"lidar", "dem"}
    if surveyed and resolution_m <= GRADE_LIMITS_M["design"]:
        return "design"
    if resolution_m <= GRADE_LIMITS_M["planning"]:
        return "planning"
    return "coarse"


@dataclass
class Params:
    contour_interval_m: float = 0.6  # about 2 ft
    flow_threshold_m2: float = 2_000.0  # contributing area at which a flow path is drawn
    valley_threshold_fraction: float = 0.04  # share of the site's area that makes a primary valley
    min_valley_threshold_m2: float = 8_000.0
    keypoint_smooth_m: float = 15.0
    simplify_m: float | None = None  # defaults to half a cell


@dataclass
class TerrainResult:
    summary: dict
    layers: dict[str, list[Feature]] = field(default_factory=dict)


COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def compass_direction(dx: float, dy: float) -> str:
    bearing = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    return COMPASS[int((bearing + 22.5) // 45) % 8]


def _line(dem: Dem, cells: list[int], simplify: float) -> LineString:
    rows, cols = np.divmod(np.asarray(cells), dem.shape[1])
    x, y = dem.xy(rows, cols)
    return LineString(np.column_stack([x, y])).simplify(simplify)


def _distinct_valleys(dem: Dem, paths: list[list[int]], merge_m: float = 10.0, overlap: float = 0.5) -> list[list[int]]:
    """Drop paths that mostly run alongside or on top of a longer one.

    Paths from different heads join downstream, and D8 can carry parallel flow lines down one valley
    floor; a path that lies within `merge_m` of an already kept path for more than `overlap` of its
    length is the same valley.
    """
    kept: list[tuple[list[int], object]] = []
    for path in sorted(paths, key=len, reverse=True):
        line = _line(dem, path, 0)
        if line.length == 0:
            continue
        duplicate = False
        for _, other_zone in kept:
            shared = line.intersection(other_zone).length / line.length
            if shared > overlap:
                duplicate = True
                break
        if not duplicate:
            kept.append((path, line.buffer(merge_m)))
    return [p for p, _ in kept]


def _cell_point(dem: Dem, cell: int) -> Point:
    r, c = divmod(cell, dem.shape[1])
    x, y = dem.xy(np.array([r]), np.array([c]))
    return Point(float(x[0]), float(y[0]))


def _clip_lines(lines: list[Feature], boundary: Polygon) -> list[Feature]:
    out = []
    for geom, props in lines:
        clipped = geom.intersection(boundary)
        if clipped.is_empty:
            continue
        parts = getattr(clipped, "geoms", [clipped])
        for part in parts:
            if isinstance(part, LineString) and part.length > 0:
                out.append((part, props))
    return out


def analyze(
    dem: Dem,
    boundary: Polygon,
    params: Params | None = None,
    source_grades: dict[str, float] | None = None,
) -> TerrainResult:
    """Run the full Stage 1 analysis.

    `dem` must be in a projected CRS and should extend somewhat beyond `boundary` (same CRS) so upslope
    catchments are counted. `source_grades` gives the share of the site per grade, e.g. {"design": 0.82, ...};
    by default it is derived from the DEM resolution as public data.
    """
    p = params or Params()
    simplify = p.simplify_m if p.simplify_m is not None else dem.res / 2
    cell_area = dem.res**2
    inside = polygon_mask(dem, boundary) & ~np.isnan(dem.elevation)
    if inside.sum() < 50:
        raise ValueError("The boundary covers too few DEM cells to analyse")
    site_area = float(inside.sum() * cell_area)

    # Hydrology on the full (buffered) grid so water entering the site is counted.
    filled = hydrology.fill_depressions(dem.elevation)
    downstream = hydrology.d8_downstream(filled)
    acc = hydrology.flow_accumulation(filled, downstream)

    flow_thr = max(p.flow_threshold_m2 / cell_area, 10)
    valley_thr = max(p.valley_threshold_fraction * site_area, p.min_valley_threshold_m2) / cell_area
    valley_thr = max(valley_thr, flow_thr * 2)

    flow_lines: list[Feature] = []
    for ch in hydrology.trace_channels(acc, downstream, flow_thr):
        flow_lines.append((_line(dem, ch.cells, simplify), {"accumulation_m2": ch.max_accumulation * cell_area}))
    flow_lines = _clip_lines(flow_lines, boundary)
    if flow_lines:
        ranked = sorted(flow_lines, key=lambda f: -f[1]["accumulation_m2"])
        cutoff = ranked[max(0, len(ranked) // 4 - 1)][1]["accumulation_m2"]
        for _, props in flow_lines:
            props["major"] = props["accumulation_m2"] >= cutoff

    valley_lines: list[Feature] = []
    for ch in hydrology.trace_channels(acc, downstream, valley_thr):
        valley_lines.append((_line(dem, ch.cells, simplify), {"accumulation_m2": ch.max_accumulation * cell_area}))
    valley_lines = _clip_lines(valley_lines, boundary)

    # Ridges are the channels of the inverted surface.
    inv_filled = hydrology.fill_depressions(-dem.elevation)
    inv_down = hydrology.d8_downstream(inv_filled)
    inv_acc = hydrology.flow_accumulation(inv_filled, inv_down)
    ridge_lines = _clip_lines(
        [(_line(dem, ch.cells, simplify), {}) for ch in hydrology.trace_channels(inv_acc, inv_down, valley_thr)],
        boundary,
    )

    # Keypoints along each primary valley, head to where it leaves the site.
    candidates = []
    paths = _distinct_valleys(dem, hydrology.longest_flow_paths(acc, downstream, valley_thr, mask=inside))
    for path in paths:
        kp = keypoints.find_keypoint(path, dem.elevation, dem.res, smooth_m=p.keypoint_smooth_m)
        if kp is not None:
            candidates.append(kp)
    candidates.sort(key=lambda k: -k.score)
    kept: list[tuple[keypoints.KeypointCandidate, Point]] = []
    min_sep = 3 * p.keypoint_smooth_m
    for kp in candidates:
        pt = _cell_point(dem, kp.cell)
        if all(pt.distance(other) >= min_sep for _, other in kept):
            kept.append((kp, pt))
    keypoint_features: list[Feature] = []
    for i, (kp, pt) in enumerate(kept, start=1):
        keypoint_features.append(
            (
                pt,
                {
                    "id": f"K{i}",
                    "elevation_m": round(kp.elevation, 2),
                    "score": round(kp.score, 3),
                    "gradient_above_pct": round(kp.gradient_above * 100, 1),
                    "gradient_below_pct": round(kp.gradient_below * 100, 1),
                    "confirmed": False,
                },
            )
        )

    contour_features: list[Feature] = []
    masked = Dem(np.where(inside | _ring(inside), dem.elevation, np.nan), dem.transform, dem.crs)
    for line, level, is_index in terrain.contours(masked, p.contour_interval_m):
        contour_features.append((line, {"elevation_m": round(level, 2), "index": is_index}))
    contour_features = _clip_lines(contour_features, boundary)

    # Outlet: the inside cell with the most accumulation whose flow leaves the site.
    flat_inside = inside.reshape(-1)
    ds = downstream
    leaves = flat_inside & ((ds < 0) | ~flat_inside[np.clip(ds, 0, None)])
    acc_flat = np.nan_to_num(acc.reshape(-1))
    outlet_cell = int(np.argmax(np.where(leaves, acc_flat, -1)))
    orow, ocol = divmod(outlet_cell, dem.shape[1])
    ox, oy = dem.xy(np.array([orow]), np.array([ocol]))
    centroid = boundary.centroid
    outlet_dir = compass_direction(float(ox[0]) - centroid.x, float(oy[0]) - centroid.y)

    slope = terrain.slope_percent(dem)
    z_in = dem.elevation[inside]
    grades = source_grades or {grade_for(dem.res, "public_dem"): 1.0}
    quality = {f"{g}_pct": round(100.0 * grades.get(g, 0.0), 1) for g in ("design", "planning", "coarse")}

    summary = {
        "dem_resolution_m": round(dem.res, 3),
        "elevation_min_m": round(float(np.nanmin(z_in)), 2),
        "elevation_max_m": round(float(np.nanmax(z_in)), 2),
        "mean_slope_pct": round(float(np.nanmean(slope[inside])), 1),
        "outlet_xy": (float(ox[0]), float(oy[0])),
        "outlet_direction": outlet_dir,
        "main_valley_count": len(paths),
        "keypoint_count": len(keypoint_features),
        "site_area_m2": round(site_area, 1),
        "quality": quality,
    }
    return TerrainResult(
        summary=summary,
        layers={
            "contours": contour_features,
            "flow": flow_lines,
            "valleys": valley_lines,
            "ridges": ridge_lines,
            "keypoints": keypoint_features,
        },
    )


def _ring(mask: np.ndarray) -> np.ndarray:
    """One-cell ring outside the mask, so contours reach the boundary before clipping."""
    from scipy import ndimage

    return ndimage.binary_dilation(mask, iterations=2) & ~mask
