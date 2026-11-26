"""Phase 3 master plan tools: planting layouts, zones and sectors, placement checks, and their API."""

import os

import numpy as np
import pytest
from affine import Affine
from shapely.geometry import LineString, Point, Polygon, box

from tr_geo import Dem
from tr_geo import plan as gp
from tr_geo.design import Surface, contour_line
from tr_kb import plan_checks as pc

X0, Y0 = 500000.0, 4250000.0


def plane(grade=0.1, size=400, res=1.0) -> Surface:
    """Ground rising north at `grade` (rise/run): contours run east-west."""
    rows = cols = size
    y = Y0 + size - (np.arange(rows) + 0.5) * res
    z = np.repeat(((y - Y0) * grade)[:, None], cols, axis=1)
    return Surface(Dem(z, Affine(res, 0, X0, 0, -res, Y0 + size), "EPSG:32610"), smooth_m=0)


def flat(size=200) -> Surface:
    return Surface(Dem(np.full((size, size), 50.0), Affine(1, 0, X0, 0, -1, Y0 + size), "EPSG:32610"), smooth_m=0)


def sq(x, y, w, h=None):
    return box(X0 + x, Y0 + y, X0 + x + w, Y0 + y + (h or w))


# ---- Geometry -------------------------------------------------------------------------------------------


def test_sun_azimuths():
    s = gp.sun_azimuths(38.4)  # Sonoma County
    assert s["summer"]["rise"] == pytest.approx(59.5, abs=0.5) and s["summer"]["set"] == pytest.approx(300.5, abs=0.5)
    assert s["winter"]["rise"] == pytest.approx(120.5, abs=0.5)
    assert s["summer"]["noon_altitude"] == pytest.approx(75.0, abs=0.1)
    assert s["winter"]["noon_altitude"] == pytest.approx(28.2, abs=0.1)
    assert gp.sun_azimuths(0)["summer"]["rise"] == pytest.approx(66.6, abs=0.1)
    assert gp.sun_azimuths(80)["summer"] is None  # midnight sun
    south = gp.sun_azimuths(-33.9)  # Cape Town: the December sun rises south of east
    assert south["summer"]["rise"] > 90 and south["winter"]["rise"] < 90


def test_sectors_and_zones():
    c = Point(X0, Y0)
    w = gp.sector(c, 0, 90, 100)  # north to east
    assert w.contains(Point(X0 + 50, Y0 + 50)) and not w.contains(Point(X0 - 50, Y0 + 50))
    rings = gp.zone_rings(sq(-5, -5, 10), (15, 45, 120, 300))
    assert [z for z, _ in rings] == [1, 2, 3, 4]
    assert all(rings[i][1].area < rings[i + 1][1].area for i in range(3))
    assert not rings[0][1].contains(c)  # zone 0 is the house itself
    secs = gp.site_sectors(c, 38.4, 300, [{"label": "Winter storms", "from_deg": 200}], 45)
    assert [s["kind"] for s in secs] == ["sun", "sun", "wind", "fire"]
    sun = secs[0]["geom"]
    assert sun.contains(Point(X0, Y0 - 200)) and not sun.contains(Point(X0, Y0 + 200))  # the sun's arc is to the south


def test_straight_and_line_planting():
    lay = gp.straight_rows(sq(0, 0, 60), 6, 5)
    assert lay.pattern == "straight" and len(lay.rows) == 10
    assert 100 <= len(lay.points) <= 120
    ys = sorted({round(r.coords[0][1], 3) for r in lay.rows})
    assert np.allclose(np.diff(ys), 6)
    wb = gp.line_planting(LineString([(X0, Y0), (X0 + 100, Y0)]), 5, rows=2)
    assert len(wb.rows) == 2 and len(wb.points) == 42


def test_rows_on_contour_follow_the_contour():
    s = plane(0.1)
    area = sq(100, 100, 120, 80)
    lay = gp.rows_on_contour(s, area, 6, 4)
    assert lay.pattern == "contour" and len(lay.rows) >= 12
    for r in lay.rows:  # on this ground contours run east-west: each row holds its elevation
        z = s.z(np.array([c[0] for c in r.coords]), np.array([c[1] for c in r.coords]))
        assert np.nanmax(z) - np.nanmin(z) < 0.3
    ys = sorted({round(np.mean([c[1] for c in r.coords])) for r in lay.rows})
    assert np.allclose(np.diff(ys), 6, atol=1)
    assert all(area.buffer(0.01).contains(Point(p)) for p in lay.points)
    with pytest.raises(ValueError):
        gp.rows_on_contour(flat(), sq(50, 50, 60), 6, 4)


