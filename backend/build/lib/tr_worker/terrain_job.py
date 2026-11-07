"""The terrain job: gather elevation sources → working DEM → analysis → layers saved to PostGIS.

Runs in a thread under the API locally, or as the `terrain-worker` Cloud Run Job (`tr-worker terrain <job_id>`).
Progress is written to the `jobs` row so the web app can poll it.
"""

from __future__ import annotations

import json
import logging
import tempfile
import traceback
from pathlib import Path

import numpy as np
from shapely.geometry import mapping, shape

from tr_api.config import get_settings
from tr_api.db import execute, fetch_all, fetch_one, get_engine
from tr_api.storage import get_storage
from tr_geo import Dem, Params, analyze, grade_for, polygon_mask, project_geometry, utm_crs_for, write_geotiff
from tr_geo.dem import grid_for_bounds, resample_to_grid, working_resolution

from . import sources

log = logging.getLogger(__name__)

STEPS = ["Gathering elevation", "Building working DEM", "Analysing water and landforms", "Saving layers"]
GRADE_RANK = {"design": 0, "planning": 1, "coarse": 2}


def _step(job_id: str, index: int) -> None:
    execute(
        "UPDATE jobs SET step = :step, step_index = :i, step_count = :n WHERE id = :id",
        step=STEPS[index - 1], i=index, n=len(STEPS), id=job_id,
    )


def run_terrain_job(job_id: str) -> None:
    try:
        _run(job_id)
    except Exception as exc:  # record the failure for the app; keep the traceback in logs
        log.error("Terrain job %s failed\n%s", job_id, traceback.format_exc())
        execute(
            "UPDATE jobs SET status = 'failed', error = :err, finished_at = now() WHERE id = :id",
            err=str(exc)[:1000], id=job_id,
        )


