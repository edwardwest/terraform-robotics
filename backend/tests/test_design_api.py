"""Stage 2 through the API: keyline pattern, swale, estimate, exports and tiles on synthetic terrain.

Needs PostgreSQL with PostGIS and backend/sql applied (TEST_DATABASE_URL); skipped otherwise.
"""

import io
import json
import math
import os
import time
import zipfile

import pytest

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture(scope="module")
def designed(client, tmp_path_factory):
    from conftest import two_valley_terrain
    from shapely.geometry import box, mapping

    from tr_geo import project_geometry, write_geotiff

    terrain = two_valley_terrain()
    rows, cols = terrain.shape
    x0, y0 = terrain.transform.c, terrain.transform.f
    b = mapping(project_geometry(box(x0 + 15, y0 - rows + 15, x0 + cols - 15, y0 - 15), terrain.crs, "EPSG:4326"))
    boundary = {"type": "Polygon", "coordinates": [[list(p) for p in b["coordinates"][0]]]}
    pid = client.post("/api/projects", json={"name": "Design test", "boundary": boundary}).json()["id"]
    tif = tmp_path_factory.mktemp("dem") / "survey.tif"
    write_geotiff(terrain, str(tif))
    with open(tif, "rb") as f:
        assert client.post(f"/api/projects/{pid}/surveys", data={"kind": "dem"}, files={"file": ("s.tif", f, "image/tiff")}).status_code == 201
    job = client.post(f"/api/projects/{pid}/terrain-jobs", json={"contour_interval_m": 1.0}).json()
    for _ in range(120):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    assert job["status"] == "succeeded", job
    return pid, boundary, terrain


