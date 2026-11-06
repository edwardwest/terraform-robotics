"""Terraform Robotics API. Run with: uvicorn tr_api.main:app --reload"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import PurePosixPath
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from shapely.geometry import LineString

from tr_geo import project_geometry, read_geotiff
from tr_geo.terrain import sample_line

from . import schemas
from .auth import CurrentUser
from .db import execute, fetch_all, fetch_one
from .jobs import dispatch_terrain_job
from .storage import get_storage

app = FastAPI(title="Terraform Robotics API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

LAYERS = ("contours", "flow", "valleys", "ridges", "keypoints")
UPLOAD_EXTENSIONS = {
    "lidar": {".las", ".laz"},
    "dem": {".tif", ".tiff"},
    "contours": {".geojson", ".json"},
}

PROJECT_SELECT = """
SELECT id, name, address, boundary_source, created_at,
       ST_AsGeoJSON(boundary)::json AS boundary,
       ST_Area(boundary::geography) AS area_m2,
       ST_Perimeter(boundary::geography) AS perimeter_m,
       CASE WHEN boundary IS NULL THEN NULL
            ELSE ARRAY[ST_X(ST_Centroid(boundary)), ST_Y(ST_Centroid(boundary))] END AS centroid,
       CASE WHEN boundary IS NULL THEN NULL
            ELSE ARRAY[ST_XMin(boundary), ST_YMin(boundary), ST_XMax(boundary), ST_YMax(boundary)] END AS bbox
FROM projects
"""

SURVEY_COLUMNS = "id, project_id, kind, filename, status, resolution_m, grade, error, created_at"
JOB_COLUMNS = "id, project_id, kind, status, step, step_index, step_count, error, created_at, finished_at"


def _project_or_404(project_id: UUID, user: dict) -> dict:
    """The project if the user owns it. Someone else's project is reported as not found."""
    row = fetch_one(PROJECT_SELECT + " WHERE id = :id AND owner_id = :uid", id=str(project_id), uid=str(user["id"]))
    if not row:
        raise HTTPException(404, "Project not found")
    return row


@app.get("/api/health")
def health():
    fetch_one("SELECT 1 AS ok")
    return {"status": "ok"}


@app.get("/api/me", response_model=schemas.User)
def me(user: CurrentUser):
    return user


# ---- Projects ---------------------------------------------------------------------------------


@app.post("/api/projects", response_model=schemas.Project, status_code=201)
def create_project(body: schemas.ProjectCreate, user: CurrentUser):
    boundary = json.dumps(body.boundary.model_dump()) if body.boundary else None
    row = fetch_one(
        """INSERT INTO projects (owner_id, name, address, boundary, boundary_source)
           VALUES (:uid, :name, :address,
                   CASE WHEN CAST(:boundary AS text) IS NULL THEN NULL
                        ELSE ST_SetSRID(ST_GeomFromGeoJSON(CAST(:boundary AS text)), 4326) END,
                   :source)
           RETURNING id""",
        name=body.name,
        address=body.address,
        boundary=boundary,
        source=body.boundary_source if body.boundary else None,
        uid=str(user["id"]),
    )
    return _project_or_404(row["id"], user)


@app.get("/api/projects", response_model=list[schemas.Project])
def list_projects(user: CurrentUser):
    return fetch_all(PROJECT_SELECT + " WHERE owner_id = :uid ORDER BY created_at DESC", uid=str(user["id"]))


@app.get("/api/projects/{project_id}", response_model=schemas.Project)
def get_project(project_id: UUID, user: CurrentUser):
    return _project_or_404(project_id, user)


@app.put("/api/projects/{project_id}/boundary", response_model=schemas.Project)
def update_boundary(project_id: UUID, body: schemas.BoundaryUpdate, user: CurrentUser):
    _project_or_404(project_id, user)
    execute(
        """UPDATE projects
           SET boundary = ST_SetSRID(ST_GeomFromGeoJSON(:boundary), 4326), boundary_source = :source
           WHERE id = :id""",
        boundary=json.dumps(body.boundary.model_dump()),
        source=body.source,
        id=str(project_id),
    )
    return _project_or_404(project_id, user)


# ---- Surveys ----------------------------------------------------------------------------------


