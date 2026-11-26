"""Master plan sheet: layout helpers (pure), and the settings, SVG and PDF endpoints."""

import os

import pytest
from shapely.geometry import LineString, Point, Polygon

from tr_api import basemap
from tr_api.master_sheet import (
    SheetFeature, SheetInput, _spread, frame_for, label_groups, nice_scale, render, schedule_rows, tree_points,
    style_for,
)
from tr_kb import plan_features as pf

X0, Y0 = 500000.0, 4250000.0


def feat(i, t, g, label=None, status="proposed", props=None, n=None, phase=1):
    ty = pf.types_by_id()[t]
    return SheetFeature(str(i), t, ty["label"], ty["category"], label, status, phase, g, props or {}, n)


def sq(x, y, w, h=None):
    h = h or w
    return Polygon([(X0 + x, Y0 + y), (X0 + x + w, Y0 + y), (X0 + x + w, Y0 + y + h), (X0 + x, Y0 + y + h)])


# ---- Pure ----------------------------------------------------------------------------------------------


def test_nice_scale_picks_the_next_standard_scale():
    # 300 m across 9 in needs ~109 ft/in -> 120
    assert nice_scale(300, 100, 9 * 72, 7 * 72) == 120
    assert nice_scale(30, 30, 9 * 72, 7 * 72) == 15  # 30 m over 7 in is ~14 ft/in
    assert nice_scale(100000, 10, 72, 72) % 1000 == 0


def test_spread_keeps_labels_apart_and_on_the_sheet():
    ys = _spread([100, 101, 102, 500], [10, 10, 10, 10], 0, 200)
    assert ys == [100, 110, 120, 200]
    ys = _spread([195, 196, 197], [10, 10, 10], 0, 200)
    assert ys == [180, 190, 200]


def test_label_groups_merge_same_text_and_respect_hidden():
    fs = [feat(1, "cistern", Point(X0, Y0), "Cisterns"), feat(2, "cistern", Point(X0 + 5, Y0), "cisterns"),
          feat(3, "pond", sq(0, 0, 20)), feat(4, "apiary", Point(X0, Y0 + 9))]
    g = label_groups(fs, hidden={"APIARY"})
    assert set(g) == {"CISTERNS", "POND"} and len(g["CISTERNS"]) == 2


def test_tree_points_follow_spacing_and_are_capped():
    orchard = feat(1, "orchard", sq(0, 0, 60), props={"plant_spacing_m": 5, "row_spacing_m": 6})
    pts, r = tree_points(orchard, style_for(orchard, "#000"), 10000)
    assert 80 <= len(pts) <= 120  # ~60/5 × 60/6 = 120, less the inset edge
    huge = feat(2, "orchard", sq(0, 0, 3000), props={"plant_spacing_m": 3, "row_spacing_m": 3})
    pts, _ = tree_points(huge, style_for(huge, "#000"), 10000)
    assert len(pts) <= 900
    wb = feat(3, "windbreak", LineString([(X0, Y0), (X0 + 100, Y0)]), props={"plant_spacing_m": 5, "rows": 2})
    pts, _ = tree_points(wb, style_for(wb, "#000"), 10000)
    assert len(pts) == 42  # 21 per row


def test_schedule_rows():
    fs = [feat(1, "orchard", sq(0, 0, 50), "Apples", props={"species": [{"symbol": "MADO2", "common_name": "apple", "scientific_name": "Malus domestica"}],
                                                       "plant_spacing_m": 4.572, "row_spacing_m": 6.096}, n=80),
          feat(2, "pond", sq(0, 0, 10))]
    rows = schedule_rows(fs)
    assert rows == [{"label": "Apples", "species": "Apple", "spacing": "15 ft × 20 ft", "count": 80}]


