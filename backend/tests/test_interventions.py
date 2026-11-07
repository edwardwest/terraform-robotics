"""The intervention catalog and recommender: pure code, no database."""

import pytest

from tr_kb import interventions as iv
from tr_kb.rules import load_references, load_rules, load_topics


def test_catalog_is_consistent():
    data = iv.catalog()
    goals = set(iv.goal_ids())
    phases = {p["id"] for p in data["phases"]}
    categories = {c["id"] for c in data["categories"]}
    topics = set(load_topics())
    rules = {r["id"] for r in load_rules()[1]}
    refs = {r["id"] for r in load_references()[1]}
    ids = [i["id"] for i in data["interventions"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 20
    for i in data["interventions"]:
        assert set(i["goals"]) <= goals and all(w in (1, 2, 3) for w in i["goals"].values()), i["id"]
        assert i["phase"] in phases and i["category"] in categories, i["id"]
        assert set(i["topics"]) <= topics, i["id"]
        assert set(i["rules"]) <= rules, i["id"]
        assert set(i["references"]) <= refs, i["id"]
        assert set(i["requires"]) <= {"terrain", "valley", "creek", "buildings"}, i["id"]
        assert i["maintenance"] in ("low", "medium", "high") and i["cost_tier"] in (1, 2, 3, 4), i["id"]
        assert i["tool"] in (None, "keyline", "swale"), i["id"]
        # every intervention either has a design tool or a costed allowance with a quantity basis
        if i["tool"]:
            assert not i["cost_item"], i["id"]
        else:
            assert i["cost_item"] and i["quantity"]["basis"] in ("area_m2", "length_m", "volume_m3", "count"), i["id"]
        assert all(len(c) < 400 for c in i["cautions"]), i["id"]
    # every goal is a main purpose of some intervention (income is a supporting goal: served well by several)
    for g in goals - {"income"}:
        assert any(i["goals"].get(g) == 3 for i in data["interventions"]), g
    assert sum(1 for i in data["interventions"] if i["goals"].get("income", 0) >= 2) >= 2


def test_cost_items_exist_for_allowances():
    sql = open(__file__.replace("tests/test_interventions.py", "sql/006_goals_and_plan.sql")).read()
    for i in iv.catalog()["interventions"]:
        if i["cost_item"]:
            assert f"'{i['cost_item']}'" in sql, i["id"]


def _top(brief, site, n=6):
    return [r["id"] for r in iv.recommend(brief, site) if r["fit"] == "good"][:n]


def test_small_lot_gets_household_ideas_not_keyline():
    recs = {r["id"]: r for r in iv.recommend(
        {"goals": ["water_security", "food"], "has_buildings": True}, {"area_m2": 700})}
    assert recs["keyline"]["fit"] == "not_suited" and recs["pond"]["fit"] == "not_suited"
    assert any("Needs at least" in c for c in recs["keyline"]["concerns"])
    good = _top({"goals": ["water_security", "food"], "has_buildings": True}, {"area_m2": 700})
    assert "roof-catchment" in good and "greywater-laundry" in good
    assert recs["roof-catchment"]["reasons"][0].startswith("A main way to meet your top goal")


def test_ranch_with_valleys_and_water_goal_gets_keyline():
    site = {"area_m2": 160_000, "mean_slope_pct": 9, "has_terrain": True, "main_valleys": 2, "keypoint_count": 2}
    recs = {r["id"]: r for r in iv.recommend({"goals": ["water_security", "soil"]}, site)}
    assert recs["keyline"]["fit"] == "good"
    assert "Suits this site's average slope of 9%." in recs["keyline"]["reasons"]


def test_fire_goal_puts_fire_work_first():
    good = _top({"goals": ["fire"], "has_buildings": True}, {"area_m2": 40_000}, n=3)
    assert good[0] == "defensible-space" or good[0] == "fuel-break"
    assert set(good) & {"defensible-space", "fuel-break"} and "keyline" not in good


def test_unanswered_questions_do_not_demote_but_terrain_checks_wait():
    recs = {r["id"]: r for r in iv.recommend({"goals": ["water_security"]}, {"area_m2": 50_000})}
    assert recs["roof-catchment"]["fit"] == "good"
    assert recs["roof-catchment"]["unknowns"] == ["Assumes a house or other building on site."]
    # earthworks wait for the terrain model, with one note rather than one per requirement
    keyline = recs["keyline"]
    assert keyline["fit"] == "possible" and len(keyline["unknowns"]) == 1 and "terrain model" in keyline["unknowns"][0]


def test_option_labels_keep_their_commas():
    labels = {o["id"]: o["label"] for o in iv.catalog()["questions"]["budget"]}
    assert labels["under_5k"] == "Under $5,000" and labels["over_100k"] == "Over $100,000"


def test_budget_upkeep_and_constraints_add_concerns():
    brief = {"goals": ["food"], "budget": "under_5k", "maintenance": "low", "constraints": ["renting"]}
    recs = {r["id"]: r for r in iv.recommend(brief, {"area_m2": 5_000})}
    ff = recs["food-forest"]
    assert ff["fit"] == "possible"
    assert any("upkeep" in c for c in ff["concerns"]) and any("landowner" in c for c in ff["concerns"])
    assert any("budget" in c for c in recs["high-tunnel"]["concerns"])


def test_steep_site_flags_slope_but_keeps_it_possible():
    site = {"area_m2": 30_000, "mean_slope_pct": 32, "has_terrain": True, "main_valleys": 1}
    swale = next(r for r in iv.recommend({"goals": ["water_security"]}, site) if r["id"] == "swale")
    assert swale["fit"] == "possible"
    assert any("this site averages 32%" in c for c in swale["concerns"])


def test_missing_creek_rules_out_riparian():
    r = next(r for r in iv.recommend({"goals": ["habitat"], "water_sources": ["well"]}, {}) if r["id"] == "riparian-buffer")
    assert r["fit"] == "not_suited"


def test_no_goals_lists_everything_as_possible():
    recs = iv.recommend({}, {"area_m2": 5_000})
    assert {r["fit"] for r in recs} <= {"possible", "not_suited"}
    assert all(r["score"] == 0 for r in recs)


def test_sequence_follows_scale_of_permanence():
    ids = ["sheet-mulch", "poultry", "food-forest", "access-on-contour", "roof-catchment"]
    assert [i["id"] for i in iv.sequence(ids + ["not-a-thing"])] == [
        "roof-catchment", "access-on-contour", "food-forest", "poultry", "sheet-mulch"]


@pytest.mark.parametrize("basis,qty,unit,expected", [
    ("area_m2", 4046.8564224, "acre", 1.0),
    ("area_m2", 0.09290304, "sq ft", 1.0),
    ("length_m", 1.0, "linear foot", 3.28084),
    ("volume_m3", 1.0, "gallon", 264.172),
    ("count", 3, "tree", 3),
])
def test_quantity_units(basis, qty, unit, expected):
    assert iv.quantity_in_cost_unit(basis, qty, unit) == pytest.approx(expected)


def test_intervention_documents_for_search():
    docs = iv.intervention_documents()
    pond = next(d for d in docs if d["code"] == "pond")
    assert pond["source"] == "interventions" and pond["commercial_ok"]
    assert "378" in pond["body"] and "Division of Safety of Dams" in pond["body"]