@app.get("/api/projects/{project_id}/surveys", response_model=list[schemas.Survey])
def list_surveys(project_id: UUID, user: CurrentUser):
    _project_or_404(project_id, user)
    return fetch_all(
        f"SELECT {SURVEY_COLUMNS} FROM surveys WHERE project_id = :id ORDER BY created_at", id=str(project_id)
    )


@app.post("/api/projects/{project_id}/surveys", response_model=schemas.Survey, status_code=201)
def upload_survey(project_id: UUID, user: CurrentUser, kind: str = Form(...), file: UploadFile = File(...)):
    _project_or_404(project_id, user)
    if kind not in UPLOAD_EXTENSIONS:
        raise HTTPException(422, f"kind must be one of {sorted(UPLOAD_EXTENSIONS)}")
    filename = PurePosixPath(file.filename or "upload").name
    ext = PurePosixPath(filename).suffix.lower()
    if ext not in UPLOAD_EXTENSIONS[kind]:
        raise HTTPException(422, f"A {kind} upload must be one of {sorted(UPLOAD_EXTENSIONS[kind])}")
    row = fetch_one(
        "INSERT INTO surveys (project_id, kind, filename) VALUES (:pid, :kind, :fn) RETURNING id",
        pid=str(project_id),
        kind=kind,
        fn=filename,
    )
    key = f"projects/{project_id}/surveys/{row['id']}/{filename}"
    get_storage().save_stream(key, file.file)
    execute("UPDATE surveys SET storage_path = :key WHERE id = :id", key=key, id=str(row["id"]))
    return fetch_one(f"SELECT {SURVEY_COLUMNS} FROM surveys WHERE id = :id", id=str(row["id"]))


@app.post("/api/projects/{project_id}/surveys/public-dem", response_model=schemas.Survey, status_code=201)
def add_public_dem(project_id: UUID, user: CurrentUser):
    """Record that the terrain job should fetch USGS 3DEP elevation for this parcel (fetched at job time)."""
    _project_or_404(project_id, user)
    existing = fetch_one(
        f"SELECT {SURVEY_COLUMNS} FROM surveys WHERE project_id = :id AND kind = 'public_dem'", id=str(project_id)
    )
    if existing:
        return existing
    return fetch_one(
        f"""INSERT INTO surveys (project_id, kind, filename) VALUES (:id, 'public_dem', 'USGS 3DEP')
            RETURNING {SURVEY_COLUMNS}""",
        id=str(project_id),
    )


# ---- Terrain jobs and results -----------------------------------------------------------------


@app.post("/api/projects/{project_id}/terrain-jobs", response_model=schemas.Job, status_code=202)
def start_terrain_job(project_id: UUID, user: CurrentUser, body: schemas.TerrainJobCreate | None = None):
    project = _project_or_404(project_id, user)
    if not project["boundary"]:
        raise HTTPException(409, "Set the parcel boundary before building the terrain model")
    running = fetch_one(
        f"SELECT {JOB_COLUMNS} FROM jobs WHERE project_id = :id AND status IN ('queued', 'running')",
        id=str(project_id),
    )
    if running:
        return running
    params = (body or schemas.TerrainJobCreate()).model_dump()
    job = fetch_one(
        f"""INSERT INTO jobs (project_id, kind, params, step, step_count)
            VALUES (:id, 'terrain', CAST(:params AS jsonb), 'Queued', 4)
            RETURNING {JOB_COLUMNS}""",
        id=str(project_id),
        params=json.dumps(params),
    )
    dispatch_terrain_job(str(job["id"]))
    return job


