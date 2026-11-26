"""Master plan, terrain-aware: lines along a contour, planting layouts (rows on contour), zones and sectors, and
placement checks. Geometry comes from tr_geo.plan and tr_geo.design; checks from tr_kb.plan_checks."""

from __future__ import annotations

import json
import logging
import math
from uuid import UUID

from fastapi import APIRouter, HTTPException
from shapely import affinity, wkb
from shapely.geometry import LineString, Point, mapping

from tr_geo import design as geo
from tr_geo import plan as gp
from tr_geo import project_geometry, utm_crs_for
from tr_kb import plan_checks as pc
from tr_kb import plan_features as pf

from . import schemas
from .auth import CurrentUser
from .common import _project_or_404, boundary_in, terrain_surface
from .db import execute, fetch_all, fetch_one
from .plan_features_api import feature_rows

log = logging.getLogger(__name__)
router = APIRouter()

MAX_DISPLAY_PLANTS = 4000  # per project on the map


# ---- Site frame ----------------------------------------------------------------------------------------


def site_frame(project_id: UUID):
    """(srid, surface or None, boundary in srid) for a project: the terrain model's CRS when there is one,
    else the UTM zone of the property."""
    try:
        _, surface, srid = terrain_surface(project_id)
    except Exception as e:  # noqa: BLE001 - no terrain model (404) or storage trouble: work without terrain
        if not (isinstance(e, HTTPException) and e.status_code == 404):
            log.warning("site_frame: terrain unavailable", exc_info=True)
        row = fetch_one("SELECT ST_X(ST_Centroid(boundary)) AS lon, ST_Y(ST_Centroid(boundary)) AS lat FROM projects WHERE id = :id",
                        id=str(project_id))
        srid, surface = int(utm_crs_for(row["lon"], row["lat"]).split(":")[1]), None
    return srid, surface, boundary_in(project_id, srid)


def features_in(project_id: UUID, srid: int) -> list[tuple[dict, object]]:
    """(feature row, geometry in srid) pairs."""
    rows = feature_rows(project_id)
    if not rows:
        return []
    geoms = {str(g["id"]): wkb.loads(bytes(g["g"])) for g in fetch_all(
        "SELECT id, ST_AsBinary(ST_Transform(geom, :srid)) AS g FROM plan_features WHERE project_id = :id",
        id=str(project_id), srid=srid)}
    return [(r, geoms[str(r["id"])]) for r in rows if str(r["id"]) in geoms]


def _ll(geom, srid: int):
    return project_geometry(geom, f"EPSG:{srid}", "EPSG:4326")


# ---- Planting layouts -------------------------------------------------------------------------------


def planting_layout(project_id: UUID, srid: int | None = None, surface=None, pairs=None) -> dict[str, dict]:
    """Rows and plant positions (in srid) for every planted feature that has a plant spacing.

    Areas use straight rows, or rows on contour when the feature asks for it and there's a terrain model (falling
    back to straight rows on ground too flat for a contour). Lines get rows along them; single trees one point."""
    if srid is None:
        srid, surface, _ = site_frame(project_id)
    pairs = pairs if pairs is not None else features_in(project_id, srid)
    types = pf.types_by_id()
    out: dict[str, dict] = {}
    for r, g in pairs:
        t = types[r["type"]]
        if "species" not in t["fields"]:
            continue
        p = r["props"] or {}
        plant = p.get("plant_spacing_m")
        try:
            if t["geometry"] == "point":
                lay, note = gp.Planting([], [(g.x, g.y)], "point"), None
            elif not plant:
                continue
            elif t["geometry"] == "line":
                lay, note = gp.line_planting(g, float(plant), int(p.get("rows") or 1)), None
            else:
                row = float(p.get("row_spacing_m") or plant)
                note = None
                if p.get("rows_pattern") == "contour":
                    if surface is None:
                        lay, note = gp.straight_rows(g, row, float(plant)), "No terrain model yet, so rows run straight."
                    else:
                        try:
                            lay = gp.rows_on_contour(surface, g, row, float(plant))
                        except ValueError as e:
                            lay, note = gp.straight_rows(g, row, float(plant)), f"{e}. Rows run straight here."
                else:
                    lay = gp.straight_rows(g, row, float(plant))
        except ValueError:
            continue
        out[str(r["id"])] = {"layout": lay, "note": note, "row": r}
    return out


