"""End-to-end API test: project → DEM upload → terrain job → summary, layers, keypoints, profile.

Needs PostgreSQL with PostGIS and the schema in backend/sql. Set TEST_DATABASE_URL, e.g.
postgresql+psycopg://terraform:terraform@localhost/terraform. Skipped when unset.
"""

import os
import time

import pytest

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


def _boundary_lnglat(terrain, inset=15):
    from shapely.geometry import box, mapping

    from tr_geo import project_geometry

    rows, cols = terrain.shape
    x0, y0 = terrain.transform.c, terrain.transform.f
    utm_box = box(x0 + inset, y0 - rows + inset, x0 + cols - inset, y0 - inset)
    return mapping(project_geometry(utm_box, terrain.crs, "EPSG:4326"))


def test_full_terrain_flow(client, terrain, tmp_path):
    from tr_geo import write_geotiff

    boundary = _boundary_lnglat(terrain)
    boundary = {"type": "Polygon", "coordinates": [[list(pt) for pt in boundary["coordinates"][0]]]}
    r = client.post("/api/projects", json={"name": "Synthetic valleys", "boundary": boundary})
    assert r.status_code == 201, r.text
    project = r.json()
    assert 80_000 < project["area_m2"] < 100_000  # 290 m × 330 m
    pid = project["id"]

    tif = tmp_path / "survey.tif"
    write_geotiff(terrain, str(tif))
    with open(tif, "rb") as f:
        r = client.post(f"/api/projects/{pid}/surveys", data={"kind": "dem"}, files={"file": ("survey.tif", f, "image/tiff")})
    assert r.status_code == 201, r.text

    r = client.post(f"/api/projects/{pid}/terrain-jobs", json={"contour_interval_m": 2.0})
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]
    for _ in range(120):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    assert job["status"] == "succeeded", job

    surveys = client.get(f"/api/projects/{pid}/surveys").json()
    assert surveys[0]["status"] == "ready" and surveys[0]["grade"] == "design"

    summary = client.get(f"/api/projects/{pid}/terrain").json()
    assert summary["main_valley_count"] == 2
    assert summary["quality"]["design_pct"] > 99
    assert summary["outlet_direction"] in {"S", "SE", "SW"}

    kps = client.get(f"/api/projects/{pid}/layers/keypoints").json()["features"]
    assert len(kps) == 2
    contours = client.get(f"/api/projects/{pid}/layers/contours").json()["features"]
    assert contours and all(f["geometry"]["type"] == "LineString" for f in contours)

    r = client.patch(f"/api/projects/{pid}/keypoints/K1", json={"confirmed": True})
    assert r.status_code == 200 and r.json()["properties"]["confirmed"] is True

    (lng0, lat0), (lng1, lat1) = boundary["coordinates"][0][0], boundary["coordinates"][0][2]
    prof = client.get(f"/api/projects/{pid}/profile", params={"coords": f"{lng0},{lat0};{lng1},{lat1}", "samples": 50}).json()
    assert len(prof["distance_m"]) == 50 and prof["elevation_m"][0] is not None

    r = client.get(summary["dem_url"])
    assert r.status_code == 200 and len(r.content) > 1000
