"""Keyline design geometry: graded keylines through keypoints, keyline patterns and swales on contour.

Everything here works in the DEM's projected CRS (metres). Lines are traced on a lightly smoothed copy of
the terrain so one-cell noise in the DEM does not make them wander.

Conventions
- `grade` is a fraction: 1/300 means the line falls 1 m for every 300 m along it.
- A keyline starts at a keypoint in a valley and falls gently toward the ridges on both sides, so water
  that follows the rip lines is carried out of the valley onto the drier ridges.
- Headings are radians in the math convention (0 = east, counter-clockwise).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage
from shapely import ops
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep

from . import hydrology
from .dem import Dem

DEFAULT_GRADE = 1 / 300
GALLONS_PER_M3 = 264.172

# Terrain slope (%) above which an element is flagged for the designer.
SWALE_SLOPE_WARN_PCT = 15.0
SWALE_SLOPE_MAX_PCT = 25.0
RIP_GRADE_WARN = 1 / 100  # a rip line steeper than this along its length can start to scour


class Surface:
    """A smoothed, bilinearly sampled terrain surface built from a `Dem`."""

    def __init__(self, dem: Dem, smooth_m: float = 2.0):
        self.dem = dem
        z = dem.elevation
        valid = ~np.isnan(z)
        sigma = smooth_m / dem.res
        if sigma > 0.3:
            # normalized convolution so nodata does not bleed into the smoothed surface
            w = ndimage.gaussian_filter(valid.astype(float), sigma)
            zs = ndimage.gaussian_filter(np.where(valid, z, 0.0), sigma)
            with np.errstate(invalid="ignore", divide="ignore"):
                z = np.where(valid, zs / w, np.nan)
        self.elevation = z
        self.res = dem.res

    def z(self, x, y) -> np.ndarray:
        r, c = self.dem.rowcol(np.atleast_1d(x), np.atleast_1d(y))
        rows, cols = self.elevation.shape
        inside = (r >= 0) & (c >= 0) & (r <= rows - 1) & (c <= cols - 1)
        out = np.full(r.shape, np.nan)
        if inside.any():
            out[inside] = ndimage.map_coordinates(self.elevation, [r[inside], c[inside]], order=1, mode="nearest")
        return out

    def z1(self, x: float, y: float) -> float:
        return float(self.z(x, y)[0])

    def downhill_heading(self, x: float, y: float, radius_m: float = 8.0) -> float:
        """Direction of steepest descent at a point, from elevations `radius_m` away."""
        r = max(radius_m, 2 * self.res)
        zx = self.z(np.array([x + r, x - r]), np.array([y, y]))
        zy = self.z(np.array([x, x]), np.array([y + r, y - r]))
        gx, gy = (zx[0] - zx[1]) / (2 * r), (zy[0] - zy[1]) / (2 * r)
        if not np.isfinite(gx + gy) or (gx == 0 and gy == 0):
            raise ValueError("No slope at this point to orient a line")
        return math.atan2(-gy, -gx)

    def slope_pct_along(self, line: LineString, step: float | None = None) -> np.ndarray:
        """Terrain slope (%) at points along a line (not the slope of the line itself)."""
        step = step or self.res
        d = np.arange(0, line.length + step / 2, step)
        pts = np.array([line.interpolate(v).coords[0] for v in d])
        h = self.res
        x, y = pts[:, 0], pts[:, 1]
        gx = (self.z(x + h, y) - self.z(x - h, y)) / (2 * h)
        gy = (self.z(x, y + h) - self.z(x, y - h)) / (2 * h)
        return np.hypot(gx, gy) * 100.0

    def profile(self, line: LineString, step: float | None = None) -> tuple[np.ndarray, np.ndarray]:
        step = step or self.res
        n = max(int(line.length / step) + 1, 2)
        d = np.linspace(0, line.length, n)
        pts = np.array([line.interpolate(v).coords[0] for v in d])
        return d, self.z(pts[:, 0], pts[:, 1])


# ---- Graded line tracing ------------------------------------------------------------------------


@dataclass
class Trace:
    points: list[tuple[float, float]]
    stop: str  # "boundary" | "ridge" | "terrain" | "length"

    @property
    def length(self) -> float:
        return LineString(self.points).length if len(self.points) > 1 else 0.0


def trace_graded(
    surface: Surface,
    start: tuple[float, float],
    grade: float,
    heading: float,
    *,
    step: float | None = None,
    max_length: float = 3000.0,
    stops: BaseGeometry | None = None,
    within: Polygon | None = None,
    z_start: float | None = None,
    search_deg: float = 80.0,
) -> Trace:
    """Walk from `start` holding a constant fall of `grade` per metre, staying close to `heading`.

    At each step the next point is where the surface crosses the target elevation on an arc of radius
    `step` ahead; among several crossings the one closest to the current heading wins, so the line keeps
    going the same way along the slope. Stops at the `within` boundary, at any line in `stops` (ridges),
    where no crossing exists (terrain too flat or a cliff), or at `max_length`.
    """
    step = step or max(surface.res, 1.0)
    x, y = start
    z0 = surface.z1(x, y) if z_start is None else z_start
    if not np.isfinite(z0):
        raise ValueError("Start point is outside the terrain model")
    pts = [(x, y)]
    within_p = prep(within) if within is not None else None
    # stop a little before touching a stop line: valley floors are notched, so the trace can lose its
    # crossing a step short of the valley line itself
    stops_p = prep(stops.buffer(1.5 * step)) if stops is not None and not stops.is_empty else None
    offsets = np.radians(np.linspace(-search_deg, search_deg, int(2 * search_deg) + 1))
    s = 0.0
    reason = "length"
    while s < max_length:
        target = z0 - grade * (s + step)
        angs = heading + offsets
        xs, ys = x + step * np.cos(angs), y + step * np.sin(angs)
        d = surface.z(xs, ys) - target
        ok = np.isfinite(d[:-1]) & np.isfinite(d[1:])
        cross = np.flatnonzero(ok & (d[:-1] * d[1:] <= 0))
        if cross.size == 0:
            reason = "terrain"
            break
        a0, a1, d0, d1 = angs[cross], angs[cross + 1], d[cross], d[cross + 1]
        frac = np.where(d0 != d1, d0 / (d0 - d1), 0.5)
        cand = a0 + (a1 - a0) * frac
        best = cand[np.argmin(np.abs(cand - heading))]
        nx, ny = x + step * math.cos(best), y + step * math.sin(best)
        seg = LineString([(x, y), (nx, ny)])
        if within_p is not None and not within_p.contains(Point(nx, ny)):
            hit = seg.intersection(within.boundary)
            if not hit.is_empty:
                pts.append(_first_point(hit, (x, y)))
            reason = "boundary"
            break
        if stops_p is not None and s > 2 * step and stops_p.intersects(seg):
            pts.append(_first_point(stops, (x, y)))
            reason = "ridge"
            break
        pts.append((nx, ny))
        heading = best
        x, y = nx, ny
        s += step
    return Trace(pts, reason)


def _first_point(geom: BaseGeometry, origin: tuple[float, float]) -> tuple[float, float]:
    """The point of `geom` nearest `origin` (intersections can be points, multipoints or segments)."""
    o = Point(origin)
    nearest = ops.nearest_points(o, geom)[1]
    return (nearest.x, nearest.y)


def _join_arms(a: Trace, b: Trace) -> LineString:
    coords = list(reversed(a.points)) + b.points[1:]
    return LineString(coords)


def keyline_through(
    surface: Surface,
    keypoint: tuple[float, float],
    grade: float = DEFAULT_GRADE,
    *,
    stops: BaseGeometry | None = None,
    within: Polygon | None = None,
    step: float | None = None,
    max_arm_m: float = 2000.0,
) -> tuple[LineString, list[Trace]]:
    """The keyline through a keypoint: two arms, each falling at `grade` toward a ridge."""
    down = surface.downhill_heading(*keypoint)
    z0 = surface.z1(*keypoint)
    # leave a small hole around the keypoint so the valley it sits in does not stop the trace at once
    local_stops = stops.difference(Point(keypoint).buffer(3 * (step or surface.res) + 2)) if stops is not None else None
    arms = [
        trace_graded(surface, keypoint, grade, down + s * math.pi / 2, step=step, max_length=max_arm_m,
                     stops=local_stops, within=within, z_start=z0)
        for s in (1, -1)
    ]
    line = _join_arms(arms[0], arms[1])
    if line.length < 2 * surface.res:
        raise ValueError("The keyline could not be traced from this keypoint")
    return line, arms


# ---- Patterns -----------------------------------------------------------------------------------


@dataclass
class PatternLine:
    geom: LineString
    props: dict = field(default_factory=dict)


def _parts(geom: BaseGeometry) -> list[LineString]:
    if geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    out = []
    for g in getattr(geom, "geoms", []):
        out.extend(_parts(g))
    return out


def _restrict_to_valley(line: LineString, valley: BaseGeometry | None, ridges: BaseGeometry | None, tol: float) -> list[LineString]:
    """Split a line at ridges and keep only the pieces that cross the keypoint's valley."""
    pieces = [line]
    if ridges is not None and not ridges.is_empty:
        pieces = _parts(ops.split(line, ridges)) if line.intersects(ridges) else [line]
    if valley is None:
        return pieces
    zone = valley.buffer(tol)
    return [p for p in pieces if p.intersects(zone)]