def test_contour_line_and_grades():
    s = plane(0.1)
    ln = contour_line(s, Point(X0 + 200, Y0 + 200), 50)
    assert ln.length == pytest.approx(100, abs=2)
    assert abs(ln.coords[0][1] - ln.coords[-1][1]) < 0.5
    up = LineString([(X0 + 200, Y0 + 50), (X0 + 200, Y0 + 300)])
    assert gp.max_grade_pct(s, up) == pytest.approx(10, abs=0.5)
    assert gp.bearing_deg(up) == pytest.approx(0) and gp.bearing_deg(LineString([(0, 0), (10, 0)])) == pytest.approx(90)


# ---- Checks ---------------------------------------------------------------------------------------------


def F(i, t, g, cat="x", status="proposed", label=None):
    return pc.CheckFeature(str(i), t, cat, label or t, status, g)


def rules(found):
    return sorted({f.rule for f in found})


def test_well_and_runoff_checks():
    s = plane(0.1)
    lot = sq(0, 0, 400)
    well = F(1, "well-spring", Point(X0 + 200, Y0 + 100), status="existing")
    coop = F(2, "poultry-coop", Point(X0 + 200, Y0 + 125))   # 25 m uphill of the well
    pond = F(3, "pond", sq(150, 200, 40, 20))
    paddock = F(4, "paddock", sq(150, 240, 40, 30))           # just uphill of the pond
    found = pc.run_checks([well, coop, pond, paddock], lot, s)
    r = rules(found)
    assert "well-setback" in r and "runoff" in r
    runoff = [f for f in found if f.rule == "runoff"]
    assert all(f.severity == "warning" for f in runoff) and {tuple(f.feature_ids) for f in runoff} >= {("4", "3")}
    downhill = F(5, "paddock", sq(150, 140, 40, 30))  # below the pond: no runoff warning for it
    assert not [f for f in pc.run_checks([pond, downhill], lot, s) if f.rule == "runoff"]
    # without terrain, closeness alone is a note
    no_terrain = pc.run_checks([pond, paddock], lot, None)
    assert [f.severity for f in no_terrain if f.rule == "runoff"] == ["note"]


def test_terrain_checks():
    steep = plane(0.25)
    lot = sq(0, 0, 400)
    pond = F(1, "pond", sq(100, 100, 30))
    road = F(2, "road", LineString([(X0 + 300, Y0 + 20), (X0 + 300, Y0 + 300)]))
    path = F(3, "path", LineString([(X0 + 320, Y0 + 20), (X0 + 320, Y0 + 300)]))
    found = pc.run_checks([pond, road, path], lot, steep)
    assert set(rules(found)) >= {"pond-slope", "road-grade", "path-grade"}
    across = F(4, "road", LineString([(X0 + 20, Y0 + 200), (X0 + 380, Y0 + 200)]))  # on contour
    assert "road-grade" not in rules(pc.run_checks([across], lot, steep))


def test_fire_zone_and_layout_checks():
    lot = sq(-500, -500, 1000)
    house = F(1, "house", sq(0, 0, 12, 10), status="existing")
    orchard = F(2, "orchard", sq(13, 0, 30))          # 1 m from the house
    forest = F(3, "existing-forest", sq(-40, 0, 32))  # 8 m away
    garden = F(4, "vegetable-garden", sq(100, 0, 20))  # 88 m away
    compost = F(5, "compost", Point(X0 + 300, Y0))
    found = pc.run_checks([house, orchard, forest, garden, compost], lot, None)
    r = rules(found)
    assert {"defensible-zone0", "defensible-zone1", "defensible-space", "garden-far", "compost-far"} <= set(r)
    assert found[0].severity == "warning"  # warnings first
    ds = F(6, "defensible-space", sq(-30, -30, 72))
    assert "defensible-space" not in rules(pc.run_checks([house, ds], lot, None))


def test_outside_setback_and_windbreak():
    lot = sq(0, 0, 100)
    out = F(1, "pond", sq(90, 40, 20))
    near = F(2, "rain-garden", sq(1, 40, 5))
    wb = F(3, "windbreak", LineString([(X0 + 10, Y0 + 80), (X0 + 90, Y0 + 80)]))  # runs east-west
    existing = F(4, "pond", sq(95, 10, 20), status="existing")
    r = rules(pc.run_checks([out, near, wb, existing], lot, None, winds=[{"label": "Summer", "from_deg": 270}]))
    assert "outside-property" in r and "setback" in r and "windbreak-wind" in r
    found = pc.run_checks([out, near, wb, existing], lot, None, winds=[{"label": "North", "from_deg": 0}])
    assert "windbreak-wind" not in rules(found)  # across a north wind: good
    assert all("4" not in f.feature_ids for f in found if f.rule == "outside-property")  # existing isn't flagged


# ---- API ------------------------------------------------------------------------------------------------

db = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")

LOT = {"type": "Polygon", "coordinates": [[[-122.70, 38.40], [-122.699, 38.40], [-122.699, 38.4008],
                                          [-122.70, 38.4008], [-122.70, 38.40]]]}
HOUSE = {"type": "Polygon", "coordinates": [[[-122.6996, 38.4003], [-122.69955, 38.4003], [-122.69955, 38.40035],
                                            [-122.6996, 38.40035], [-122.6996, 38.4003]]]}
