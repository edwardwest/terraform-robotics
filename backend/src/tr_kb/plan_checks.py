"""Placement checks for the master plan: rules in code, each with its source, run over the placed features.

Pure: features (projected to a UTM CRS, metres), the property line and, when there is one, the terrain surface in;
a list of findings out. Findings are guidance for a landowner, not approvals; every regulatory one says to check the
county. Limits are quoted in the units the rule uses ("100 ft", "16%"); measured values are metric fields for the
web app to show in the person's units.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, Point, Polygon

FT = 0.3048

ANIMAL_ENCLOSURES = {"paddock", "poultry-yard", "poultry-coop"}
NUTRIENT_SOURCES = ANIMAL_ENCLOSURES | {"compost", "compost-area", "biomass"}
WATER_BODIES = {"pond", "rain-garden", "creek", "well-spring"}
HOMES = {"house"}
BUILDINGS = {"house", "barn", "shed"}
TREES = {"shade-tree", "orchard", "food-forest", "windbreak", "hedgerow", "existing-forest", "riparian", "berries"}
FORESTS = {"existing-forest", "food-forest"}
GARDENS = {"vegetable-garden", "sheet-mulch"}
EARTHWORKS = {"pond", "rain-garden", "check-dam"}

SOURCES = {
    "well": "California Well Standards, DWR Bulletins 74-81 and 74-90: 100 ft from an animal or fowl enclosure. Counties may require more.",
    "calfire": "CAL FIRE defensible space: Zone 0 (0–5 ft), Zone 1 (5–30 ft), Zone 2 (30–100 ft). Zone 0 rules are being finalized; check current CAL FIRE guidance.",
    "road": "California State Minimum Fire Safe Regulations, 14 CCR 1273.03: road and driveway grades no more than 16% (up to 20% with local approval).",
    "setback": "Terraform Robotics design rule (setback): earthworks 3 m (10 ft) or more from the property line. Local grading rules govern.",
    "pond": "Terraform Robotics design rule, after NRCS Pond (378): ponds belong in low, gently sloping ground.",
    "runoff": "Terraform Robotics design rule (in-house): keep manure and compost downhill of, or well away from, water.",
    "zones": "Permaculture zoning (Mollison): place what you visit daily closest to the house.",
}


@dataclass
class CheckFeature:
    id: str
    type: str
    category: str
    label: str
    status: str
    geom: Point | LineString | Polygon


@dataclass
class Finding:
    rule: str
    severity: str  # "warning" | "note"
    title: str
    message: str
    feature_ids: list[str]
    source: str
    measure: dict = field(default_factory=dict)  # metric values, e.g. {"distance_m": 21.4} or {"grade_pct": 19}

    def as_dict(self) -> dict:
        return {"rule": self.rule, "severity": self.severity, "title": self.title, "message": self.message,
                "feature_ids": self.feature_ids, "source": self.source, "measure": self.measure}


def _name(f: CheckFeature) -> str:
    return f.label or f.type.replace("-", " ")


def _of(features: list[CheckFeature], types: set[str], proposed_only: bool = False) -> list[CheckFeature]:
    return [f for f in features if f.type in types and (not proposed_only or f.status == "proposed")]


def run_checks(features: list[CheckFeature], boundary: Polygon | None, surface=None,
               winds: list[dict] | None = None) -> list[Finding]:
    """All placement checks. `surface` (tr_geo.design.Surface) enables the terrain checks."""
    out: list[Finding] = []
    out += _outside(features, boundary)
    out += _setback(features, boundary)
    out += _well(features)
    out += _runoff(features, surface)
    out += _pond_slope(features, surface)
    out += _road_grade(features, surface)
    out += _fire(features)
    out += _zones(features)
    out += _windbreaks(features, winds or [])
    order = {"warning": 0, "note": 1}
    return sorted(out, key=lambda f: (order[f.severity], f.rule))


def _outside(features, boundary) -> list[Finding]:
    if boundary is None:
        return []
    out = []
    inner = boundary.buffer(1.0)
    for f in features:
        if f.status == "proposed" and not inner.contains(f.geom):
            out.append(Finding("outside-property", "warning", "Outside the property line",
                               f"Part of {_name(f)} is outside the property line.", [f.id],
                               "Property line from the Site step."))
    return out


def _setback(features, boundary) -> list[Finding]:
    if boundary is None:
        return []
    edge = boundary.exterior
    out = []
    for f in _of(features, EARTHWORKS, proposed_only=True):
        d = f.geom.distance(edge)
        if d < 3.0 and boundary.buffer(1.0).contains(f.geom):
            out.append(Finding("setback", "note", "Close to the property line",
                               f"{_name(f).capitalize()} is within 10 ft of the property line. Neighbours' drainage and "
                               "county grading rules may need more room.", [f.id], SOURCES["setback"], {"distance_m": round(d, 1)}))
    return out


def _well(features) -> list[Finding]:
    out = []
    wells = _of(features, {"well-spring"})
    for a in _of(features, ANIMAL_ENCLOSURES):
        for w in wells:
            d = a.geom.distance(w.geom)
            if d < 100 * FT:
                out.append(Finding("well-setback", "warning", "Animals near a well",
                                   f"{_name(a).capitalize()} is within 100 ft of {_name(w)}. California's well standards "
                                   "keep animal and poultry enclosures at least 100 ft from a well.", [a.id, w.id],
                                   SOURCES["well"], {"distance_m": round(d, 1)}))
    return out


def _z_at(surface, geom) -> float | None:
    p = geom.representative_point() if not isinstance(geom, Point) else geom
    z = surface.z1(p.x, p.y)
    return z if math.isfinite(z) else None


def _runoff(features, surface) -> list[Finding]:
    out = []
    waters = _of(features, WATER_BODIES)
    for s in _of(features, NUTRIENT_SOURCES):
        for w in waters:
            d = s.geom.distance(w.geom)
            if d > 60:
                continue
            if surface is None:
                if d < 30:
                    out.append(Finding("runoff", "note", "Manure or compost near water",
                                       f"{_name(s).capitalize()} is close to {_name(w)}. Add a terrain model to check "
                                       "whether runoff would flow toward it.", [s.id, w.id], SOURCES["runoff"],
                                       {"distance_m": round(d, 1)}))
                continue
            zs = _z_at(surface, s.geom)
            near = w.geom.interpolate(w.geom.project(s.geom.centroid)) if isinstance(w.geom, LineString) else (
                w.geom if isinstance(w.geom, Point) else w.geom.exterior.interpolate(w.geom.exterior.project(s.geom.centroid)))
            zw = _z_at(surface, near)
            if zs is not None and zw is not None and zs - zw > 1.0:
                out.append(Finding("runoff", "warning", "Manure or compost uphill of water",
                                   f"{_name(s).capitalize()} sits uphill of {_name(w)}, so rain can carry nutrients into it. "
                                   "Move it downhill or across the slope, or put a vegetated buffer or swale between them.",
                                   [s.id, w.id], SOURCES["runoff"], {"distance_m": round(d, 1), "drop_m": round(zs - zw, 1)}))
    return out


def _pond_slope(features, surface) -> list[Finding]:
    if surface is None:
        return []
    out = []
    for p in _of(features, {"pond"}, proposed_only=True):
        if not isinstance(p.geom, Polygon):
            continue
        slopes = surface.slope_pct_along(p.geom.exterior)
        slopes = slopes[[math.isfinite(v) for v in slopes]]
        if len(slopes) and float(slopes.mean()) > 15:
            out.append(Finding("pond-slope", "warning", "Steep ground for a pond",
                               f"The ground around {_name(p)} averages over 15% slope. Ponds hold more water for less "
                               "earthmoving in low, gentle ground; a dam here may need an engineer.", [p.id], SOURCES["pond"],
                               {"slope_pct": round(float(slopes.mean()), 1)}))
    return out


def _road_grade(features, surface) -> list[Finding]:
    if surface is None:
        return []
    from tr_geo.plan import max_grade_pct

    out = []
    for r in _of(features, {"road", "path"}, proposed_only=True):
        if not isinstance(r.geom, LineString):
            continue
        g = max_grade_pct(surface, r.geom)
        if g is None:
            continue
        if r.type == "road" and g > 16:
            out.append(Finding("road-grade", "warning", "Steep road",
                               f"{_name(r).capitalize()} climbs as steeply as {g:.0f}%. California's fire-safe rules cap "
                               "roads and driveways at 16%; steep grades also erode. Try a route across the slope.",
                               [r.id], SOURCES["road"], {"grade_pct": g}))
        elif r.type == "path" and g > 20:
            out.append(Finding("path-grade", "note", "Steep path",
                               f"{_name(r).capitalize()} climbs as steeply as {g:.0f}%. Steps or switchbacks make it "
                               "easier underfoot and with a wheelbarrow.", [r.id], "Terraform Robotics design rule (in-house).",
                               {"grade_pct": g}))
    return out


def _fire(features) -> list[Finding]:
    out = []
    buildings = _of(features, BUILDINGS)
    for b in buildings:
        for t in _of(features, TREES):
            d = t.geom.distance(b.geom)
            if d < 5 * FT:
                out.append(Finding("defensible-zone0", "warning", "Plants against a building",
                                   f"{_name(t).capitalize()} comes within 5 ft of {_name(b)}. CAL FIRE's Zone 0 keeps the first "
                                   "5 ft around buildings free of plants and other fuel.", [t.id, b.id], SOURCES["calfire"],
                                   {"distance_m": round(d, 1)}))
            elif t.type in FORESTS and d < 30 * FT and b.type in HOMES:
                out.append(Finding("defensible-zone1", "note", "Trees within 30 ft of the house",
                                   f"{_name(t).capitalize()} comes within 30 ft of {_name(b)}. In CAL FIRE's Zone 1, space trees "
                                   "and shrubs apart and keep branches 10 ft from the house.", [t.id, b.id], SOURCES["calfire"],
                                   {"distance_m": round(d, 1)}))
    homes = _of(features, HOMES)
    if homes and not _of(features, {"defensible-space"}):
        out.append(Finding("defensible-space", "note", "No defensible space drawn",
                           "Draw defensible space around the house: 100 ft is required in California's fire hazard areas "
                           "(or to the property line).", [h.id for h in homes], SOURCES["calfire"]))
    return out


def _zones(features) -> list[Finding]:
    out = []
    homes = _of(features, HOMES)
    if not homes:
        return out
    for g in _of(features, GARDENS, proposed_only=True):
        d = min(g.geom.distance(h.geom) for h in homes)
        if d > 60:
            out.append(Finding("garden-far", "note", "Kitchen garden far from the house",
                               f"{_name(g).capitalize()} is more than 200 ft from the house. Gardens you tend daily do best "
                               "within a short walk of the kitchen (zones 1 and 2).", [g.id], SOURCES["zones"],
                               {"distance_m": round(d, 1)}))
    gardens = _of(features, GARDENS)
    if gardens:
        for c in _of(features, {"compost"}, proposed_only=True):
            d = min(c.geom.distance(g.geom) for g in gardens)
            if d > 60:
                out.append(Finding("compost-far", "note", "Compost far from the garden",
                                   f"{_name(c).capitalize()} is more than 200 ft from the nearest garden; that's a long haul "
                                   "with a wheelbarrow.", [c.id], SOURCES["zones"], {"distance_m": round(d, 1)}))
    return out


def _windbreaks(features, winds: list[dict]) -> list[Finding]:
    if not winds:
        return []
    from tr_geo.plan import bearing_deg

    out = []
    for w in _of(features, {"windbreak"}, proposed_only=True):
        if not isinstance(w.geom, LineString) or w.geom.length < 10:
            continue
        line = bearing_deg(w.geom)
        for wind in winds:
            d = float(wind["from_deg"]) % 180
            diff = abs(line - d) % 180
            diff = min(diff, 180 - diff)  # angle between the line and the wind, 0-90
            if diff < 45:
                label = (wind.get("label") or "prevailing").lower()
                out.append(Finding("windbreak-wind", "note", "Windbreak runs with the wind",
                                   f"{_name(w).capitalize()} runs within 45° of the {label} wind, so it shelters little. "
                                   "Windbreaks work best across the wind.", [w.id],
                                   "Windbreak siting (NRCS Windbreak/Shelterbelt Establishment, 380): orient across the wind.",
                                   {"angle_deg": round(diff, 0)}))
    return out
