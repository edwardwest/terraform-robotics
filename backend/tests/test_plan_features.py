"""Master plan feature library (pure) and the plan-features API, including the plan, estimate and exports."""

import io
import json
import os
import zipfile

import pytest

from tr_kb import interventions as iv
from tr_kb import plan_features as pf

# ---- Library (pure) -----------------------------------------------------------------------------------


def test_library_loads_and_links_interventions():
    lib = pf.library()
    assert len(lib["categories"]) == 9
    assert len({c["color"] for c in lib["categories"]}) == 9  # every category is distinguishable on the map
    types = pf.types_by_id()
    assert types["orchard"]["intervention"] == "food-forest" and "species" in types["orchard"]["fields"]
    assert types["house"]["status"] == "existing" and types["house"]["defaults"]["roof"] == "gable"
    # every linked intervention exists and isn't one the design tools lay out
    catalog = iv.by_id()
    for t in lib["types"]:
        if t["intervention"]:
            assert not catalog[t["intervention"]]["tool"]


def test_every_drawable_intervention_has_a_type():
    """Each catalog intervention without a design tool can be placed on the master plan."""
    missing = [i["id"] for i in iv.catalog()["interventions"] if not i["tool"] and not pf.type_for_intervention(i["id"])]
    assert missing == []


def test_plant_counts():
    t = pf.types_by_id()
    assert pf.plant_count(t["orchard"], {"row_spacing_m": 5, "plant_spacing_m": 4}, 1000, None) == 50
    assert pf.plant_count(t["windbreak"], {"plant_spacing_m": 3, "rows": 2}, None, 30) == 22  # 11 per row
    assert pf.plant_count(t["shade-tree"], {}, None, None) == 1
    assert pf.plant_count(t["orchard"], {}, 1000, None) is None  # no spacing yet
    assert pf.plant_count(t["pond"], {"plant_spacing_m": 3}, 1000, None) is None  # not a planted type


def test_measured_quantity_by_basis():
    feats = [
        {"type": "orchard", "area_m2": 800.0, "length_m": None, "props": {}, "status": "proposed"},
        {"type": "food-forest", "area_m2": 200.0, "length_m": None, "props": {}, "status": "proposed"},
        {"type": "orchard", "area_m2": 5000.0, "length_m": None, "props": {}, "status": "existing"},  # not new work
        {"type": "windbreak", "area_m2": None, "length_m": 120.0, "props": {}, "status": "proposed"},
        {"type": "poultry-coop", "area_m2": None, "length_m": None, "props": {}, "status": "proposed"},
        {"type": "poultry-coop", "area_m2": None, "length_m": None, "props": {}, "status": "proposed"},
        {"type": "cistern", "area_m2": None, "length_m": None, "props": {}, "status": "proposed"},
    ]
    assert pf.measured_quantity("food-forest", feats) == 1000.0
    assert pf.measured_quantity("windbreak", feats) == 120.0
    assert pf.measured_quantity("poultry", feats) == 2.0
    assert pf.measured_quantity("roof-catchment", feats) is None  # volume needs a capacity
    feats[-1]["props"] = {"capacity_m3": 18.9}
    assert pf.measured_quantity("roof-catchment", feats) == 18.9
    assert pf.measured_quantity("pond", feats) is None


# ---- API ------------------------------------------------------------------------------------------------

db = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")

LOT = {"type": "Polygon", "coordinates": [[[-122.70, 38.40], [-122.699, 38.40], [-122.699, 38.4008],
                                          [-122.70, 38.4008], [-122.70, 38.40]]]}  # about 4.4 acres
ORCHARD = {"type": "Polygon", "coordinates": [[[-122.6998, 38.4001], [-122.6994, 38.4001], [-122.6994, 38.4004],
                                              [-122.6998, 38.4004], [-122.6998, 38.4001]]]}
HEDGE = {"type": "LineString", "coordinates": [[-122.6999, 38.4006], [-122.6992, 38.4006]]}
COOP = {"type": "Point", "coordinates": [-122.6995, 38.4005]}


@pytest.fixture
def pid(client):
    return client.post("/api/projects", json={"name": "Master plan test", "boundary": LOT}).json()["id"]


@pytest.fixture
def apple(client):
    from tr_api.db import execute

    execute("""INSERT INTO species (symbol, scientific_name, common_name, traits, source, license)
               VALUES ('MADO2', 'Malus domestica', 'apple', '{"growth_form": "Tree"}', 'test', 'public domain')
               ON CONFLICT (symbol) DO NOTHING""")
    return "MADO2"