ORCHARD = {"type": "Polygon", "coordinates": [[[-122.69955, 38.4003], [-122.6992, 38.4003], [-122.6992, 38.4006],
                                              [-122.69955, 38.4006], [-122.69955, 38.4003]]]}


@db
def test_site_settings_and_overlays(client):
    pid = client.post("/api/projects", json={"name": "Site tools", "boundary": LOT}).json()["id"]
    r = client.get(f"/api/projects/{pid}/plan-site").json()
    assert r["center_source"] == "property" and r["settings"]["show_zones"] is False
    assert r["sun"]["summer"]["rise"] == pytest.approx(59.5, abs=0.5)
    client.post(f"/api/projects/{pid}/plan-features", json={"type": "house", "geometry": HOUSE})
    body = {**r["settings"], "winds": [{"label": "Summer breeze", "from_deg": 300}], "fire_from_deg": 45, "show_zones": True}
    r = client.put(f"/api/projects/{pid}/plan-site", json=body)
    assert r.status_code == 200, r.text
    r = r.json()
    assert r["center_source"] == "house"
    kinds = [f["properties"]["kind"] for f in r["overlays"]["features"]]
    assert kinds.count("zone") == 4 and kinds.count("sun") == 2 and kinds.count("wind") == 1 and kinds.count("fire") == 1
    bad = {**body, "zone_radii_m": [50, 20, 100, 200]}
    assert client.put(f"/api/projects/{pid}/plan-site", json=bad).status_code == 422
    assert client.put(f"/api/projects/{pid}/plan-site", json={**body, "winds": [{"from_deg": 360}]}).status_code == 422


@db
def test_planting_and_checks_without_terrain(client):
    pid = client.post("/api/projects", json={"name": "Planting", "boundary": LOT}).json()["id"]
    client.post(f"/api/projects/{pid}/plan-features", json={"type": "house", "geometry": HOUSE, "label": "House"})
    o = client.post(f"/api/projects/{pid}/plan-features", json={
        "type": "orchard", "geometry": ORCHARD, "props": {"row_spacing_m": 6, "plant_spacing_m": 5, "rows_pattern": "contour"}})
    assert o.status_code == 201, o.text
    fid = o.json()["properties"]["id"]
    p = client.get(f"/api/projects/{pid}/plan-features/planting").json()
    s = p["summary"][fid]
    assert s["pattern"] == "straight" and "terrain model" in s["note"] and s["plants"] > 20
    assert {f["properties"]["kind"] for f in p["features"]} == {"row", "plant"}
    c = client.get(f"/api/projects/{pid}/plan-checks").json()
    assert c["terrain"] is False
    assert "defensible-zone0" in {f["rule"] for f in c["findings"]}  # the orchard touches the house
    assert client.post(f"/api/projects/{pid}/plan-features/contour-line",
                       json={"start": [-122.6997, 38.4002], "end": [-122.6993, 38.4002]}).status_code == 409
    assert client.post(f"/api/projects/{pid}/plan-features", json={
        "type": "pond", "geometry": ORCHARD, "props": {"rows_pattern": "contour"}}).status_code == 422


@db
def test_contour_line_and_rows_with_terrain(client, tmp_path_factory):
    from shapely.geometry import mapping, shape

    from conftest import make_terrain_project

    pid, _, _ = make_terrain_project(client, tmp_path_factory, name="Contour tools")
    b = shape(client.get(f"/api/projects/{pid}").json()["boundary"])
    minx, miny, maxx, maxy = b.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    r = client.post(f"/api/projects/{pid}/plan-features/contour-line",
                    json={"start": [minx + (maxx - minx) * 0.2, cy], "end": [minx + (maxx - minx) * 0.8, cy]})
    assert r.status_code == 200, r.text
    line = r.json()
    assert line["geometry"]["type"] == "LineString" and line["length_m"] > 20
    h = client.post(f"/api/projects/{pid}/plan-features", json={"type": "hedgerow", "geometry": line["geometry"]})
    assert h.status_code == 201
    area = b.buffer(-(maxx - minx) * 0.2)
    o = client.post(f"/api/projects/{pid}/plan-features", json={
        "type": "orchard", "geometry": mapping(area), "props": {"row_spacing_m": 6, "plant_spacing_m": 5, "rows_pattern": "contour"}})
    assert o.status_code == 201, o.text
    p = client.get(f"/api/projects/{pid}/plan-features/planting").json()
    s = p["summary"][o.json()["properties"]["id"]]
    assert s["pattern"] in ("contour", "straight") and s["plants"] > 10
    c = client.get(f"/api/projects/{pid}/plan-checks").json()
    assert c["terrain"] is True
    svg = client.get(f"/api/projects/{pid}/plan-sheet/svg").text
    assert svg.count("#t-orchard") >= min(s["plants"], 900) * 0.5  # sheet trees from the layout
