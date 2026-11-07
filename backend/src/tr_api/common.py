"""Helpers shared by the API routers: owner-scoped project lookup and cached terrain loading."""

from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from fastapi import HTTPException
from shapely import wkb

from tr_geo import read_geotiff
from tr_geo.design import Surface

from .db import fetch_all, fetch_one
from .storage import get_storage

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


@lru_cache(maxsize=16)
def load_dem(path: str, version: str | None = None):
    """Cached DEM; `version` (the terrain job id) keeps a re-run from being served stale."""
    return read_geotiff(path)


@lru_cache(maxsize=8)
def load_surface(path: str, version: str | None = None) -> Surface:
    return Surface(load_dem(path, version))


def terrain_or_404(project_id: UUID) -> dict:
    row = fetch_one("SELECT summary, dem_path, dem_crs, job_id FROM terrain_results WHERE project_id = :id", id=str(project_id))
    if not row:
        raise HTTPException(404, "No terrain model yet")
    return row


def srid_of(crs: str) -> int:
    if not crs.upper().startswith("EPSG:"):
        raise HTTPException(500, f"Unsupported terrain CRS {crs}")
    return int(crs.split(":")[1])


def boundary_in(project_id: UUID, srid: int):
    row = fetch_one("SELECT ST_AsBinary(ST_Transform(boundary, :srid)) AS g FROM projects WHERE id = :id",
                    id=str(project_id), srid=srid)
    return wkb.loads(bytes(row["g"])) if row and row["g"] else None


def layer_in(project_id: UUID, layer: str, srid: int, where: str = "", **params) -> list[tuple[object, dict]]:
    """A terrain layer's features in the terrain CRS. `where` is extra SQL using bound `params`."""
    rows = fetch_all(
        f"""SELECT ST_AsBinary(ST_Transform(geom, :srid)) AS g, properties FROM terrain_features
            WHERE project_id = :id AND layer = :layer {where}""",
        id=str(project_id), layer=layer, srid=srid, **params,
    )
    return [(wkb.loads(bytes(r["g"])), r["properties"]) for r in rows]


def terrain_surface(project_id: UUID):
    """(terrain row, Surface, srid) for a project with a terrain model."""
    t = terrain_or_404(project_id)
    version = terrain_version(t)
    path = get_storage().local_path(t["dem_path"], version)
    return t, load_surface(path, version), srid_of(t["dem_crs"])


def terrain_version(t: dict) -> str:
    return str(t.get("job_id") or "")


def dem_local_path(t: dict) -> str:
    return get_storage().local_path(t["dem_path"], terrain_version(t))