@db
def test_library_endpoint(client):
    r = client.get("/api/plan-features/library")
    assert r.status_code == 200
    lib = r.json()
    orchard = next(t for t in lib["types"] if t["id"] == "orchard")
    assert orchard["intervention_title"] and orchard["geometry"] == "polygon"
    assert all(c["color"].startswith("#") for c in lib["categories"])


@db
def test_create_measure_and_feed_the_plan(client, pid, apple):
    r = client.post(f"/api/projects/{pid}/plan-features", json={
        "type": "orchard", "geometry": ORCHARD, "build_phase": 2,
        "props": {"species": [{"symbol": apple, "scientific_name": "made up"}], "row_spacing_m": 6, "plant_spacing_m": 4.5}})
    assert r.status_code == 201, r.text
    f = r.json()["properties"]
    assert f["label"] == "Orchard" and f["status"] == "proposed" and f["build_phase"] == 2 and f["category"] == "trees"
    assert 1000 < f["area_m2"] < 1200  # ~35 m × 33 m
    assert f["plant_count"] == int(f["area_m2"] / 27)
    assert f["props"]["species"] == [{"symbol": "MADO2", "scientific_name": "Malus domestica", "common_name": "apple"}]
    assert f["props"]["height_m"] == 5  # type default kept

    plan = {p["intervention_id"]: p for p in client.get(f"/api/projects/{pid}/plan").json()}
    assert plan["food-forest"]["placed"] == 1 and plan["food-forest"]["measured_quantity"] == pytest.approx(f["area_m2"], abs=0.1)

    est = client.get(f"/api/projects/{pid}/estimate").json()
    line = next(ln for ln in est["lines"] if ln["item"] == "food_forest_acre")
    assert line["basis"] == "Measured from 1 feature on your master plan"
    assert line["quantity"] == pytest.approx(f["area_m2"] / 4046.86, abs=0.01)