def parallel_pattern(
    surface: Surface,
    keyline: LineString,
    spacing: float,
    within: Polygon,
    *,
    max_lines: int = 300,
    valley: BaseGeometry | None = None,
    ridges: BaseGeometry | None = None,
    min_length: float | None = None,
) -> list[PatternLine]:
    """Yeomans' keyline pattern: lines offset parallel to the keyline, above and below it.

    With `valley`, the pattern is cut at the ridges and kept only where it crosses that valley; otherwise it
    runs across the whole `within` area.
    """
    if spacing <= 0:
        raise ValueError("Spacing must be positive")
    min_length = min_length if min_length is not None else max(2 * spacing, 10.0)
    reach = within.hausdorff_distance(keyline)
    per_side = min(int(math.ceil(reach / spacing)), max_lines // 2)
    mid = keyline.interpolate(0.5, normalized=True)
    z_mid = surface.z1(mid.x, mid.y)
    side_up = None
    out: list[PatternLine] = []
    for k in range(1, per_side + 1):
        for sign in (1, -1):
            off = keyline.offset_curve(sign * k * spacing, quad_segs=4, join_style="round")
            if off.is_empty:
                continue
            if side_up is None:
                probe = off.interpolate(0.5, normalized=True)
                side_up = sign if surface.z1(probe.x, probe.y) > z_mid else -sign
            clipped = off.intersection(within)
            pieces = []
            for part in _parts(clipped):
                pieces.extend(_restrict_to_valley(part, valley, ridges, spacing / 2) if valley is not None else [part])
            for piece in pieces:
                if piece.length >= min_length:
                    out.append(PatternLine(piece, {"offset_m": round(sign * k * spacing, 2),
                                                   "position": "above" if sign == side_up else "below",
                                                   "row": k}))
        if len(out) >= max_lines:
            break
    return out[:max_lines]


def graded_pattern(
    surface: Surface,
    seeds_along: LineString,
    keypoint: tuple[float, float],
    spacing: float,
    grade: float,
    within: Polygon,
    *,
    stops: BaseGeometry | None = None,
    max_lines: int = 300,
    step: float | None = None,
) -> list[PatternLine]:
    """Lines that each hold `grade`, seeded every `spacing` metres along the valley through the keypoint."""
    if spacing <= 0:
        raise ValueError("Spacing must be positive")
    kp_d = seeds_along.project(Point(keypoint))
    offsets = []
    k = 1
    while len(offsets) < max_lines and (kp_d - k * spacing >= 0 or kp_d + k * spacing <= seeds_along.length):
        for sign in (-1, 1):
            d = kp_d + sign * k * spacing
            if 0 <= d <= seeds_along.length:
                offsets.append(d)
        k += 1
    out: list[PatternLine] = []
    z_kp = surface.z1(*keypoint)
    for d in offsets[:max_lines]:
        p = seeds_along.interpolate(d)
        if not within.contains(p):
            continue
        try:
            line, _ = keyline_through(surface, (p.x, p.y), grade, stops=stops, within=within, step=step)
        except ValueError:
            continue
        if line.length >= max(2 * spacing, 10.0):
            z = surface.z1(p.x, p.y)
            out.append(PatternLine(line, {"seed_offset_m": round(d - kp_d, 2),
                                          "position": "above" if z > z_kp else "below"}))
    return out


# ---- Line checks ------------------------------------------------------------------------------


def line_metrics(surface: Surface, line: LineString, valley: BaseGeometry | None = None) -> dict:
    """Length, elevations and how water would drift along a rip line.

    `fall_to_ridges_min` is the smaller of the two arms' average fall away from the valley crossing (or from
    the line's high point): positive means water following the line leaves the valley, as intended.
    """
    d, z = surface.profile(line)
    ok = np.isfinite(z)
    if ok.sum() < 2:
        return {"length_m": round(line.length, 1)}
    d, z = d[ok], z[ok]
    if valley is not None and line.intersects(valley):
        cross = line.project(Point(_first_point(line.intersection(valley), line.coords[0])))
        ci = int(np.argmin(np.abs(d - cross)))
    else:
        ci = int(np.argmax(z))
    arms = []
    if ci > 0:
        arms.append((z[ci] - z[0]) / max(d[ci] - d[0], 1e-6))
    if ci < len(d) - 1:
        arms.append((z[ci] - z[-1]) / max(d[-1] - d[ci], 1e-6))
    local = np.abs(np.diff(z)) / np.maximum(np.diff(d), 1e-6)
    seg_len = max(int(round(20 / max(surface.res, 0.5))), 1)  # judge steepness over ~20 m, not cell to cell
    if len(z) > seg_len:
        local = np.abs(z[seg_len:] - z[:-seg_len]) / np.maximum(d[seg_len:] - d[:-seg_len], 1e-6)
    return {
        "length_m": round(float(line.length), 1),
        "z_start_m": round(float(z[0]), 2),
        "z_end_m": round(float(z[-1]), 2),
        "fall_to_ridges_min": round(float(min(arms)), 5) if arms else None,
        "steepest_grade": round(float(local.max()), 4) if local.size else None,
    }


def check_rip(metrics: dict) -> list[str]:
    notes = []
    fall = metrics.get("fall_to_ridges_min")
    if fall is not None and fall < 0:
        notes.append("Part of this line carries water back toward the valley.")
    steep = metrics.get("steepest_grade")
    if steep is not None and steep > RIP_GRADE_WARN:
        notes.append(f"Falls as steeply as 1:{max(int(round(1 / steep)), 1)} in places; watch for scour.")
    return notes


# ---- Swales ------------------------------------------------------------------------------------


@dataclass
class Swale:
    geom: LineString
    elevation_m: float
    end_offset_m: float  # how far the requested end point was from the contour


def swale_on_contour(surface: Surface, start: tuple[float, float], end: tuple[float, float], window_m: float = 300.0) -> Swale:
    """A dead-level swale: the contour through `start`, from `start` to the point nearest `end`."""
    from skimage import measure

    z0 = surface.z1(*start)
    if not np.isfinite(z0):
        raise ValueError("The start point is outside the terrain model")
    dem = surface.dem
    minx, maxx = min(start[0], end[0]) - window_m, max(start[0], end[0]) + window_m
    miny, maxy = min(start[1], end[1]) - window_m, max(start[1], end[1]) + window_m
    r0, c0 = dem.rowcol(np.array([minx]), np.array([maxy]))
    r1, c1 = dem.rowcol(np.array([maxx]), np.array([miny]))
    rows, cols = surface.elevation.shape
    r0, c0 = max(int(r0[0]), 0), max(int(c0[0]), 0)
    r1, c1 = min(int(r1[0]) + 2, rows), min(int(c1[0]) + 2, cols)
    win = surface.elevation[r0:r1, c0:c1]
    filled = np.where(np.isnan(win), np.nanmin(win) - 100, win)
    sp = Point(start)
    best, best_d = None, np.inf
    for coords in measure.find_contours(filled, z0):
        if len(coords) < 2:
            continue
        x, y = dem.xy(coords[:, 0] + r0, coords[:, 1] + c0)
        ln = LineString(np.column_stack([x, y]))
        dist = ln.distance(sp)
        if dist < best_d:
            best, best_d = ln, dist
    if best is None:
        raise ValueError("No contour found through the start point")
    a, b = best.project(sp), best.project(Point(end))
    piece = ops.substring(best, min(a, b), max(a, b))
    if best.is_ring:
        # a closed contour can be walked either way; take the shorter way round
        other = best.length - piece.length
        if other < piece.length:
            first = ops.substring(best, max(a, b), best.length)
            second = ops.substring(best, 0, min(a, b))
            piece = LineString(list(first.coords) + list(second.coords)[1:])
    if not isinstance(piece, LineString) or piece.length < 2 * surface.res:
        raise ValueError("The swale is too short; pick an end point further along the slope")
    if a > b:
        piece = LineString(list(piece.coords)[::-1])
    return Swale(piece, z0, float(best.interpolate(best.project(Point(end))).distance(Point(end))))


def upslope_area(surface: Surface, line: LineString, window_m: float = 600.0) -> tuple[float, bool]:
    """Area (m²) that drains onto `line`, within a window around it. The flag is True if the window clipped it."""
    from rasterio.features import rasterize

    dem = surface.dem
    minx, miny, maxx, maxy = line.buffer(window_m).bounds
    r0, c0 = dem.rowcol(np.array([minx]), np.array([maxy]))
    r1, c1 = dem.rowcol(np.array([maxx]), np.array([miny]))
    rows, cols = surface.elevation.shape
    r0, c0 = max(int(r0[0]), 0), max(int(c0[0]), 0)
    r1, c1 = min(int(r1[0]) + 2, rows), min(int(c1[0]) + 2, cols)
    z = surface.elevation[r0:r1, c0:c1]
    from affine import Affine

    t = dem.transform @ Affine.translation(c0, r0)
    mark = rasterize([(line, 1)], out_shape=z.shape, transform=t, all_touched=True).astype(bool).reshape(-1)
    downstream = hydrology.d8_downstream(z)
    flat = z.reshape(-1)
    order = np.argsort(np.where(np.isnan(flat), np.inf, flat), kind="stable")
    reach = mark.copy()
    for i in order:
        if reach[i] or np.isnan(flat[i]):
            continue
        dsi = downstream[i]
        if dsi >= 0 and reach[dsi]:
            reach[i] = True
    grid = reach.reshape(z.shape)
    clipped = bool(grid[0, :].any() or grid[-1, :].any() or grid[:, 0].any() or grid[:, -1].any())
    area = float((reach & ~mark).sum() * dem.res**2)
    return area, clipped


def swale_metrics(surface: Surface, swale: Swale, width_m: float, depth_m: float,
                  boundary: Polygon | None = None, major_flow: BaseGeometry | None = None) -> tuple[dict, list[str]]:
    """Size, storage and catchment of a swale, with design notes."""
    length = swale.geom.length
    section = (2.0 / 3.0) * width_m * depth_m  # parabolic cross-section
    volume = section * length
    slope = surface.slope_pct_along(swale.geom)
    catchment, clipped = upslope_area(surface, swale.geom)
    m = {
        "elevation_m": round(swale.elevation_m, 2),
        "length_m": round(length, 1),
        "width_m": width_m,
        "depth_m": depth_m,
        "cross_section_m2": round(section, 3),
        "cut_volume_m3": round(volume, 1),
        "storage_gal": round(volume * GALLONS_PER_M3),
        "catchment_m2": round(catchment, 1),
        "catchment_clipped": clipped,
        "terrain_slope_mean_pct": round(float(np.nanmean(slope)), 1),
        "terrain_slope_max_pct": round(float(np.nanmax(slope)), 1),
    }
    notes = []
    if m["terrain_slope_max_pct"] > SWALE_SLOPE_MAX_PCT:
        notes.append(f"Ground reaches {m['terrain_slope_max_pct']:.0f}% slope along this swale; above "
                     f"{SWALE_SLOPE_MAX_PCT:.0f}% a swale is hard to build and can fail. Consider a terrace or a shorter run.")
    elif m["terrain_slope_max_pct"] > SWALE_SLOPE_WARN_PCT:
        notes.append(f"Ground reaches {m['terrain_slope_max_pct']:.0f}% slope along this swale; keep the berm well compacted.")
    if major_flow is not None and not major_flow.is_empty and swale.geom.intersects(major_flow):
        notes.append("Crosses a main flow path: add a level spillway there so overflow leaves safely.")
    if boundary is not None and swale.geom.distance(boundary.exterior) < 3.0:
        notes.append("Runs within 3 m of the property line.")
    if swale.end_offset_m > 25:
        notes.append(f"The end point was {swale.end_offset_m:.0f} m off this contour; the swale stops at the nearest point on it.")
    if clipped:
        notes.append("Catchment extends beyond the analysis window; the true catchment is larger.")
    return m, notes


def keyline_stops(ridges: BaseGeometry | None, valleys: list[LineString], keypoint: Point, hole_m: float = 15.0) -> BaseGeometry | None:
    """Where keyline arms stop: ridges, and any valley other than near the keypoint's own crossing.

    Ridge detection can miss low interfluves; reaching the next valley floor is then the stop instead.
    """
    from shapely.ops import unary_union

    parts = []
    if ridges is not None and not ridges.is_empty:
        parts.append(ridges)
    if valleys:
        parts.append(unary_union(valleys).difference(keypoint.buffer(hole_m)))
    return unary_union(parts) if parts else None


def valley_near(valleys: list[LineString], point: Point, max_dist: float = 30.0) -> LineString | None:
    """The merged valley line passing closest to a point, if within `max_dist`."""
    if not valleys:
        return None
    merged = ops.linemerge(MultiLineString(valleys)) if len(valleys) > 1 else valleys[0]
    best = min(_parts(merged), key=lambda ln: ln.distance(point))
    return best if best.distance(point) <= max_dist else None