def test_render_is_a_complete_sheet():
    fs = [feat(1, "orchard", sq(0, 0, 80), "Apple orchard", props={"plant_spacing_m": 5, "row_spacing_m": 6}, n=200),
          feat(2, "pond", sq(100, 0, 30)), feat(3, "house", sq(0, 100, 15), status="existing"),
          feat(4, "road", LineString([(X0 - 10, Y0 - 10), (X0 + 150, Y0 + 130)])), feat(5, "cistern", Point(X0 + 20, Y0 + 120))]
    settings = {"size": "11x17", "labels": "callouts", "title": "Master plan & more", "notes": "Water first.", "contours": True,
                "label_positions": {"POND": [0.5, 0.5]}}
    inp = SheetInput("Test <farm>", "1 Road", sq(-20, -20, 200), fs, pf.library()["categories"], settings)
    svg = render(inp)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert 'width="1224pt"' in svg
    assert "Test &lt;farm&gt;" in svg and "Master plan &amp; more" in svg  # escaped
    assert svg.count('class="lbl"') == 5
    assert 'data-key="POND" data-x="612.0" data-y="396.0"' in svg  # dragged label at its saved spot
    assert "#t-orchard" in svg and "PLANT SCHEDULE" in svg and "Water first." in svg
    assert "Existing features are drawn lighter." in svg and "1 in = " in svg
    import cairosvg
    assert cairosvg.svg2pdf(bytestring=svg.encode()).startswith(b"%PDF")
    big = render(SheetInput("x", None, None, fs, pf.library()["categories"], {**settings, "size": "24x36", "labels": "off"}))
    assert 'width="2592pt"' in big and 'class="lbl"' not in big


def test_frame_fits_everything():
    fs = [feat(1, "pond", sq(0, 0, 400, 100))]
    f = frame_for({"size": "11x17"}, fs, None)
    x0, y0, x1, y1 = f.bounds_m()
    assert x0 < X0 and x1 > X0 + 400 and y0 < Y0 and y1 > Y0 + 100


# ---- API -------------------------------------------------------------------------------------------

db = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")

LOT = {"type": "Polygon", "coordinates": [[[-122.70, 38.40], [-122.699, 38.40], [-122.699, 38.4008],
                                          [-122.70, 38.4008], [-122.70, 38.40]]]}
ORCHARD = {"type": "Polygon", "coordinates": [[[-122.6998, 38.4001], [-122.6994, 38.4001], [-122.6994, 38.4004],
                                              [-122.6998, 38.4004], [-122.6998, 38.4001]]]}
COOP = {"type": "Point", "coordinates": [-122.6995, 38.4005]}


@pytest.fixture
def no_network(monkeypatch):
    monkeypatch.setattr(basemap, "aerial", lambda *a, **k: None)


def test_aerial_mosaic_is_faded_and_fills_the_frame(monkeypatch):
    import numpy as np

    calls = []

    def tile(client, z, x, y):
        calls.append((z, x, y))
        return np.full((256, 256, 3), (30, 90, 40), dtype=np.uint8)

    monkeypatch.setattr(basemap, "_fetch_tile", tile)
    basemap._aerial_cached.cache_clear()
    bounds = (X0, Y0, X0 + 400, Y0 + 300)
    rgb = basemap.aerial("EPSG:32610", bounds, 400, 300)
    assert rgb is not None and rgb.shape == (300, 400, 3)
    assert 1 <= len(calls) <= basemap.MAX_TILES
    assert {c[0] for c in calls} == {17}  # ~1 m/px wanted: z17 (~0.94 m/px at this latitude) is the coarsest sharp enough
    mid = rgb[150, 200].astype(int)
    assert (mid > np.array([30, 90, 40])).all() and mid.max() - mid.min() < 50  # lighter and greyer than the photo
    basemap._aerial_cached.cache_clear()
    monkeypatch.setattr(basemap, "_fetch_tile", lambda *a: None)
    assert basemap.aerial("EPSG:32610", bounds, 400, 300) is None


@pytest.fixture
def pid(client, no_network):
    pid = client.post("/api/projects", json={"name": "Sheet test", "address": "1 Orchard Ln", "boundary": LOT}).json()["id"]
    client.post(f"/api/projects/{pid}/plan-features", json={"type": "orchard", "geometry": ORCHARD, "label": "Apples", "build_phase": 2})
    client.post(f"/api/projects/{pid}/plan-features", json={"type": "poultry-coop", "geometry": COOP, "label": "Coop"})
    return pid


