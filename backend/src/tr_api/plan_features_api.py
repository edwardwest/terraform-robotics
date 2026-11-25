"""Master plan features: things a person places on the map (ponds, orchards, buildings, roads...).

Types, categories and map colors come from the feature library (tr_kb/rules/plan_features.yaml). Areas and lengths
are measured by PostGIS on the spheroid. A feature that places a catalog intervention adds that intervention to the
plan, and placed features replace the plan's planning quantity in the estimate (see plan_api.plan_rows).
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException
from shapely.geometry import shape

from tr_kb import interventions as iv
from tr_kb import plan_features as pf

from . import schemas
from .auth import CurrentUser
from .common import _project_or_404
from .db import execute, fetch_all, fetch_one

router = APIRouter()

MAX_VERTICES = 5000
NEAR_BOUNDARY_M = 500  # features must touch the property or sit within this distance of it

FEATURE_SELECT = """
SELECT id, type, label, status, build_phase, props, created_at, updated_at,
       ST_AsGeoJSON(geom, 7)::json AS geometry,
       CASE WHEN GeometryType(geom) = 'POLYGON' THEN ST_Area(geom::geography) END AS area_m2,
       CASE WHEN GeometryType(geom) = 'LINESTRING' THEN ST_Length(geom::geography)
            WHEN GeometryType(geom) = 'POLYGON' THEN ST_Perimeter(geom::geography) END AS length_m
FROM plan_features
"""


def feature_rows(project_id: UUID) -> list[dict]:
    """Placed features with measurements; types no longer in the library are skipped."""
    types = pf.types_by_id()
    rows = fetch_all(FEATURE_SELECT + " WHERE project_id = :id ORDER BY created_at, id", id=str(project_id))
    out = []
    for r in rows:
        t = types.get(r["type"])
        if not t:
            continue
        area = float(r["area_m2"]) if r["area_m2"] is not None else None
        length = float(r["length_m"]) if r["length_m"] is not None and t["geometry"] == "line" else None
        perimeter = float(r["length_m"]) if r["length_m"] is not None and t["geometry"] == "polygon" else None
        out.append({**r, "area_m2": area, "length_m": length, "perimeter_m": perimeter, "category": t["category"],
                    "intervention": t["intervention"], "props": r["props"] or {}})
    return out


def as_feature(r: dict) -> dict:
    t = pf.types_by_id()[r["type"]]
    color = pf.categories_by_id()[t["category"]]["color"]
    return {
        "type": "Feature",
        "geometry": r["geometry"],
        "properties": {
            "id": str(r["id"]), "type": r["type"], "type_label": t["label"], "category": t["category"], "color": color,
            "label": r["label"], "status": r["status"], "build_phase": r["build_phase"], "props": r["props"],
            "intervention": t["intervention"],
            "area_m2": round(r["area_m2"], 1) if r["area_m2"] is not None else None,
            "length_m": round(r["length_m"], 1) if r["length_m"] is not None else None,
            "perimeter_m": round(r["perimeter_m"], 1) if r["perimeter_m"] is not None else None,
            "plant_count": pf.plant_count(t, r["props"], r["area_m2"], r["length_m"]),
            "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat(),
        },
    }


def _check_geometry(geometry: dict, ftype: dict) -> str:
    """GeoJSON text of a valid geometry of the type's kind, or a 422."""
    try:
        g = shape(geometry)
    except Exception as e:  # noqa: BLE001 - any parse failure is the client's
        raise HTTPException(422, f"Not a GeoJSON geometry: {e}") from e
    want = pf.GEOMETRIES[ftype["geometry"]]
    if g.geom_type != want:
        raise HTTPException(422, f"A {ftype['label'].lower()} is drawn as a {ftype['geometry']}, not a {g.geom_type}")
    if g.is_empty:
        raise HTTPException(422, "The shape is empty")
    coords = list(g.exterior.coords) if want == "Polygon" else list(g.coords)
    if len(coords) > MAX_VERTICES:
        raise HTTPException(422, f"The shape has more than {MAX_VERTICES:,} points")
    if any(not (-180 <= x <= 180 and -90 <= y <= 90) for x, y, *_ in coords):
        raise HTTPException(422, "Coordinates must be longitude and latitude (EPSG:4326)")
    if want == "Polygon":
        if len(g.interiors):
            raise HTTPException(422, "Areas with holes aren't supported yet")
        if not g.is_valid or g.area == 0:
            raise HTTPException(422, "The area crosses over itself. Redraw it without crossing lines.")
    if want == "LineString" and g.length == 0:
        raise HTTPException(422, "A line needs two different points")
    xy = [list(c[:2]) for c in coords]
    coordinates = xy[0] if want == "Point" else [xy] if want == "Polygon" else xy
    return json.dumps({"type": want, "coordinates": coordinates})


