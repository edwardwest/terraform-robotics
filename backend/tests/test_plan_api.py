"""Goals brief, recommendations, plan and plan allowances in the estimate, over the API."""

import os

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")

LOT = {"type": "Polygon", "coordinates": [[[-122.70, 38.40], [-122.6995, 38.40], [-122.6995, 38.4004],
                                          [-122.70, 38.4004], [-122.70, 38.40]]]}  # about 1.1 acres


@pytest.fixture
def pid(client):
    return client.post("/api/projects", json={"name": "Goals test", "boundary": LOT}).json()["id"]


def test_catalog_lists_goals_questions_and_interventions(client):
    r = client.get("/api/interventions/catalog")
    assert r.status_code == 200
    c = r.json()
    assert len(c["goals"]) == 10 and "budget" in c["questions"]
    assert any(i["id"] == "keyline" and i["tool"] == "keyline" for i in c["interventions"])


def test_brief_merges_and_validates(client, pid):
    assert client.get(f"/api/projects/{pid}/brief").json()["goals"] is None
    r = client.put(f"/api/projects/{pid}/brief", json={"goals": ["food", "water_security"], "has_buildings": True,
                                                      "budget": "under_5k"})
    assert r.status_code == 200, r.text
    r = client.put(f"/api/projects/{pid}/brief", json={"maintenance": "low", "budget": None})
    b = r.json()
    assert b["goals"] == ["food", "water_security"] and b["maintenance"] == "low" and b["budget"] is None
    assert b["has_buildings"] is True and b["updated_at"]
    assert client.put(f"/api/projects/{pid}/brief", json={"goals": ["world_peace"]}).status_code == 422
    assert client.put(f"/api/projects/{pid}/brief", json={"budget": "lots"}).status_code == 422
    assert client.put(f"/api/projects/{pid}/brief", json={"goals": ["food", "food"]}).status_code == 422


def test_recommendations_follow_the_brief(client, pid):
    before = client.get(f"/api/projects/{pid}/recommendations").json()
    assert before["brief_complete"] is False and before["site"]["has_terrain"] is False
    client.put(f"/api/projects/{pid}/brief", json={"goals": ["water_security"], "has_buildings": True})
    rec = client.get(f"/api/projects/{pid}/recommendations").json()
    assert rec["brief_complete"] is True
    items = {i["id"]: i for i in rec["items"]}
    assert items["roof-catchment"]["fit"] == "good"
    assert items["keyline"]["fit"] == "not_suited"  # an acre is too small for a keyline pattern
    refs = items["roof-catchment"]["references"]
    assert {r["id"] for r in refs} == {"lancaster-rainwater-v1", "oaec-water-publications"}
    assert all(r["url"] is None or r["url"].startswith("https://") for r in refs) and refs[0]["work_license"]


def test_plan_sequences_and_feeds_estimate(client, pid):
    assert client.put(f"/api/projects/{pid}/plan/nope", json={}).status_code == 404
    r = client.put(f"/api/projects/{pid}/plan/sheet-mulch", json={})
    assert r.status_code == 200 and r.json()["quantity"] == 100  # catalog default, m²
    client.put(f"/api/projects/{pid}/plan/roof-catchment", json={"quantity": 18.927})  # 5,000 gal
    client.put(f"/api/projects/{pid}/plan/swale", json={"quantity": 50})  # tool items carry no allowance quantity
    r = client.put(f"/api/projects/{pid}/plan/sheet-mulch", json={"notes": "front lawn"})
    assert r.json()["quantity"] == 100 and r.json()["notes"] == "front lawn"
    plan = client.get(f"/api/projects/{pid}/plan").json()
    assert [p["intervention_id"] for p in plan] == ["roof-catchment", "swale", "sheet-mulch"]
    assert plan[1]["quantity"] is None and plan[1]["tool"] == "swale"

    est = client.get(f"/api/projects/{pid}/estimate").json()
    lines = {ln["item"]: ln for ln in est["lines"]}
    assert set(lines) == {"tank_gal", "sheet_mulch_sqft"}
    assert all(ln["group"] == "plan" for ln in est["lines"])
    assert lines["tank_gal"]["quantity"] == pytest.approx(5000, abs=1)
    assert lines["sheet_mulch_sqft"]["quantity"] == pytest.approx(1076.4, abs=0.1)
    assert est["design_fee_low"] == 0  # no computed layout, no per-acre design fee
    assert est["total_low"] > 0

    rec = {i["id"]: i for i in client.get(f"/api/projects/{pid}/recommendations").json()["items"]}
    assert rec["sheet-mulch"]["selected"] and not rec["pond"]["selected"]
    assert client.delete(f"/api/projects/{pid}/plan/sheet-mulch").status_code == 204
    assert len(client.get(f"/api/projects/{pid}/plan").json()) == 2


def test_assistant_interviews_and_suggests_brief(client, pid, monkeypatch):
    from test_assistant import FakeClaude, use
    from tr_api import assistant

    fake = FakeClaude([
        ([use(1, "get_site_summary")], "tool_use"),
        ([use(2, "suggest_brief", goals=["fire", "water_security"], has_buildings=True),
          use(3, "suggest_brief", maintenance="low"), use(4, "suggest_brief", goals=["moonbeams"])], "tool_use"),
        ([use(5, "recommend_interventions", category="fire")], "tool_use"),
        ([{"type": "text", "text": "Here is what I heard. Apply it if it looks right."}], "end_turn"),
    ])
    monkeypatch.setattr(assistant, "client_factory", lambda: fake)
    r = client.post(f"/api/projects/{pid}/assistant", json={
        "messages": [{"role": "user", "content": "Fire scares me most, then water. We have a house. Low upkeep please."}],
        "step": "goals"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["brief_suggestion"] == {"goals": ["fire", "water_security"], "has_buildings": True, "maintenance": "low"}
    assert any(t["error"] for t in out["tool_log"] if t["tool"] == "suggest_brief")  # invalid goal rejected
    assert {t["name"] for t in fake.calls[0]["tools"]} == assistant.STEP_TOOLS["goals"]
    assert "Goals" in fake.calls[0]["system"][1]["text"] and "step 2 of 7" in fake.calls[0]["system"][1]["text"]
    summary = fake.calls[1]["messages"][-1]["content"][0]["content"]
    assert '"brief": null' in summary and "No goals brief yet" in summary
    recs = fake.calls[3]["messages"][-1]["content"][0]["content"]
    assert '"defensible-space"' in recs and '"keyline"' not in recs  # category filter
    # nothing was saved: the person applies the suggestion themselves
    assert client.get(f"/api/projects/{pid}/brief").json()["goals"] is None