@db
def test_settings_defaults_and_validation(client, pid):
    s = client.get(f"/api/projects/{pid}/plan-sheet").json()
    assert s["size"] == "11x17" and s["labels"] == "callouts" and s["base"] == "aerial" and s["label_positions"] == {}
    r = client.put(f"/api/projects/{pid}/plan-sheet", json={**s, "size": "24x36", "label_positions": {"COOP": [0.2, 0.3]}})
    assert r.status_code == 200 and r.json()["size"] == "24x36" and r.json()["label_positions"] == {"COOP": [0.2, 0.3]}
    assert client.get(f"/api/projects/{pid}/plan-sheet").json()["size"] == "24x36"
    assert client.put(f"/api/projects/{pid}/plan-sheet", json={**s, "hidden_categories": ["nope"]}).status_code == 422
    assert client.put(f"/api/projects/{pid}/plan-sheet", json={**s, "label_positions": {"X": [1.5, 0]}}).status_code == 422
    assert client.put(f"/api/projects/{pid}/plan-sheet", json={**s, "extra": 1}).status_code == 422


@db
def test_svg_follows_settings(client, pid):
    svg = client.get(f"/api/projects/{pid}/plan-sheet/svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert 'data-key="APPLES"' in svg.text and 'data-key="COOP"' in svg.text and "1 Orchard Ln" in svg.text
    s = client.get(f"/api/projects/{pid}/plan-sheet").json()
    client.put(f"/api/projects/{pid}/plan-sheet", json={**s, "phases": 1, "hidden_labels": ["COOP"]})
    text = client.get(f"/api/projects/{pid}/plan-sheet/svg").text
    assert 'data-key="APPLES"' not in text  # phase 2 hidden by the phase filter
    assert 'data-key="COOP"' not in text  # label hidden, feature still drawn
    client.put(f"/api/projects/{pid}/plan-sheet", json={**s, "hidden_categories": ["animals"]})
    assert 'data-key="COOP"' not in client.get(f"/api/projects/{pid}/plan-sheet/svg").text


@db
def test_pdf_and_scoping(client, pid, signing_key):
    r = client.get(f"/api/projects/{pid}/export/master-plan.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert "master-plan.pdf" in r.headers["content-disposition"]
    bob = {"Authorization": f"Bearer {signing_key['token']('user_bob', email='bob@example.com')}"}
    assert client.get(f"/api/projects/{pid}/plan-sheet/svg", headers=bob).status_code == 404
    assert client.get(f"/api/projects/{pid}/export/master-plan.pdf", headers=bob).status_code == 404


@db
def test_terrain_shading_when_no_aerial(client, tmp_path_factory, no_network):
    from shapely.geometry import mapping, shape

    from conftest import make_terrain_project

    pid, _, _ = make_terrain_project(client, tmp_path_factory, name="Sheet terrain test")
    c = shape(client.get(f"/api/projects/{pid}").json()["boundary"]).centroid
    client.post(f"/api/projects/{pid}/plan-features", json={"type": "pond", "geometry": mapping(c.buffer(0.0002))})
    r = client.get(f"/api/projects/{pid}/plan-sheet/svg")
    assert r.headers["x-sheet-base"] == "terrain"  # aerial asked for, unreachable: terrain shading instead
    svg = r.text
    assert "<image " in svg and "data:image/jpeg;base64," in svg  # hillshade under the plan
    assert 'stroke="#6f7a62"' in svg  # contours
    s = client.get(f"/api/projects/{pid}/plan-sheet").json()
    client.put(f"/api/projects/{pid}/plan-sheet", json={**s, "base": "plain", "contours": False})
    r = client.get(f"/api/projects/{pid}/plan-sheet/svg")
    assert r.headers["x-sheet-base"] == "plain"
    assert "<image " not in r.text and 'stroke="#6f7a62"' not in r.text
