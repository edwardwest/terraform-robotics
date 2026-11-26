"""Master plan geometry: planting layouts, zone rings and sun, wind and fire sectors. Pure (numpy/shapely); works in
a projected CRS in metres.

Rows on contour follow the pattern keyline orchards use: the contour through the middle of the area is the master
row, and the other rows run parallel to it at the row spacing. Rows across steep, curving ground drift a little off
the true contour away from the master row; that is the accepted trade for even spacing between rows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString, Point, Polygon

from .design import Surface, contour_line

MAX_PLANTS = 5000


@dataclass
class Planting:
    rows: list[LineString]
    points: list[tuple[float, float]]
    pattern: str  # "contour" | "straight" | "line" | "point"
    capped: bool = False  # more plants than MAX_PLANTS: points thinned for display; the count stays the layout's


def _along(line: LineString, spacing: float) -> list[tuple[float, float]]:
    n = max(1, int(line.length // spacing) + 1)
    if n == 1:
        q = line.interpolate(0.5, normalized=True)
        return [(q.x, q.y)]
    offset = (line.length - (n - 1) * spacing) / 2  # center the run within the row
    return [line.interpolate(offset + i * spacing).coords[0][:2] for i in range(n)]


def _parts(geom) -> list[LineString]:
    if geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, LineString)]


def straight_rows(area: Polygon, row_spacing: float, plant_spacing: float) -> Planting:
    """East-west rows across the area at the row spacing, plants along them at the plant spacing."""
    _check_spacing(row_spacing, plant_spacing)
    inner = area.buffer(-plant_spacing / 2)
    if inner.is_empty:
        inner = area
    minx, miny, maxx, maxy = inner.bounds
    n = int((maxy - miny) // row_spacing) + 1
    start = miny + ((maxy - miny) - (n - 1) * row_spacing) / 2  # center the rows in the area
    rows = []
    for y in start + row_spacing * np.arange(n):
        rows.extend(p for p in _parts(LineString([(minx - 1, y), (maxx + 1, y)]).intersection(inner)) if p.length > 0)
    return _finish(rows, plant_spacing, "straight", area)


def rows_on_contour(surface: Surface, area: Polygon, row_spacing: float, plant_spacing: float) -> Planting:
    """Rows parallel to the contour through the middle of the area. Raises ValueError on ground too flat to
    have a contour there; the caller falls back to straight rows."""
    _check_spacing(row_spacing, plant_spacing)
    inner = area.buffer(-plant_spacing / 2)
    if inner.is_empty:
        inner = area
    center = area.representative_point()
    minx, miny, maxx, maxy = area.bounds
    reach = math.hypot(maxx - minx, maxy - miny)
    master = contour_line(surface, center, reach)
    # Extend the master row straight past its ends so offsets still span the area where the contour stops short.
    master = _extend(master, reach)
    rows: list[LineString] = []
    n_side = int(math.ceil(reach / row_spacing)) + 1
    for k in range(-n_side, n_side + 1):
        off = master if k == 0 else master.offset_curve(k * row_spacing, quad_segs=4, join_style="round")
        if off.is_empty:
            continue
        rows.extend(p for p in _parts(off.intersection(inner)) if p.length >= plant_spacing * 0.5)
    if not rows:
        raise ValueError("The area is too small for rows at this spacing")
    return _finish(rows, plant_spacing, "contour", area)


def _extend(line: LineString, by: float) -> LineString:
    c = list(line.coords)
    (x0, y0), (x1, y1) = c[0][:2], c[min(3, len(c) - 1)][:2]
    (xa, ya), (xb, yb) = c[max(-4, -len(c))][:2], c[-1][:2]
    d0 = math.hypot(x0 - x1, y0 - y1) or 1
    d1 = math.hypot(xb - xa, yb - ya) or 1
    start = (x0 + (x0 - x1) / d0 * by, y0 + (y0 - y1) / d0 * by)
    end = (xb + (xb - xa) / d1 * by, yb + (yb - ya) / d1 * by)
    return LineString([start, *[p[:2] for p in c], end])


def line_planting(line: LineString, plant_spacing: float, rows: int = 1) -> Planting:
    """Plants along a line (a windbreak or hedgerow), in `rows` parallel rows about 0.8 × spacing apart."""
    if plant_spacing <= 0:
        raise ValueError("Spacing must be positive")
    gap = max(plant_spacing * 0.8, 1.0)
    lines = []
    for r in range(rows):
        off = (r - (rows - 1) / 2) * gap
        o = line if off == 0 else line.offset_curve(off)
        lines.extend(_parts(o) or [line])
    return _finish(lines, plant_spacing, "line", None)


def _check_spacing(row: float, plant: float) -> None:
    if row <= 0 or plant <= 0:
        raise ValueError("Spacing must be positive")


def _finish(rows: list[LineString], plant_spacing: float, pattern: str, area: Polygon | None) -> Planting:
    pts: list[tuple[float, float]] = []
    for r in rows:
        pts.extend(_along(r, plant_spacing))
    if area is not None and pattern == "contour":
        # offsets of a curving row can loop; drop plants that land too close to one already placed
        pts = _thin(pts, plant_spacing * 0.6)
    capped = len(pts) > MAX_PLANTS
    return Planting(rows, pts, pattern, capped)


def _thin(pts: list[tuple[float, float]], min_d: float) -> list[tuple[float, float]]:
    if len(pts) < 2:
        return pts
    keep: list[tuple[float, float]] = []
    tree_pts: dict[tuple[int, int], list[tuple[float, float]]] = {}
    cell = min_d
    for x, y in pts:
        cx, cy = int(x // cell), int(y // cell)
        near = [q for dx in (-1, 0, 1) for dy in (-1, 0, 1) for q in tree_pts.get((cx + dx, cy + dy), [])]
        if any((x - qx) ** 2 + (y - qy) ** 2 < min_d * min_d for qx, qy in near):
            continue
        keep.append((x, y))
        tree_pts.setdefault((cx, cy), []).append((x, y))
    return keep


# ---- Zones and sectors -------------------------------------------------------------------------------

DEFAULT_ZONE_RADII_M = (15.24, 45.72, 121.92, 304.8)  # zones 1-4 (50, 150, 400, 1,000 ft) out from the house; zone 5 is beyond


def zone_rings(center: Polygon | Point, radii_m: tuple[float, ...] = DEFAULT_ZONE_RADII_M) -> list[tuple[int, Polygon]]:
    """Zones 1..n as rings around zone 0 (the house), each `radii_m[i]` out from its walls."""
    out, inner = [], center if isinstance(center, Polygon) else center.buffer(0.5)
    prev = inner
    for i, r in enumerate(sorted(radii_m), start=1):
        ring = center.buffer(r, quad_segs=16)
        out.append((i, ring.difference(prev)))
        prev = ring
    return out


def sun_azimuths(lat_deg: float) -> dict:
    """Sunrise and sunset azimuths (degrees clockwise from north) at the solstices, and the noon sun's height,
    for a latitude. Uses the geometric sunrise (no refraction); within a degree or two of what an almanac gives."""
    phi = math.radians(lat_deg)
    out = {}
    for name, decl in (("summer", 23.44), ("winter", -23.44)):
        d = math.radians(decl if lat_deg >= 0 else -decl)
        c = math.sin(d) / math.cos(phi)
        if abs(c) >= 1:  # polar day or night
            out[name] = None
            continue
        rise = math.degrees(math.acos(c))
        out[name] = {"rise": round(rise, 1), "set": round(360 - rise, 1),
                     "noon_altitude": round(90 - abs(lat_deg - math.degrees(d)), 1)}
    return out


def sector(center: Point, from_deg: float, to_deg: float, radius_m: float) -> Polygon:
    """A wedge from the center out to `radius_m`, clockwise from bearing `from_deg` to `to_deg` (from north)."""
    span = (to_deg - from_deg) % 360 or 360
    n = max(8, int(span / 3))
    pts = [(center.x, center.y)]
    for i in range(n + 1):
        b = math.radians(from_deg + span * i / n)
        pts.append((center.x + radius_m * math.sin(b), center.y + radius_m * math.cos(b)))
    pts.append((center.x, center.y))
    return Polygon(pts)


def site_sectors(center: Point, lat_deg: float, radius_m: float, winds: list[dict], fire_from_deg: float | None) -> list[dict]:
    """Sector wedges: the sun's arc (sunrise to sunset through south in the northern hemisphere) at both solstices,
    each wind from its direction (a 45° wedge), and the fire direction (a 60° wedge)."""
    out = []
    sun = sun_azimuths(lat_deg)
    for season in ("summer", "winter"):
        s = sun.get(season)
        if s:
            # northern hemisphere: the sun crosses the south; southern: the north (rise→set clockwise either way)
            a, b = (s["rise"], s["set"]) if lat_deg >= 0 else (s["set"], s["rise"])
            out.append({"kind": "sun", "label": f"{season.title()} sun", "season": season, "from_deg": a, "to_deg": b,
                        "geom": sector(center, a, b, radius_m * (1.0 if season == "summer" else 0.82))})
    for w in winds:
        d = float(w["from_deg"]) % 360
        out.append({"kind": "wind", "label": w.get("label") or "Wind", "from_deg": d,
                    "geom": sector(center, d - 22.5, d + 22.5, radius_m * 0.9)})
    if fire_from_deg is not None:
        d = float(fire_from_deg) % 360
        out.append({"kind": "fire", "label": "Fire", "from_deg": d, "geom": sector(center, d - 30, d + 30, radius_m * 0.95)})
    return out


def bearing_deg(line: LineString) -> float:
    """Overall bearing of a line from its first to its last point (0-180, as a line has no direction)."""
    (x0, y0), (x1, y1) = line.coords[0][:2], line.coords[-1][:2]
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 180


def max_grade_pct(surface: Surface, line: LineString, window_m: float = 20.0) -> float | None:
    """Steepest grade along a line (rise over run, %) averaged over `window_m` stretches; None off the terrain."""
    if line.length < window_m:
        window_m = max(line.length, surface.res * 2)
    d, z = surface.profile(line, step=max(surface.res, 1.0))
    ok = np.isfinite(z)
    if ok.sum() < 2:
        return None
    d, z = d[ok], z[ok]
    best = 0.0
    j = 0
    for i in range(len(d)):
        while j < len(d) and d[j] - d[i] < window_m:
            j += 1
        if j >= len(d):
            break
        best = max(best, abs(z[j] - z[i]) / (d[j] - d[i]) * 100)
    return round(best, 1)


__all__ = ["Planting", "straight_rows", "rows_on_contour", "line_planting", "zone_rings", "sun_azimuths", "sector",
           "site_sectors", "bearing_deg", "max_grade_pct", "DEFAULT_ZONE_RADII_M"]