@app.get("/api/jobs/{job_id}", response_model=schemas.Job)
def get_job(job_id: UUID, user: CurrentUser):
    job = fetch_one(
        f"""SELECT {', '.join('j.' + c.strip() for c in JOB_COLUMNS.split(','))}
            FROM jobs j JOIN projects p ON p.id = j.project_id
            WHERE j.id = :id AND p.owner_id = :uid""",
        id=str(job_id),
        uid=str(user["id"]),
    )
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/projects/{project_id}/terrain", response_model=schemas.TerrainSummary)
def get_terrain(project_id: UUID, user: CurrentUser):
    _project_or_404(project_id, user)
    row = fetch_one("SELECT summary, dem_path FROM terrain_results WHERE project_id = :id", id=str(project_id))
    if not row:
        raise HTTPException(404, "No terrain model yet")
    s = row["summary"]
    return {
        **{k: s[k] for k in ("dem_resolution_m", "elevation_min_m", "elevation_max_m", "mean_slope_pct",
                             "outlet_direction", "main_valley_count", "keypoint_count", "quality")},
        "outlet": {"type": "Point", "coordinates": s["outlet_lnglat"]},
        "layers": list(LAYERS),
        "dem_url": f"/files/{row['dem_path']}",
    }


@app.get("/api/projects/{project_id}/layers/{layer}")
def get_layer(project_id: UUID, layer: str, user: CurrentUser):
    if layer not in LAYERS:
        raise HTTPException(404, f"Unknown layer; choose one of {LAYERS}")
    _project_or_404(project_id, user)
    row = fetch_one(
        """SELECT json_build_object(
               'type', 'FeatureCollection',
               'features', COALESCE(json_agg(json_build_object(
                   'type', 'Feature',
                   'geometry', ST_AsGeoJSON(geom, 7)::json,
                   'properties', properties)), '[]'::json)) AS fc
           FROM terrain_features WHERE project_id = :id AND layer = :layer""",
        id=str(project_id),
        layer=layer,
    )
    return row["fc"]


@app.patch("/api/projects/{project_id}/keypoints/{kp_id}")
def update_keypoint(project_id: UUID, kp_id: str, body: schemas.KeypointUpdate, user: CurrentUser):
    _project_or_404(project_id, user)
    row = fetch_one(
        """UPDATE terrain_features
           SET properties = jsonb_set(properties, '{confirmed}', to_jsonb(CAST(:confirmed AS boolean)))
           WHERE project_id = :pid AND layer = 'keypoints' AND properties->>'id' = :kp
           RETURNING json_build_object('type', 'Feature', 'geometry', ST_AsGeoJSON(geom, 7)::json,
                                       'properties', properties) AS feature""",
        pid=str(project_id),
        kp=kp_id,
        confirmed=body.confirmed,
    )
    if not row:
        raise HTTPException(404, "Keypoint not found")
    return row["feature"]


@lru_cache(maxsize=16)
def _load_dem(path: str):
    return read_geotiff(path)


@app.get("/api/projects/{project_id}/profile", response_model=schemas.Profile)
def get_profile(project_id: UUID, user: CurrentUser, coords: str = Query(..., description="lng,lat;lng,lat"), samples: int = Query(200, ge=2, le=2000)):
    _project_or_404(project_id, user)
    row = fetch_one("SELECT dem_path FROM terrain_results WHERE project_id = :id", id=str(project_id))
    if not row:
        raise HTTPException(404, "No terrain model yet")
    try:
        pts = [tuple(float(v) for v in pair.split(",")) for pair in coords.split(";")]
        line = LineString(pts)
    except Exception:
        raise HTTPException(422, "coords must look like lng,lat;lng,lat")
    dem = _load_dem(get_storage().local_path(row["dem_path"]))
    d, z = sample_line(dem, project_geometry(line, "EPSG:4326", dem.crs), samples)
    return {"distance_m": [round(float(v), 2) for v in d],
            "elevation_m": [None if v != v else round(float(v), 2) for v in z]}


@app.get("/files/{key:path}")
def get_file(key: str, user: CurrentUser):
    storage = get_storage()
    parts = key.split("/")
    if len(parts) < 3 or parts[0] != "projects" or ".." in parts:
        raise HTTPException(404, "File not found")
    try:
        _project_or_404(UUID(parts[1]), user)
    except ValueError:
        raise HTTPException(404, "File not found")
    if not storage.exists(key):
        raise HTTPException(404, "File not found")
    return FileResponse(storage.local_path(key))


@app.get("/api/projects/{project_id}/geojson")
def project_geojson(project_id: UUID, user: CurrentUser):
    """The boundary as a Feature, for quick inspection in GIS tools."""
    p = _project_or_404(project_id, user)
    return {"type": "Feature", "geometry": p["boundary"], "properties": {"name": p["name"]}}