def _check_near(project_id: UUID, geojson: str) -> None:
    row = fetch_one(
        """SELECT ST_DWithin(ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)::geography, boundary::geography, :d) AS ok
           FROM projects WHERE id = :id""",
        g=geojson, id=str(project_id), d=NEAR_BOUNDARY_M)
    if row and row["ok"] is False:
        raise HTTPException(422, "That's well outside the property. Place features on or near the land.")


def _check_props(props: dict, ftype: dict) -> dict:
    """Keep only settings the type takes; species must exist in the PLANTS table."""
    allowed = _allowed_keys(ftype)
    extra = {k for k, v in props.items() if v is not None} - allowed
    if extra:
        raise HTTPException(422, f"A {ftype['label'].lower()} doesn't take {', '.join(sorted(extra))}")
    clean = {k: v for k, v in props.items() if v is not None and k in allowed}
    if clean.get("species"):
        symbols = [s["symbol"] for s in clean["species"]]
        if len(set(symbols)) != len(symbols):
            raise HTTPException(422, "A species is listed twice")
        found = {r["symbol"]: r for r in fetch_all(
            "SELECT symbol, scientific_name, common_name FROM species WHERE symbol = ANY(:s)", s=symbols)}
        missing = [s for s in symbols if s not in found]
        if missing:
            raise HTTPException(422, f"Unknown USDA PLANTS symbol: {', '.join(missing)}")
        # Names come from the table, not the client.
        clean["species"] = [{"symbol": s, "scientific_name": found[s]["scientific_name"],
                             "common_name": found[s]["common_name"]} for s in symbols]
    return clean


def _ensure_in_plan(project_id: UUID, intervention_id: str | None) -> None:
    if not intervention_id:
        return
    item = iv.by_id()[intervention_id]
    execute(
        """INSERT INTO project_plan (project_id, intervention_id, quantity) VALUES (:pid, :iid, :qty)
           ON CONFLICT (project_id, intervention_id) DO NOTHING""",
        pid=str(project_id), iid=intervention_id, qty=(item["quantity"] or {}).get("default"))


def _feature_or_404(project_id: UUID, feature_id: UUID) -> dict:
    r = next((r for r in feature_rows(project_id) if str(r["id"]) == str(feature_id)), None)
    if not r:
        raise HTTPException(404, "Feature not found")
    return r


# ---- Routes ----------------------------------------------------------------------------------------


@router.get("/api/plan-features/library")
def read_library(user: CurrentUser):
    """Categories (with map colors), placeable types and their settings."""
    return pf.public_library()


@router.get("/api/projects/{project_id}/plan-features", response_model=schemas.PlanFeatureCollection)
def list_features(project_id: UUID, user: CurrentUser):
    _project_or_404(project_id, user)
    return {"type": "FeatureCollection", "features": [as_feature(r) for r in feature_rows(project_id)]}


