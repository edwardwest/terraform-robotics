"""Stage 2 design: keylines, rip patterns and swales, computed from the terrain model by tr_geo.design."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from shapely import wkb
from shapely.geometry import LineString, Point, mapping
from shapely.ops import unary_union

from tr_geo import project_geometry
from tr_geo import design as geo

from . import schemas
from .auth import CurrentUser
from .common import _project_or_404, boundary_in, layer_in, terrain_surface
from .db import execute, fetch_all, fetch_one, transaction

router = APIRouter()

ELEMENT_SELECT = """
SELECT id, kind, group_id, label, params, properties, created_at,
       ST_AsGeoJSON(geom, 7)::json AS geometry, ST_Length(geom::geography) AS length_m
FROM design_elements
"""


def _grade_gate(summary: dict, allow_planning: bool) -> str:
    """The terrain grade the design sits on; refuses coarse data, and planning data unless allowed."""
    q = summary.get("quality", {})
    if q.get("design_pct", 0) >= 50:
        return "design"
    if q.get("coarse_pct", 0) >= 50:
        raise HTTPException(409, "The terrain model is too coarse for keyline design. Add a drone LiDAR or RTK survey.")
    if not allow_planning:
        raise HTTPException(
            409,
            "The terrain model is planning grade, so lines may be off by a metre or more in the field. "
            "Add a drone LiDAR or RTK survey for design grade, or generate a draft on planning-grade data.",
        )
    return "planning"


def _feature(row: dict) -> dict:
    props = {**(row["properties"] or {}), "id": str(row["id"]), "kind": row["kind"], "label": row["label"],
             "group_id": str(row["group_id"]) if row["group_id"] else None, "length_m": round(float(row["length_m"]), 1)}
    return {"type": "Feature", "geometry": row["geometry"], "properties": props}


def _to_lnglat(geom, crs: str):
    return project_geometry(geom, crs, "EPSG:4326")


INSERT_SQL = """INSERT INTO design_elements (project_id, kind, group_id, label, geom, params, properties)
           VALUES (:pid, :kind, :gid, :label, ST_SetSRID(ST_GeomFromWKB(:g), 4326), CAST(:params AS jsonb),
                   CAST(:props AS jsonb))"""


def _row(project_id: UUID, kind: str, label: str, geom_ll, params: dict, props: dict, group_id: str | None) -> dict:
    return {"pid": str(project_id), "kind": kind, "gid": group_id, "label": label, "g": wkb.dumps(geom_ll),
            "params": json.dumps(params), "props": json.dumps(props)}


def _site_context(project_id: UUID):
    t, surface, srid = terrain_surface(project_id)
    boundary = boundary_in(project_id, srid)
    ridges = unary_union([g for g, _ in layer_in(project_id, "ridges", srid)])
    valleys = layer_in(project_id, "valleys", srid)  # (geometry, properties) pairs
    return t, surface, srid, boundary, ridges, valleys


@router.get("/api/projects/{project_id}/design")
def get_design(project_id: UUID, user: CurrentUser):
    _project_or_404(project_id, user)
    rows = fetch_all(ELEMENT_SELECT + " WHERE project_id = :id ORDER BY created_at, label", id=str(project_id))
    return {"type": "FeatureCollection", "features": [_feature(r) for r in rows]}


@router.post("/api/projects/{project_id}/design/keylines", response_model=schemas.KeylineResult)
def create_keyline(project_id: UUID, body: schemas.KeylineCreate, user: CurrentUser):
    _project_or_404(project_id, user)
    t, surface, srid, boundary, ridges, valley_rows = _site_context(project_id)
    valleys = [g for g, _ in valley_rows]
    grade_label = _grade_gate(t["summary"], body.allow_planning)
    kp_rows = layer_in(project_id, "keypoints", srid, "AND properties->>'id' = :kp", kp=body.keypoint_id)
    if not kp_rows:
        raise HTTPException(404, f"Keypoint {body.keypoint_id} not found")
    kp: Point = kp_rows[0][0]
    step = max(surface.res, 1.0)
    stops = geo.Stops(geo.keyline_stops(ridges, valleys, kp), step)
    try:
        keyline, arms = geo.keyline_through(surface, (kp.x, kp.y), body.grade, stops=stops, within=boundary, step=step)
    except ValueError as e:
        raise HTTPException(422, str(e))
    # the keypoint's main valley stem: seeds graded lines and decides which pattern lines belong to it
    valley = geo.valley_trunk(valley_rows, kp) or geo.valley_near(valleys, kp)
    system = valley
    truncated = False

    if body.pattern == "parallel":
        lines = geo.parallel_pattern(surface, keyline, body.spacing_m, boundary, max_lines=body.max_lines,
                                     valley=system if body.extent == "valley" else None,
                                     ridges=ridges if body.extent == "valley" else None)
    elif body.pattern == "graded":
        if valley is None:
            raise HTTPException(422, "No valley line passes near this keypoint to seed graded lines from")
        # graded lines start on the valley line itself, so only the other valleys (and ridges) stop them
        others = unary_union(valleys).difference(valley.buffer(5)) if valleys else None
        stop_parts = [g for g in (ridges, others) if g is not None and not g.is_empty]
        graded_stops = unary_union(stop_parts) if stop_parts else None
        lines, truncated = geo.graded_pattern(surface, valley, (kp.x, kp.y), body.spacing_m, body.grade, boundary,
                                              stops=geo.Stops(graded_stops, step), max_lines=body.max_lines, step=step)
    else:
        lines = []

    group_id = str(uuid4())
    params = {**body.model_dump(), "terrain_grade": grade_label}
    draft = grade_label != "design"
    km = geo.line_metrics(surface, keyline, system or valley)
    rows = [_row(project_id, "keyline", f"Keyline {body.keypoint_id}", _to_lnglat(keyline, t["dem_crs"]), params,
                 {**km, "keypoint_id": body.keypoint_id, "draft": draft, "stops": [a.stop for a in arms]}, group_id)]

    # Rip lines are labelled top to bottom, which is also the default pass order.
    measured = []
    for pl in lines:
        m = geo.line_metrics(surface, pl.geom, system or valley)
        measured.append((pl, m))
    measured.sort(key=lambda pm: -max(pm[1].get("z_start_m", 0), pm[1].get("z_end_m", 0)))
    notes_all: list[str] = []
    toward = steep = 0
    for i, (pl, m) in enumerate(measured, start=1):
        notes = geo.check_rip(m)
        toward += geo.TOWARD_VALLEY in notes
        steep += any("scour" in n for n in notes)
        rows.append(_row(project_id, "rip", f"R{i}", _to_lnglat(pl.geom, t["dem_crs"]), params,
                         {**pl.props, **m, "pass": i, "notes": notes, "draft": draft}, group_id))
    # Replace this keypoint's previous pattern in one transaction, so a failure leaves the old one intact.
    with transaction() as tx:
        tx.execute("SELECT pg_advisory_xact_lock(hashtext(:k))", k=f"{project_id}:{body.keypoint_id}")
        tx.execute("DELETE FROM design_elements WHERE project_id = :pid AND params->>'keypoint_id' = :kp",
                   pid=str(project_id), kp=body.keypoint_id)
        tx.execute_many(INSERT_SQL, rows)
    total = sum(pl.geom.length for pl, _ in measured)
    treated = 0.0
    if measured:
        treated = unary_union([pl.geom.buffer(body.spacing_m / 2, cap_style="flat") for pl, _ in measured]).intersection(boundary).area
    if toward:
        notes_all.append(f"{toward} of {len(measured)} rip lines carry some water back toward the valley.")
    if steep:
        notes_all.append(f"{steep} of {len(measured)} rip lines fall steeper than 1:100 somewhere; watch for scour. "
                         "On steep ground, 'Each line graded' keeps every line at the design grade.")
    if draft:
        notes_all.append("Draft on planning-grade terrain: confirm with a field survey before ripping.")
    if truncated:
        notes_all.append("Stopped early to keep the request quick; widen the spacing to cover the whole valley.")
    if any(a.stop == "terrain" for a in arms):
        notes_all.append("One arm of the keyline ended where the ground went flat or broke away, before a ridge.")

    row = fetch_one(ELEMENT_SELECT + " WHERE project_id = :pid AND group_id = :gid AND kind = 'keyline'",
                    pid=str(project_id), gid=group_id)
    return {
        "group_id": group_id,
        "keyline": _feature(row),
        "rip_count": len(measured),
        "rip_length_m": round(total, 1),
        "area_treated_m2": round(treated, 1),
        "terrain_grade": grade_label,
        "notes": notes_all,
    }


@router.post("/api/projects/{project_id}/design/swales", response_model=schemas.DesignFeature)
def create_swale(project_id: UUID, body: schemas.SwaleCreate, user: CurrentUser):
    _project_or_404(project_id, user)
    t, surface, srid, boundary, _, _ = _site_context(project_id)
    grade_label = _grade_gate(t["summary"], body.allow_planning)
    to_dem = lambda c: project_geometry(Point(c), "EPSG:4326", t["dem_crs"])  # noqa: E731
    start, end = to_dem(body.start), to_dem(body.end)
    if not boundary.contains(start):
        raise HTTPException(422, "Start the swale inside the property")
    try:
        sw = geo.swale_on_contour(surface, (start.x, start.y), (end.x, end.y))
    except ValueError as e:
        raise HTTPException(422, str(e))
    clipped = sw.geom.intersection(boundary)
    parts = [p for p in getattr(clipped, "geoms", [clipped]) if isinstance(p, LineString)]
    if not parts:
        raise HTTPException(422, "The swale falls outside the property")
    sw = geo.Swale(max(parts, key=lambda p: p.length), sw.elevation_m, sw.end_offset_m)
    major = unary_union([g for g, p in layer_in(project_id, "flow", srid) if p.get("major")])
    m, notes = geo.swale_metrics(surface, sw, body.width_m, body.depth_m, boundary=boundary, major_flow=major)
    n = fetch_one("SELECT count(*) AS n FROM design_elements WHERE project_id = :pid AND kind = 'swale'", pid=str(project_id))["n"]
    label = f"S{n + 1}"
    eid = str(uuid4())
    execute(
        """INSERT INTO design_elements (id, project_id, kind, label, geom, params, properties)
           VALUES (:id, :pid, 'swale', :label, ST_SetSRID(ST_GeomFromWKB(:g), 4326), CAST(:params AS jsonb), CAST(:props AS jsonb))""",
        id=eid, pid=str(project_id), label=label, g=wkb.dumps(_to_lnglat(sw.geom, t["dem_crs"])),
        params=json.dumps({**body.model_dump(), "terrain_grade": grade_label}),
        props=json.dumps({**m, "notes": notes, "berm": body.berm, "draft": grade_label != "design"}),
    )
    return _feature(fetch_one(ELEMENT_SELECT + " WHERE id = :id", id=eid))


@router.delete("/api/projects/{project_id}/design/elements/{element_id}", status_code=204)
def delete_element(project_id: UUID, element_id: UUID, user: CurrentUser):
    _project_or_404(project_id, user)
    row = fetch_one("SELECT kind, group_id FROM design_elements WHERE id = :id AND project_id = :pid",
                    id=str(element_id), pid=str(project_id))
    if not row:
        raise HTTPException(404, "Design element not found")
    if row["kind"] == "keyline" and row["group_id"]:
        execute("DELETE FROM design_elements WHERE project_id = :pid AND group_id = :gid", pid=str(project_id), gid=str(row["group_id"]))
    else:
        execute("DELETE FROM design_elements WHERE id = :id", id=str(element_id))


@router.get("/api/projects/{project_id}/design/elements/{element_id}/profile", response_model=schemas.Profile)
def element_profile(project_id: UUID, element_id: UUID, user: CurrentUser, samples: int = 300):
    _project_or_404(project_id, user)
    t, surface, srid = terrain_surface(project_id)
    row = fetch_one("SELECT ST_AsBinary(ST_Transform(geom, :srid)) AS g FROM design_elements WHERE id = :id AND project_id = :pid",
                    id=str(element_id), pid=str(project_id), srid=srid)
    if not row:
        raise HTTPException(404, "Design element not found")
    line = wkb.loads(bytes(row["g"]))
    d, z = surface.profile(line, step=max(line.length / max(samples - 1, 1), surface.res / 2))
    return {"distance_m": [round(float(v), 2) for v in d], "elevation_m": [None if v != v else round(float(v), 2) for v in z]}


def design_lines(project_id: UUID) -> list[dict]:
    """Design rows with shapely geometry in lon/lat, for estimates and exports."""
    rows = fetch_all(
        """SELECT id, kind, group_id, label, params, properties, ST_AsBinary(geom) AS g, ST_Length(geom::geography) AS length_m
           FROM design_elements WHERE project_id = :id ORDER BY kind, label""",
        id=str(project_id),
    )
    for r in rows:
        r["geom"] = wkb.loads(bytes(r.pop("g")))
    return rows


__all__ = ["router", "design_lines", "mapping"]