def _run(job_id: str) -> None:
    settings = get_settings()
    storage = get_storage()
    job = fetch_one("SELECT project_id, params FROM jobs WHERE id = :id", id=job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    project_id = str(job["project_id"])
    params = job["params"] or {}
    execute("UPDATE jobs SET status = 'running', started_at = now() WHERE id = :id", id=job_id)

    # 1. Gather elevation sources ----------------------------------------------------------------
    _step(job_id, 1)
    row = fetch_one("SELECT ST_AsGeoJSON(boundary)::json AS b FROM projects WHERE id = :id", id=project_id)
    boundary_ll = shape(row["b"])
    crs = utm_crs_for(boundary_ll.centroid.x, boundary_ll.centroid.y)
    boundary = project_geometry(boundary_ll, "EPSG:4326", crs)
    extent = boundary.buffer(settings.catchment_buffer_m)

    surveys = fetch_all(
        "SELECT id, kind, storage_path FROM surveys WHERE project_id = :id AND status <> 'failed' ORDER BY created_at",
        id=project_id,
    )
    if not surveys:  # nothing uploaded: fall back to public elevation
        surveys.append(fetch_one(
            "INSERT INTO surveys (project_id, kind, filename) VALUES (:id, 'public_dem', 'USGS 3DEP') "
            "RETURNING id, kind, storage_path", id=project_id))

    gathered: list[tuple[sources.Source, str]] = []  # (source, grade)
    with tempfile.TemporaryDirectory(prefix="tr-terrain-") as tmp:
        for s in surveys:
            sid = str(s["id"])
            execute("UPDATE surveys SET status = 'processing', error = NULL WHERE id = :id", id=sid)
            try:
                src = _load_source(s, boundary_ll, crs, Path(tmp), storage)
                grade = grade_for(src.resolution_m, src.kind)
                execute(
                    "UPDATE surveys SET status = 'ready', resolution_m = :r, grade = :g WHERE id = :id",
                    r=round(src.resolution_m, 3), g=grade, id=sid,
                )
                gathered.append((src, grade))
            except Exception as exc:
                execute("UPDATE surveys SET status = 'failed', error = :e WHERE id = :id", e=str(exc)[:500], id=sid)
                log.warning("Survey %s could not be used: %s", sid, exc)
        if not gathered:
            raise RuntimeError("No usable elevation source. Upload a survey or check the public elevation fetch.")

        # 2. Working DEM: best source first, gaps filled by the next ------------------------------
        _step(job_id, 2)
        gathered.sort(key=lambda sg: (GRADE_RANK[sg[1]], sg[0].resolution_m))
        res = working_resolution(extent.area, min(s.resolution_m for s, _ in gathered))
        transform, shape_ = grid_for_bounds(extent.bounds, res)
        elevation = np.full(shape_, np.nan)
        grade_grid = np.full(shape_, "", dtype=object)
        for src, grade in gathered:
            layer = resample_to_grid(src.dem, transform, shape_, crs).elevation
            take = np.isnan(elevation) & ~np.isnan(layer)
            elevation[take] = layer[take]
            grade_grid[take] = grade
        dem = Dem(elevation, transform, crs)
        inside = polygon_mask(dem, boundary)
        n_inside = max(int(inside.sum()), 1)
        grades = {g: float((grade_grid[inside] == g).sum()) / n_inside for g in GRADE_RANK}
        grades["coarse"] += float((grade_grid[inside] == "").sum()) / n_inside  # uncovered counts as too coarse

        # 3. Analysis ------------------------------------------------------------------------------
        _step(job_id, 3)
        result = analyze(dem, boundary, Params(contour_interval_m=float(params.get("contour_interval_m", 0.6))), grades)

        # 4. Save ----------------------------------------------------------------------------------
        _step(job_id, 4)
        dem_key = f"projects/{project_id}/terrain/dem.tif"
        local_tif = str(Path(tmp) / "dem.tif")
        write_geotiff(dem, local_tif)
        storage.save_file(dem_key, local_tif)
        _save_results(project_id, job_id, result, dem_key, crs)

    execute("UPDATE jobs SET status = 'succeeded', step = 'Done', finished_at = now() WHERE id = :id", id=job_id)


def _load_source(survey: dict, boundary_ll, crs: str, tmp: Path, storage) -> sources.Source:
    kind = survey["kind"]
    if kind == "public_dem":
        return sources.fetch_3dep(boundary_ll, str(tmp / f"3dep-{survey['id']}.tif"))
    path = storage.local_path(survey["storage_path"])
    if kind == "lidar":
        return sources.lidar_to_dtm(path, str(tmp / f"dtm-{survey['id']}.tif"))
    if kind == "dem":
        return sources.geotiff(path)
    if kind == "contours":
        return sources.contours_to_dem(path, crs)
    raise ValueError(f"Unknown survey kind {kind}")


def _save_results(project_id: str, job_id: str, result, dem_key: str, crs: str) -> None:
    from sqlalchemy import text

    summary = dict(result.summary)
    ox, oy = summary.pop("outlet_xy")
    outlet_ll = project_geometry(shape({"type": "Point", "coordinates": [ox, oy]}), crs, "EPSG:4326")
    summary["outlet_lnglat"] = [round(outlet_ll.x, 7), round(outlet_ll.y, 7)]

    rows = []
    for layer, features in result.layers.items():
        for geom, props in features:
            g = project_geometry(geom, crs, "EPSG:4326")
            rows.append({"pid": project_id, "layer": layer, "geom": json.dumps(mapping(g)), "props": json.dumps(props)})

    with get_engine().begin() as conn:  # one transaction: readers never see a half-written result
        conn.execute(text("DELETE FROM terrain_features WHERE project_id = :pid"), {"pid": project_id})
        if rows:
            conn.execute(
                text("INSERT INTO terrain_features (project_id, layer, geom, properties) "
                     "VALUES (:pid, :layer, ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326), CAST(:props AS jsonb))"),
                rows,
            )
        conn.execute(
            text("""INSERT INTO terrain_results (project_id, job_id, summary, dem_path, dem_crs)
                    VALUES (:pid, :jid, CAST(:summary AS jsonb), :dem, :crs)
                    ON CONFLICT (project_id) DO UPDATE
                    SET job_id = EXCLUDED.job_id, summary = EXCLUDED.summary, dem_path = EXCLUDED.dem_path,
                        dem_crs = EXCLUDED.dem_crs, created_at = now()"""),
            {"pid": project_id, "jid": job_id, "summary": json.dumps(summary), "dem": dem_key, "crs": crs},
        )