@router.post("/api/projects/{project_id}/plan-features", response_model=schemas.PlanFeature, status_code=201)
def create_feature(project_id: UUID, body: schemas.PlanFeatureCreate, user: CurrentUser):
    _project_or_404(project_id, user)
    ftype = pf.types_by_id().get(body.type)
    if not ftype:
        raise HTTPException(422, f"Unknown feature type {body.type}")
    geojson = _check_geometry(body.geometry, ftype)
    _check_near(project_id, geojson)
    given = body.props.model_dump(exclude_unset=True) if body.props else {}
    props = _check_props({**ftype["defaults"], **given}, ftype)
    row = fetch_one(
        """INSERT INTO plan_features (project_id, type, label, status, build_phase, geom, props)
           VALUES (:pid, :type, :label, :status, :phase, ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326), CAST(:props AS jsonb))
           RETURNING id""",
        pid=str(project_id), type=body.type, label=(body.label or ftype["label"]).strip(),
        status=body.status or ftype["status"], phase=body.build_phase or 1, g=geojson, props=json.dumps(props))
    _ensure_in_plan(project_id, ftype["intervention"])
    return as_feature(_feature_or_404(project_id, row["id"]))


@router.patch("/api/projects/{project_id}/plan-features/{feature_id}", response_model=schemas.PlanFeature)
def update_feature(project_id: UUID, feature_id: UUID, body: schemas.PlanFeatureUpdate, user: CurrentUser):
    """Change the label, status, build phase, settings, shape, or the type within the same geometry kind.
    `props` replaces the settings as a whole."""
    _project_or_404(project_id, user)
    current = _feature_or_404(project_id, feature_id)
    fields = body.model_dump(exclude_unset=True)
    ftype = pf.types_by_id()[current["type"]]
    sets, params = [], {"id": str(feature_id), "pid": str(project_id)}
    if "type" in fields and fields["type"] != current["type"]:
        new = pf.types_by_id().get(fields["type"])
        if not new:
            raise HTTPException(422, f"Unknown feature type {fields['type']}")
        if new["geometry"] != ftype["geometry"]:
            raise HTTPException(422, f"Change to a type drawn as a {ftype['geometry']}, or draw a new feature")
        ftype = new
        sets.append("type = :type")
        params["type"] = new["id"]
        if "props" not in fields:  # keep the settings the new type takes, fill in its defaults
            kept = {k: v for k, v in current["props"].items() if k in _allowed_keys(new)}
            fields["props"] = {**new["defaults"], **kept}
    if "label" in fields:
        sets.append("label = :label")
        params["label"] = (fields["label"] or ftype["label"]).strip()
    if fields.get("status"):
        sets.append("status = :status")
        params["status"] = fields["status"]
    if fields.get("build_phase"):
        sets.append("build_phase = :phase")
        params["phase"] = fields["build_phase"]
    if "props" in fields:
        sets.append("props = CAST(:props AS jsonb)")
        params["props"] = json.dumps(_check_props(fields["props"] or {}, ftype))
    if fields.get("geometry"):
        g = _check_geometry(fields["geometry"], ftype)
        _check_near(project_id, g)
        sets.append("geom = ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)")
        params["g"] = g
    if sets:
        execute(f"UPDATE plan_features SET {', '.join(sets)}, updated_at = now() WHERE id = :id AND project_id = :pid", **params)
        _ensure_in_plan(project_id, ftype["intervention"])
    return as_feature(_feature_or_404(project_id, feature_id))


def _allowed_keys(ftype: dict) -> set[str]:
    keys = {"notes"}
    if "species" in ftype["fields"]:
        keys |= {"species", "plant_spacing_m", "row_spacing_m", "rows", "height_m"}
    if "building" in ftype["fields"]:
        keys |= {"height_m", "roof"}
    if "capacity" in ftype["fields"]:
        keys |= {"capacity_m3"}
    return keys


@router.delete("/api/projects/{project_id}/plan-features/{feature_id}", status_code=204)
def delete_feature(project_id: UUID, feature_id: UUID, user: CurrentUser):
    """Removes the feature only; the plan keeps the intervention (with its planning quantity) until removed there."""
    _project_or_404(project_id, user)
    execute("DELETE FROM plan_features WHERE id = :id AND project_id = :pid", id=str(feature_id), pid=str(project_id))
