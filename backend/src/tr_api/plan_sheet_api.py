"""Master plan sheet: settings, SVG preview and PDF.

One renderer (master_sheet.render) draws the sheet as SVG; the web app shows that SVG as a live preview (and lets
people drag labels on it), and the PDF is the same SVG converted by cairosvg, so the preview is what prints.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from shapely import wkb

from tr_geo import utm_crs_for
from tr_kb import plan_features as pf

from . import basemap, schemas
from .auth import CurrentUser
from .common import _project_or_404, dem_local_path
from .db import execute, fetch_all, fetch_one
from .master_sheet import SheetFeature, SheetInput, frame_for, pdf_with_base, render
from .plan_features_api import feature_rows

log = logging.getLogger(__name__)
router = APIRouter()

PREVIEW_DPI = 110
PDF_DPI = 200
MAX_BASE_PX = 3600
MAX_CONTOURS = 1500


def load_settings(project_id: UUID) -> dict:
    row = fetch_one("SELECT settings FROM plan_sheets WHERE project_id = :id", id=str(project_id))
    stored = (row or {}).get("settings") or {}
    try:
        return schemas.PlanSheetSettings(**stored).model_dump()
    except Exception:  # noqa: BLE001 - settings from an older version: keep what still validates
        good = {}
        for k, v in stored.items():
            try:
                schemas.PlanSheetSettings(**{k: v})
                good[k] = v
            except Exception:  # noqa: BLE001
                continue
        return schemas.PlanSheetSettings(**good).model_dump()


def _sheet_input(project_id: UUID, user, settings: dict, dpi: int) -> tuple[SheetInput, str]:
    """What the sheet draws, and the base map actually used: aerial, terrain or plain."""
    project = _project_or_404(project_id, user)
    b = fetch_one("SELECT ST_X(ST_Centroid(boundary)) AS lon, ST_Y(ST_Centroid(boundary)) AS lat FROM projects WHERE id = :id",
                  id=str(project_id))
    crs = utm_crs_for(b["lon"], b["lat"])
    srid = int(crs.split(":")[1])
    brow = fetch_one("SELECT ST_AsBinary(ST_Transform(boundary, :srid)) AS g FROM projects WHERE id = :id",
                     id=str(project_id), srid=srid)
    boundary = wkb.loads(bytes(brow["g"])) if brow and brow["g"] else None
    if boundary is not None and boundary.geom_type != "Polygon":
        boundary = max(getattr(boundary, "geoms", [boundary]), key=lambda g: g.area)

    hidden = set(settings["hidden_categories"])
    phases = settings["phases"]
    rows = [r for r in feature_rows(project_id)
            if r["category"] not in hidden
            and (settings["show_existing"] if r["status"] == "existing" else (phases == 0 or r["build_phase"] <= phases))]
    geoms = {}
    if rows:
        for g in fetch_all("SELECT id, ST_AsBinary(ST_Transform(geom, :srid)) AS g FROM plan_features WHERE project_id = :id",
                           id=str(project_id), srid=srid):
            geoms[str(g["id"])] = wkb.loads(bytes(g["g"]))
    types = pf.types_by_id()
    features = [SheetFeature(id=str(r["id"]), type=r["type"], type_label=types[r["type"]]["label"], category=r["category"],
                             label=r["label"], status=r["status"], build_phase=r["build_phase"], geom=geoms[str(r["id"])],
                             props=r["props"], plant_count=pf.plant_count(types[r["type"]], r["props"], r["area_m2"], r["length_m"]))
                for r in rows if str(r["id"]) in geoms]

    terrain = fetch_one("SELECT dem_path, dem_crs, job_id, summary FROM terrain_results WHERE project_id = :id", id=str(project_id))
    contours = []
    if settings["contours"] and terrain:
        crow = fetch_all(
            """SELECT ST_AsBinary(ST_SimplifyPreserveTopology(ST_Transform(geom, :srid), 0.5)) AS g,
                      coalesce((properties->>'index')::boolean, false) AS idx
               FROM terrain_features WHERE project_id = :id AND layer = 'contours'""", id=str(project_id), srid=srid)
        if len(crow) > MAX_CONTOURS:  # dense terrain: index contours only
            crow = [c for c in crow if c["idx"]] or crow[:MAX_CONTOURS]
        for c in crow:
            g = wkb.loads(bytes(c["g"]))
            contours.extend(getattr(g, "geoms", [g]))

    inp = SheetInput(project_name=project["name"], address=project.get("address"), boundary=boundary, features=features,
                     categories=pf.library()["categories"], settings=settings, contours=contours)
    frame = frame_for(settings, features, boundary)
    bounds = frame.bounds_m()
    px_w = min(MAX_BASE_PX, int((frame.x1 - frame.x0) / 72 * dpi))
    px_h = min(MAX_BASE_PX, int((frame.y1 - frame.y0) / 72 * dpi))
    rgb, credit, used = None, None, "plain"
    if settings["base"] == "aerial":
        rgb = basemap.aerial(crs, bounds, px_w, px_h)
        if rgb is not None:
            credit, used = basemap.AERIAL_ATTRIBUTION, "aerial"
    if rgb is None and settings["base"] in ("aerial", "terrain") and terrain:
        try:
            rgb = basemap.hillshade(dem_local_path(terrain), crs, bounds, px_w, px_h)
            used = "terrain" if rgb is not None else used
        except Exception:  # noqa: BLE001 - storage trouble: plain base
            log.warning("sheet: terrain shading unavailable", exc_info=True)
    if rgb is not None:
        inp.base_jpeg, inp.base_bounds, inp.base_credit = basemap.jpeg_bytes(rgb), bounds, credit
    return inp, used


@router.get("/api/projects/{project_id}/plan-sheet", response_model=schemas.PlanSheetSettings)
def read_settings(project_id: UUID, user: CurrentUser):
    _project_or_404(project_id, user)
    return load_settings(project_id)


@router.put("/api/projects/{project_id}/plan-sheet", response_model=schemas.PlanSheetSettings)
def write_settings(project_id: UUID, body: schemas.PlanSheetSettings, user: CurrentUser):
    _project_or_404(project_id, user)
    cats = {c["id"] for c in pf.library()["categories"]}
    if not set(body.hidden_categories) <= cats:
        raise HTTPException(422, f"Unknown categories: {', '.join(sorted(set(body.hidden_categories) - cats))}")
    execute(
        """INSERT INTO plan_sheets (project_id, settings) VALUES (:id, CAST(:s AS jsonb))
           ON CONFLICT (project_id) DO UPDATE SET settings = EXCLUDED.settings, updated_at = now()""",
        id=str(project_id), s=json.dumps(body.model_dump()))
    return load_settings(project_id)


@router.get("/api/projects/{project_id}/plan-sheet/svg")
def sheet_svg(project_id: UUID, user: CurrentUser):
    """The sheet as SVG at preview resolution (base image ~110 dpi), drawn from the saved settings. The base map
    actually drawn (aerial, terrain or plain; aerial falls back when the imagery can't be reached) is in X-Sheet-Base."""
    _project_or_404(project_id, user)
    inp, used = _sheet_input(project_id, user, load_settings(project_id), PREVIEW_DPI)
    return Response(render(inp), media_type="image/svg+xml", headers={"Cache-Control": "no-store", "X-Sheet-Base": used})


@router.get("/api/projects/{project_id}/export/master-plan.pdf")
def sheet_pdf(project_id: UUID, user: CurrentUser, inline: bool = Query(False)):
    """The sheet as a print PDF (base image ~200 dpi, kept as JPEG)."""
    from .outputs import _download, _slug

    project = _project_or_404(project_id, user)
    inp, _ = _sheet_input(project_id, user, load_settings(project_id), PDF_DPI)
    pdf = pdf_with_base(inp)
    if inline:
        return Response(pdf, media_type="application/pdf")
    return _download(pdf, f"{_slug(project['name'])}-master-plan.pdf", "application/pdf")