@router.get("/api/projects/{project_id}/plan-features/planting")
def planting(project_id: UUID, user: CurrentUser):
    """Rows (LineString, kind "row") and plants (Point, kind "plant") of each planted feature, in EPSG:4326, plus the
    plant count and pattern per feature. Plants beyond a display cap are thinned on the map; counts are complete."""
    _project_or_404(project_id, user)
    srid, surface, _ = site_frame(project_id)
    lays = planting_layout(project_id, srid, surface)
    colors = {c["id"]: c["color"] for c in pf.library()["categories"]}
    total = sum(len(v["layout"].points) for v in lays.values()) or 1
    keep = min(1.0, MAX_DISPLAY_PLANTS / total)
    feats, summary = [], {}
    for fid, v in lays.items():
        lay, r = v["layout"], v["row"]
        color = colors.get(r["category"], "#ffffff")
        summary[fid] = {"plants": len(lay.points), "rows": len(lay.rows), "pattern": lay.pattern, "note": v["note"]}
        for ln in lay.rows:
            feats.append({"type": "Feature", "geometry": mapping(_ll(ln, srid)),
                          "properties": {"feature_id": fid, "kind": "row", "color": color}})
        step = max(1, round(1 / keep))
        for x, y in lay.points[::step]:
            q = _ll(Point(x, y), srid)
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(q.x, 7), round(q.y, 7)]},
                          "properties": {"feature_id": fid, "kind": "plant", "color": color}})
    return {"type": "FeatureCollection", "features": feats, "summary": summary}


# ---- Along a contour ------------------------------------------------------------------------------


@router.post("/api/projects/{project_id}/plan-features/contour-line")
def contour_line(project_id: UUID, body: schemas.ContourLineRequest, user: CurrentUser):
    """The contour through `start`, from `start` to the point on it nearest `end`, clipped to the property. Not
    saved: the app places it as whichever line feature the person is drawing."""
    _project_or_404(project_id, user)
    try:
        t, surface, srid = terrain_surface(project_id)
    except HTTPException as e:
        raise HTTPException(409, "Drawing along a contour needs a terrain model. Add ground data on the Survey step.") from e
    crs = t["dem_crs"]
    start = project_geometry(Point(body.start), "EPSG:4326", crs)
    end = project_geometry(Point(body.end), "EPSG:4326", crs)
    boundary = boundary_in(project_id, srid)
    if boundary is not None and not boundary.buffer(5).contains(start):
        raise HTTPException(422, "Start the line inside the property")
    try:
        sw = geo.swale_on_contour(surface, (start.x, start.y), (end.x, end.y))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    line = sw.geom
    if boundary is not None:
        clipped = line.intersection(boundary)
        parts = [p for p in getattr(clipped, "geoms", [clipped]) if isinstance(p, LineString)]
        if not parts:
            raise HTTPException(422, "That contour runs outside the property")
        line = min(parts, key=lambda p: p.distance(start))
    ll = project_geometry(line, crs, "EPSG:4326")
    return {"geometry": {"type": "LineString", "coordinates": [[round(x, 7), round(y, 7)] for x, y, *_ in ll.coords]},
            "elevation_m": round(sw.elevation_m, 2), "length_m": round(line.length, 1),
            "end_offset_m": round(sw.end_offset_m, 1)}


# ---- Zones and sectors ------------------------------------------------------------------------------


def load_site(project_id: UUID) -> dict:
    row = fetch_one("SELECT settings FROM plan_site WHERE project_id = :id", id=str(project_id))
    try:
        return schemas.PlanSiteSettings(**((row or {}).get("settings") or {})).model_dump()
    except Exception:  # noqa: BLE001 - settings from an older version
        return schemas.PlanSiteSettings().model_dump()


def _site_response(project_id: UUID, settings: dict) -> dict:
    srid, _, boundary = site_frame(project_id)
    pairs = features_in(project_id, srid)
    houses = [(r, g) for r, g in pairs if r["type"] == "house"]
    center_geom, source = None, "property"
    if settings["zone_center"]:
        center_geom = next((g for r, g in houses if str(r["id"]) == settings["zone_center"]), None)
        source = "house" if center_geom is not None else source
    if center_geom is None and houses:
        center_geom, source = houses[0][1], "house"
    if center_geom is None and boundary is not None:
        center_geom = boundary.representative_point()
    feats = []
    if center_geom is None:
        return {"settings": settings, "center": None, "center_source": None, "sun": None,
                "overlays": {"type": "FeatureCollection", "features": []}}
    c = center_geom.centroid
    lat = _ll(c, srid).y
    for zone, ring in gp.zone_rings(center_geom, tuple(settings["zone_radii_m"])):
        feats.append({"type": "Feature", "geometry": mapping(_ll(ring, srid)), "properties": {"kind": "zone", "zone": zone}})
    radius = settings["zone_radii_m"][-1] * 1.1
    for s in gp.site_sectors(c, lat, radius, settings["winds"], settings["fire_from_deg"]):
        g = s.pop("geom")
        feats.append({"type": "Feature", "geometry": mapping(_ll(g, srid)), "properties": s})
    cl = _ll(c, srid)
    return {"settings": settings, "center": [round(cl.x, 7), round(cl.y, 7)], "center_source": source,
            "sun": gp.sun_azimuths(lat), "overlays": {"type": "FeatureCollection", "features": feats}}


