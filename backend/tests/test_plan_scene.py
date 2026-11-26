"""Phase 4: growth estimates and the 3D scene."""

import os

import pytest

from tr_kb import growth


def test_mature_size_prefers_the_person_then_the_data_then_the_type():
    assert growth.mature_size("orchard", {}, []) == (5.0, 4.0, 7)
    h, c, y = growth.mature_size("orchard", {}, [{"height_ft_mature": "25", "growth_rate": "Moderate"}])
    assert h == pytest.approx(7.62) and y == 10 and c > 4.0
    h, c, y = growth.mature_size("orchard", {"height_m": 3, "plant_spacing_m": 2}, [{"height_ft_mature": "25", "growth_rate": "Rapid"}])
    assert h == 3 and c <= 2.1 and y == 5  # own height wins; canopy kept within the spacing
    # the slowest species sets the pace
    assert growth.mature_size("food-forest", {}, [{"growth_rate": "Rapid"}, {"growth_rate": "Slow"}])[2] == 18


def test_size_over_time():
    assert growth.size_at(-1, 10, 8, 4) is None  # not planted yet
    h0, _ = growth.size_at(0, 10, 8, 4)
    h5, _ = growth.size_at(5, 10, 8, 4)
    h10, c10 = growth.size_at(10, 10, 8, 4)
    assert h0 == pytest.approx(1.2) and h0 < h5 < h10 == 8 and c10 == 4
    assert growth.size_at(30, 10, 8, 4) == (8, 4)
    assert growth.size_at(0, 0, 18, 9) == (18, 9)  # existing woodland: full size


db = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")

LOT = {"type": "Polygon", "coordinates": [[[-122.70, 38.40], [-122.699, 38.40], [-122.699, 38.4008],
                                          [-122.70, 38.4008], [-122.70, 38.40]]]}
HOUSE = {"type": "Polygon", "coordinates": [[[-122.6996, 38.4003], [-122.69950, 38.4003], [-122.69950, 38.40035],
                                            [-122.6996, 38.40035], [-122.6996, 38.4003]]]}
ORCHARD = {"type": "Polygon", "coordinates": [[[-122.69940, 38.4003], [-122.6992, 38.4003], [-122.6992, 38.4006],
                                              [-122.69940, 38.4006], [-122.69940, 38.4003]]]}
WOODS = {"type": "Polygon", "coordinates": [[[-122.69995, 38.4001], [-122.6997, 38.4001], [-122.6997, 38.4007],
                                            [-122.69995, 38.4007], [-122.69995, 38.4001]]]}
TREE = {"type": "Point", "coordinates": [-122.6995, 38.4007]}


@db
def test_scene(client):
    from tr_api.db import execute

    execute("""INSERT INTO species (symbol, scientific_name, common_name, traits, source, license)
               VALUES ('ZZSCN', 'Testus scenicus', 'scene test tree', '{"height_ft_mature": "70", "growth_rate": "Slow"}', 'test', 'pd')
               ON CONFLICT (symbol) DO NOTHING""")
    try:
        _scene_checks(client)
    finally:
        execute("DELETE FROM species WHERE symbol = 'ZZSCN'")


def _scene_checks(client):
    pid = client.post("/api/projects", json={"name": "Scene", "boundary": LOT}).json()["id"]
    post = lambda body: client.post(f"/api/projects/{pid}/plan-features", json=body).json()["properties"]  # noqa: E731
    house = post({"type": "house", "geometry": HOUSE, "props": {"height_m": 7, "roof": "gable"}})
    orchard = post({"type": "orchard", "geometry": ORCHARD, "build_phase": 2, "props": {"row_spacing_m": 6, "plant_spacing_m": 5}})
    post({"type": "existing-forest", "geometry": WOODS})
    post({"type": "shade-tree", "geometry": TREE, "build_phase": 3, "props": {"species": [{"symbol": "ZZSCN"}]}})
    post({"type": "vegetable-garden", "geometry": ORCHARD})

    s = client.get(f"/api/projects/{pid}/plan-scene").json()
    assert s["phase_years"] == [0, 2, 4] and s["terrain"] is False
    parts = {f["properties"]["part"]: f["properties"] for f in s["buildings"]["features"]}
    assert parts["walls"]["id"] == house["id"] and parts["walls"]["year"] == -100  # existing: there from the start
    assert parts["walls"]["height_m"] + 0 < 7 and parts["roof"]["height_m"] == 7 and parts["roof"]["base_m"] == parts["walls"]["height_m"]
    kinds = [k["type"] for k in s["tree_kinds"]]
    woods = [t for t in s["trees"] if kinds[t[6]] == "existing-forest"]
    assert len(woods) > 5 and all(t[2] == 18 and t[4] == 0 and t[5] == -100 for t in woods)  # full size from the start
    assert woods == [t for t in client.get(f"/api/projects/{pid}/plan-scene").json()["trees"] if kinds[t[6]] == "existing-forest"]
    orchard_trees = [t for t in s["trees"] if kinds[t[6]] == "orchard"]
    assert 10 <= len(orchard_trees) <= 20 and all(t[5] == 2 and t[2] == 5.0 for t in orchard_trees)  # phase 2 starts in year 2
    oak = [t for t in s["trees"] if kinds[t[6]] == "shade-tree"]
    assert len(oak) == 1 and oak[0][2] == pytest.approx(21.34) and oak[0][4] == 18 and oak[0][5] == 4
    assert sorted(a["properties"]["type"] for a in s["areas"]["features"]) == ["existing-forest", "orchard", "vegetable-garden"]  # ground under the trees too

    site = client.get(f"/api/projects/{pid}/plan-site").json()["settings"]
    cam = {"center": [-122.6995, 38.4004], "zoom": 17, "pitch": 60, "bearing": -20}
    r = client.put(f"/api/projects/{pid}/plan-site", json={**site, "phase_years": [0, 3, 6], "flight": [cam, {**cam, "bearing": 40}]})
    assert r.status_code == 200, r.text
    assert len(r.json()["settings"]["flight"]) == 2 and r.json()["settings"]["flight"][0]["duration_s"] == 6
    assert client.get(f"/api/projects/{pid}/plan-scene").json()["phase_years"] == [0, 3, 6]
    assert client.put(f"/api/projects/{pid}/plan-site", json={**site, "phase_years": [3, 2, 6]}).status_code == 422
    assert client.put(f"/api/projects/{pid}/plan-site", json={**site, "flight": [{**cam, "pitch": 90}]}).status_code == 422