@db
def test_lines_points_and_existing_features(client, pid):
    r = client.post(f"/api/projects/{pid}/plan-features", json={"type": "hedgerow", "geometry": HEDGE, "label": "North hedge"})
    assert r.status_code == 201
    h = r.json()["properties"]
    assert 55 < h["length_m"] < 65 and h["plant_count"] == (int(h["length_m"] // 1.5) + 1)
    assert client.post(f"/api/projects/{pid}/plan-features", json={"type": "poultry-coop", "geometry": COOP}).status_code == 201
    house = client.post(f"/api/projects/{pid}/plan-features", json={"type": "house", "geometry": ORCHARD}).json()["properties"]
    assert house["status"] == "existing" and house["props"] == {"height_m": 7, "roof": "gable"}
    plan = {p["intervention_id"]: p for p in client.get(f"/api/projects/{pid}/plan").json()}
    assert plan["hedgerow"]["measured_quantity"] == pytest.approx(h["length_m"], abs=0.1)
    assert plan["poultry"]["measured_quantity"] == 1
    fc = client.get(f"/api/projects/{pid}/plan-features").json()
    assert [f["properties"]["type"] for f in fc["features"]] == ["hedgerow", "poultry-coop", "house"]


@db
def test_validation(client, pid):
    post = lambda body: client.post(f"/api/projects/{pid}/plan-features", json=body)  # noqa: E731
    assert post({"type": "nope", "geometry": COOP}).status_code == 422
    r = post({"type": "orchard", "geometry": COOP})
    assert r.status_code == 422 and "polygon" in r.json()["detail"]
    bowtie = {"type": "Polygon", "coordinates": [[[-122.6998, 38.4001], [-122.6994, 38.4004], [-122.6994, 38.4001],
                                                  [-122.6998, 38.4004], [-122.6998, 38.4001]]]}
    assert "crosses" in post({"type": "pond", "geometry": bowtie}).json()["detail"]
    far = {"type": "Point", "coordinates": [-122.60, 38.40]}  # ~8.7 km east
    assert "outside the property" in post({"type": "apiary", "geometry": far}).json()["detail"]
    r = post({"type": "pond", "geometry": ORCHARD, "props": {"roof": "flat"}})
    assert r.status_code == 422 and "roof" in r.json()["detail"]
    r = post({"type": "orchard", "geometry": ORCHARD, "props": {"species": [{"symbol": "ZZZZ9"}]}})
    assert r.status_code == 422 and "ZZZZ9" in r.json()["detail"]
    assert post({"type": "orchard", "geometry": ORCHARD, "props": {"colour": "red"}}).status_code == 422
    assert post({"type": "orchard", "geometry": ORCHARD, "build_phase": 4}).status_code == 422


@db
def test_update_retype_and_delete(client, pid):
    f = client.post(f"/api/projects/{pid}/plan-features", json={"type": "orchard", "geometry": ORCHARD}).json()["properties"]
    url = f"/api/projects/{pid}/plan-features/{f['id']}"
    r = client.patch(url, json={"label": "East orchard", "status": "existing", "build_phase": 3,
                                "props": {"row_spacing_m": 5, "plant_spacing_m": 5, "notes": "heritage apples"}})
    assert r.status_code == 200, r.text
    p = r.json()["properties"]
    assert (p["label"], p["status"], p["build_phase"]) == ("East orchard", "existing", 3)
    assert p["props"] == {"row_spacing_m": 5, "plant_spacing_m": 5, "notes": "heritage apples"}
    # retype within polygons: settings the new type doesn't take are dropped, its defaults filled in
    p = client.patch(url, json={"type": "pond"}).json()["properties"]
    assert p["type"] == "pond" and p["category"] == "water" and p["props"] == {"notes": "heritage apples"}
    assert client.patch(url, json={"type": "apiary"}).status_code == 422  # a point type
    moved = {"type": "Polygon", "coordinates": [[[-122.6999, 38.4001], [-122.6995, 38.4001], [-122.6995, 38.4003],
                                                 [-122.6999, 38.4003], [-122.6999, 38.4001]]]}
    p2 = client.patch(url, json={"geometry": moved}).json()["properties"]
    assert p2["area_m2"] < p["area_m2"]
    assert client.delete(url).status_code == 204
    assert client.patch(url, json={"label": "x"}).status_code == 404
    assert client.get(f"/api/projects/{pid}/plan-features").json()["features"] == []
    # the plan keeps the intervention after its feature is removed
    assert "pond" in {p["intervention_id"] for p in client.get(f"/api/projects/{pid}/plan").json()}


@db
def test_other_users_cannot_see_features(client, pid, signing_key):
    f = client.post(f"/api/projects/{pid}/plan-features", json={"type": "apiary", "geometry": COOP}).json()["properties"]
    bob = {"Authorization": f"Bearer {signing_key['token']('user_bob', email='bob@example.com')}"}
    assert client.get(f"/api/projects/{pid}/plan-features", headers=bob).status_code == 404
    assert client.delete(f"/api/projects/{pid}/plan-features/{f['id']}", headers=bob).status_code == 404


@db
def test_exports_include_plan_features(client, pid):
    client.post(f"/api/projects/{pid}/plan-features", json={"type": "orchard", "geometry": ORCHARD, "label": "Apples"})
    client.post(f"/api/projects/{pid}/plan-features", json={"type": "fence", "geometry": HEDGE})
    client.post(f"/api/projects/{pid}/plan-features", json={"type": "apiary", "geometry": COOP})
    gj = json.loads(client.get(f"/api/projects/{pid}/export/geojson").content)
    plan = [f for f in gj["features"] if f["properties"]["kind"] == "plan_feature"]
    assert {f["properties"]["type"] for f in plan} == {"orchard", "fence", "apiary"}
    kml = client.get(f"/api/projects/{pid}/export/kml").text
    assert "<Folder><name>Trees and perennials</name>" in kml and "#plan-animals" in kml and "Apples" in kml
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/projects/{pid}/export/shapefile").content))
    names = set(z.namelist())
    assert {n.split("/")[-1] for n in names} >= {"plan_points.shp", "plan_lines.shp", "plan_areas.shp", "plan_areas.prj"}


@db
def test_dxf_has_a_layer_per_category(client, tmp_path_factory):
    import ezdxf
    from shapely.geometry import mapping, shape

    from conftest import make_terrain_project

    pid, _, _ = make_terrain_project(client, tmp_path_factory, name="DXF plan test")
    project = client.get(f"/api/projects/{pid}").json()
    c = shape(project["boundary"]).centroid
    pond = mapping(c.buffer(0.0002))
    client.post(f"/api/projects/{pid}/plan-features", json={"type": "pond", "geometry": pond, "label": "Duck pond"})
    client.post(f"/api/projects/{pid}/plan-features", json={"type": "apiary", "geometry": mapping(c)})
    r = client.get(f"/api/projects/{pid}/export/dxf")
    assert r.status_code == 200
    doc = ezdxf.read(io.StringIO(r.text))
    assert {"PLAN_WATER", "PLAN_ANIMALS"} <= {layer.dxf.name for layer in doc.layers}
    assert "PLAN_FIRE" not in {layer.dxf.name for layer in doc.layers}  # only categories in use
    texts = [e.dxf.text for e in doc.modelspace().query("TEXT")]
    assert "Duck pond" in texts