@router.get("/api/projects/{project_id}/plan-site")
def read_site(project_id: UUID, user: CurrentUser):
    """Zone and sector settings, the computed sun path at the solstices, and the overlays (EPSG:4326)."""
    _project_or_404(project_id, user)
    return _site_response(project_id, load_site(project_id))


@router.put("/api/projects/{project_id}/plan-site")
def write_site(project_id: UUID, body: schemas.PlanSiteSettings, user: CurrentUser):
    _project_or_404(project_id, user)
    execute("""INSERT INTO plan_site (project_id, settings) VALUES (:id, CAST(:s AS jsonb))
               ON CONFLICT (project_id) DO UPDATE SET settings = EXCLUDED.settings, updated_at = now()""",
            id=str(project_id), s=json.dumps(body.model_dump()))
    return _site_response(project_id, load_site(project_id))


# ---- Checks -----------------------------------------------------------------------------------------


@router.get("/api/projects/{project_id}/plan-checks")
def checks(project_id: UUID, user: CurrentUser):
    """Placement checks over the master plan. `terrain` says whether the terrain checks (runoff direction, pond
    slope, road grade) could run."""
    _project_or_404(project_id, user)
    srid, surface, boundary = site_frame(project_id)
    pairs = features_in(project_id, srid)
    types = pf.types_by_id()
    feats = [pc.CheckFeature(str(r["id"]), r["type"], r["category"], r["label"] or types[r["type"]]["label"], r["status"], g)
             for r, g in pairs]
    winds = load_site(project_id)["winds"]
    found = pc.run_checks(feats, boundary, surface, winds)
    return {"findings": [f.as_dict() for f in found], "terrain": surface is not None}


# ---- 3D scene ---------------------------------------------------------------------------------------

MAX_SCENE_TREES = 6000
WOODLAND_TYPES = {"existing-forest"}  # natural woodland: scattered trees, not rows
BUILDING_COLORS = {"house": "#a35454", "barn": "#8c4a4a", "shed": "#7a5a42", "high-tunnel": "#d5dde0"}
TREE_COLORS = {"orchard": "#6f9a4a", "food-forest": "#5f8a3e", "berries": "#7a9a4e", "shade-tree": "#55784f",
               "windbreak": "#3d5e3a", "hedgerow": "#4f6e44", "riparian": "#4f7f56", "existing-forest": "#3f5c40"}