def test_keyline_pattern_and_regenerate(client, designed):
    pid, _, _ = designed
    r = client.post(f"/api/projects/{pid}/design/keylines", json={"keypoint_id": "K1", "spacing_m": 8, "extent": "valley"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["terrain_grade"] == "design"
    assert res["rip_count"] > 3 and res["rip_length_m"] > 100 and res["area_treated_m2"] > 0
    assert res["keyline"]["properties"]["kind"] == "keyline"
    # regenerating for the same keypoint replaces the old pattern instead of adding to it
    r2 = client.post(f"/api/projects/{pid}/design/keylines", json={"keypoint_id": "K1", "spacing_m": 16, "extent": "valley"}).json()
    fc = client.get(f"/api/projects/{pid}/design").json()
    keylines = [f for f in fc["features"] if f["properties"]["kind"] == "keyline"]
    rips = [f for f in fc["features"] if f["properties"]["kind"] == "rip"]
    assert len(keylines) == 1 and len(rips) == r2["rip_count"] < res["rip_count"]
    assert rips[0]["properties"]["label"] == "R1"


def test_graded_pattern(client, designed):
    pid, _, _ = designed
    r = client.post(f"/api/projects/{pid}/design/keylines",
                    json={"keypoint_id": "K2", "spacing_m": 20, "pattern": "graded", "max_lines": 6})
    assert r.status_code == 200, r.text
    assert r.json()["rip_count"] >= 2


def test_swale_and_profile(client, designed):
    pid, _, terrain = designed
    from shapely.geometry import Point

    from tr_geo import project_geometry

    x0, y0 = terrain.transform.c, terrain.transform.f
    a = project_geometry(Point(x0 + 40, y0 - 260), terrain.crs, "EPSG:4326")
    b = project_geometry(Point(x0 + 150, y0 - 260), terrain.crs, "EPSG:4326")
    r = client.post(f"/api/projects/{pid}/design/swales", json={"start": [a.x, a.y], "end": [b.x, b.y], "width_m": 2, "depth_m": 0.5})
    assert r.status_code == 200, r.text
    sw = r.json()["properties"]
    assert sw["label"] == "S1" and sw["cut_volume_m3"] > 50 and sw["storage_gal"] > 10_000
    prof = client.get(f"/api/projects/{pid}/design/elements/{sw['id']}/profile").json()
    z = [v for v in prof["elevation_m"] if v is not None]
    assert max(z) - min(z) < 0.1  # on contour


def test_planning_grade_gate(client):
    # a project with no design-grade terrain is refused unless the draft flag is set (checked in _grade_gate)
    from fastapi import HTTPException

    from tr_api.design_api import _grade_gate

    assert _grade_gate({"quality": {"design_pct": 100}}, False) == "design"
    with pytest.raises(HTTPException):
        _grade_gate({"quality": {"design_pct": 0, "planning_pct": 100}}, False)
    assert _grade_gate({"quality": {"design_pct": 0, "planning_pct": 100}}, True) == "planning"
    with pytest.raises(HTTPException):
        _grade_gate({"quality": {"design_pct": 0, "coarse_pct": 100}}, True)


def test_estimate_and_cost_override(client, designed):
    pid, _, _ = designed
    est = client.get(f"/api/projects/{pid}/estimate").json()
    items = {ln["item"]: ln for ln in est["lines"]}
    assert {"rip_acre", "swale_yd3", "berm_ft", "mobilization"} <= set(items)
    assert est["total_low"] < est["total_high"]
    assert est["total_low"] == pytest.approx(est["build_low"] + est["design_fee_low"] + est["contingency_low"], abs=0.05)
    r = client.put("/api/cost-items/swale_yd3", json={"rate_low": 100, "rate_high": 100})
    assert r.status_code == 200 and r.json()["custom"] is True
    est2 = client.get(f"/api/projects/{pid}/estimate").json()
    sw = next(ln for ln in est2["lines"] if ln["item"] == "swale_yd3")
    assert sw["total_low"] == pytest.approx(sw["quantity"] * 100, rel=1e-6)
    client.delete("/api/cost-items/swale_yd3")
    x = client.get(f"/api/projects/{pid}/estimate.xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_exports(client, designed):
    pid, _, _ = designed
    g = client.get(f"/api/projects/{pid}/export/geojson")
    kinds = {f["properties"]["kind"] for f in json.loads(g.content)["features"]}
    assert {"boundary", "keypoint", "keyline", "rip", "swale"} <= kinds
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/projects/{pid}/export/shapefile").content))
    assert any(n.endswith("design_lines.shp") for n in z.namelist()) and any(n.endswith(".prj") for n in z.namelist())
    assert b"<kml" in client.get(f"/api/projects/{pid}/export/kml").content
    dxf = client.get(f"/api/projects/{pid}/export/dxf").content.decode()
    for layer in ("KEYLINE", "RIP", "SWALE", "BERM", "CONTOUR"):
        assert layer in dxf
    guid = json.loads(client.get(f"/api/projects/{pid}/export/guidance").content)
    passes = [f["properties"]["pass"] for f in guid["features"]]
    assert passes == sorted(passes) and passes[0] == 1
    pdf = client.get(f"/api/projects/{pid}/export/plan.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and len(pdf.content) > 5000
    if os.environ.get("SAVE_EXPORTS"):  # for eyeballing the plan set
        with open(os.path.join(os.environ["SAVE_EXPORTS"], "plan.pdf"), "wb") as f:
            f.write(pdf.content)


def _tile_for(lng, lat, z):
    n = 2**z
    x = int((lng + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def test_tiles(client, designed):
    pid, boundary, _ = designed
    s = client.get(f"/api/projects/{pid}/terrain").json()
    assert s["dem_tiles_url"].endswith("{z}/{x}/{y}.png") and len(s["dem_bounds"]) == 4
    lng = sum(p[0] for p in boundary["coordinates"][0][:-1]) / 4
    lat = sum(p[1] for p in boundary["coordinates"][0][:-1]) / 4
    x, y = _tile_for(lng, lat, 17)
    import numpy as np
    from rasterio.io import MemoryFile

    r = client.get(f"/api/projects/{pid}/tiles/dem/17/{x}/{y}.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    with MemoryFile(r.content) as mem, mem.open() as img:
        rgb = img.read().astype(float)
    elev = rgb[0] * 256 + rgb[1] + rgb[2] / 256 - 32768
    assert 60 < np.median(elev) < 125  # the synthetic terrain spans roughly 70-120 m
    sl = client.get(f"/api/projects/{pid}/tiles/slope/17/{x}/{y}.png")
    assert sl.status_code == 200
    def decoded(path):
        resp = client.get(path)
        assert resp.status_code == 200
        with MemoryFile(resp.content) as mem, mem.open() as img:
            c = img.read().astype(float)
        return c[0] * 256 + c[1] + c[2] / 256 - 32768

    # Tiles with no data must sit at the model's base elevation, never -32768 m (that breaks 3D terrain).
    far = decoded(f"/api/projects/{pid}/tiles/dem/17/0/0.png")
    assert 60 < far.min() and far.max() < 125
    lx, ly = _tile_for(lng, lat, 3)  # the whole model is far smaller than one pixel here
    low = decoded(f"/api/projects/{pid}/tiles/dem/3/{lx}/{ly}.png")
    assert 60 < low.min() and low.max() < 125