@router.get("/api/projects/{project_id}/plan-scene")
def scene(project_id: UUID, user: CurrentUser):
    """What the 3D view draws, in EPSG:4326, with the year each thing appears: buildings (footprint, height, roof),
    trees (position, mature height and canopy, years to full size; natural woodland as scattered trees), and
    ground areas. Sizes over time are estimates from USDA PLANTS growth rates and typical sizes (tr_kb.growth)."""
    from tr_kb import growth

    _project_or_404(project_id, user)
    site = load_site(project_id)
    phase_year = dict(zip((1, 2, 3), site["phase_years"]))
    srid, surface, _ = site_frame(project_id)
    pairs = features_in(project_id, srid)
    types = pf.types_by_id()
    colors = {c["id"]: c["color"] for c in pf.library()["categories"]}

    def year_of(r: dict) -> int:
        return -100 if r["status"] == "existing" else phase_year.get(int(r["build_phase"]), 0)

    symbols = sorted({sp["symbol"] for r, _ in pairs for sp in (r["props"] or {}).get("species") or []})
    traits = {row["symbol"]: row["traits"] or {} for row in fetch_all(
        "SELECT symbol, traits FROM species WHERE symbol = ANY(:s)", s=symbols)} if symbols else {}

    buildings, areas = [], []
    for r, g in pairs:
        t = types[r["type"]]
        base = {"id": str(r["id"]), "type": r["type"], "label": r["label"], "year": year_of(r), "status": r["status"]}
        if "building" in t["fields"] and g.geom_type == "Polygon":
            h = float((r["props"] or {}).get("height_m") or t["defaults"].get("height_m") or 4)
            roof = (r["props"] or {}).get("roof") or t["defaults"].get("roof") or "gable"
            ridge = 0 if roof == "flat" else min(h * 0.35, 4.0)
            wall = h - ridge
            buildings.append({"type": "Feature", "geometry": mapping(_ll(g, srid)),
                              "properties": {**base, "height_m": round(wall, 2), "part": "walls",
                                             "color": BUILDING_COLORS.get(r["type"], "#a35454")}})
            if ridge:
                # A narrower block along the long axis reads as a gable or hip roof at site scale.
                mrr = g.minimum_rotated_rectangle
                xs = list(mrr.exterior.coords)[:4]
                e1 = LineString([xs[0], xs[1]]).length
                e2 = LineString([xs[1], xs[2]]).length
                shrink = (0.5, 0.92) if roof in ("gable", "shed") else (0.5, 0.6)
                (ax, ay), (bx, by) = (xs[0], xs[1]) if e1 >= e2 else (xs[1], xs[2])
                ang = math.degrees(math.atan2(by - ay, bx - ax))
                cap = affinity.rotate(mrr, -ang, origin="centroid")
                cap = affinity.scale(cap, xfact=shrink[1], yfact=shrink[0], origin="centroid")
                cap = affinity.rotate(cap, ang, origin="centroid")
                buildings.append({"type": "Feature", "geometry": mapping(_ll(cap, srid)),
                                  "properties": {**base, "base_m": round(wall, 2), "height_m": round(h, 2), "part": "roof",
                                                 "color": "#6f6d68" if r["type"] != "high-tunnel" else "#c6cfd1"}})
        elif g.geom_type == "Polygon":
            areas.append({"type": "Feature", "geometry": mapping(_ll(g, srid)),
                          "properties": {**base, "category": r["category"], "color": colors.get(r["category"], "#888888")}})

    lays = planting_layout(project_id, srid, surface, pairs)
    groups = []  # (row, points in the projected CRS)
    for v in lays.values():
        if v["row"]["type"] not in WOODLAND_TYPES:
            groups.append((v["row"], list(v["layout"].points)))
    for r, g in pairs:
        if r["type"] in WOODLAND_TYPES and g.geom_type == "Polygon":
            sp_traits = [traits[s["symbol"]] for s in (r["props"] or {}).get("species") or [] if s["symbol"] in traits]
            _, c, _ = growth.mature_size(r["type"], r["props"] or {}, sp_traits, types[r["type"]]["defaults"])
            groups.append((r, scatter(g, spacing=max(c * 0.8, 3.0), seed=str(r["id"]))))
    total = sum(len(pts) for _, pts in groups) or 1
    step = max(1, -(-total // MAX_SCENE_TREES))  # ceil: thin evenly when over the budget
    trees, kinds = [], []
    for r, pts in groups:
        sp_traits = [traits[s["symbol"]] for s in (r["props"] or {}).get("species") or [] if s["symbol"] in traits]
        h, c, yrs = growth.mature_size(r["type"], r["props"] or {}, sp_traits, types[r["type"]]["defaults"])
        if r["type"] not in kinds:
            kinds.append(r["type"])
        k = kinds.index(r["type"])
        y = year_of(r)
        for x, yy in pts[::step]:
            q = _ll(Point(x, yy), srid)
            trees.append([round(q.x, 7), round(q.y, 7), h, c, yrs, y, k])
    return {
        "phase_years": site["phase_years"],
        "buildings": {"type": "FeatureCollection", "features": buildings},
        "areas": {"type": "FeatureCollection", "features": areas},
        # [lon, lat, mature height m, canopy diameter m, years to full size, year planted, kind index]
        "trees": trees,
        "tree_kinds": [{"type": k, "color": TREE_COLORS.get(k, "#5f8a3e")} for k in kinds],
        "trees_thinned": step > 1,
        "terrain": surface is not None,
    }


def scatter(poly, spacing: float, seed: str) -> list[tuple[float, float]]:
    """Points filling a polygon like natural woodland: a grid at `spacing` with each point nudged up to 40% of the
    spacing, repeatable for the same feature (seeded by its id). Projected CRS, metres."""
    import random

    rnd = random.Random(seed)
    x0, y0, x1, y1 = poly.bounds
    pts = []
    y = y0 + spacing / 2
    while y < y1:
        x = x0 + spacing / 2
        while x < x1:
            p = (x + rnd.uniform(-0.4, 0.4) * spacing, y + rnd.uniform(-0.4, 0.4) * spacing)
            if poly.contains(Point(p)):
                pts.append(p)
            x += spacing
        y += spacing
    return pts
