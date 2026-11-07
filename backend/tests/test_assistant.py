"""The assistant's tool loop with a scripted stand-in for Claude, on synthetic terrain."""

import os
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


class Block(SimpleNamespace):
    def model_dump(self, exclude_none=False):
        return {k: v for k, v in self.__dict__.items() if not (exclude_none and v is None)}


class FakeClaude:
    """Replays a script of turns; records what the app sent."""

    def __init__(self, turns):
        self.turns, self.calls = list(turns), []
        self.messages = self

    def create(self, **kw):
        import copy

        self.calls.append(copy.deepcopy(kw))
        blocks, stop = self.turns.pop(0)
        return SimpleNamespace(content=[Block(**b) for b in blocks], stop_reason=stop)


def use(i, name, **inp):
    return {"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}


def test_assistant_proposes_and_accepts(client, tmp_path_factory, monkeypatch):
    from conftest import make_terrain_project
    from tr_api import assistant

    pid, _, _ = make_terrain_project(client, tmp_path_factory, "Assistant test")
    fake = FakeClaude([
        ([use(1, "get_site_summary"), use(2, "search_knowledge", query="keyline grade")], "tool_use"),
        ([use(3, "propose_keyline_pattern", keypoint_id="K1", pattern="graded", spacing_m=15),
          use(4, "propose_swale", keypoint_id="K1", rise_m=3, half_length_m=60)], "tool_use"),
        ([use(5, "propose_keyline_pattern", keypoint_id="K9")], "tool_use"),
        ([{"type": "text", "text": "Two options are ready to preview."}], "end_turn"),
    ])
    monkeypatch.setattr(assistant, "client_factory", lambda: fake)
    r = client.post(f"/api/projects/{pid}/assistant",
                    json={"messages": [{"role": "user", "content": "Propose a keyline layout for the west valley"}]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["reply"] == "Two options are ready to preview."
    assert out["model"] == assistant.DESIGN_MODEL  # a design request routes to the stronger model
    kinds = sorted(p["kind"] for p in out["proposals"])
    assert kinds == ["keyline", "swale"]
    assert any(t["error"] for t in out["tool_log"] if t["tool"] == "propose_keyline_pattern")  # K9 does not exist
    # the model saw real tool results, including the site's keypoints, and the cached system prompt
    first_results = fake.calls[1]["messages"][-1]["content"]
    assert '"keypoints"' in first_results[0]["content"]
    assert fake.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    swale = next(p for p in out["proposals"] if p["kind"] == "swale")
    assert swale["summary"]["storage_gal"] > 0 and swale["preview"]["features"][0]["geometry"]["type"] == "LineString"

    # nothing is in the design until accepted
    assert client.get(f"/api/projects/{pid}/design").json()["features"] == []
    kl = next(p for p in out["proposals"] if p["kind"] == "keyline")
    a = client.post(f"/api/projects/{pid}/assistant/proposals/{kl['id']}/accept")
    assert a.status_code == 200 and a.json()["status"] == "accepted"
    assert client.post(f"/api/projects/{pid}/assistant/proposals/{kl['id']}/accept").status_code == 409
    feats = client.get(f"/api/projects/{pid}/design").json()["features"]
    assert any(f["properties"]["kind"] == "keyline" for f in feats)
    assert client.post(f"/api/projects/{pid}/assistant/proposals/{swale['id']}/discard").status_code == 204
    assert client.get(f"/api/projects/{pid}/assistant/proposals").json() == []


def test_question_uses_default_model(client, tmp_path_factory, monkeypatch):
    from conftest import make_terrain_project
    from tr_api import assistant

    pid, _, _ = make_terrain_project(client, tmp_path_factory, "Assistant Q")
    fake = FakeClaude([([{"type": "text", "text": "Water leaves to the south."}], "end_turn")])
    monkeypatch.setattr(assistant, "client_factory", lambda: fake)
    out = client.post(f"/api/projects/{pid}/assistant", json={"messages": [{"role": "user", "content": "Which way does water leave?"}]}).json()
    assert out["model"] == assistant.DEFAULT_MODEL and out["proposals"] == []


def test_bad_tool_arguments_become_tool_errors(client, tmp_path_factory, monkeypatch):
    from conftest import make_terrain_project
    from tr_api import assistant

    pid, _, _ = make_terrain_project(client, tmp_path_factory, "Assistant errors")
    fake = FakeClaude([
        ([use(1, "propose_keyline_pattern", keypoint_id="K" * 40), use(2, "find_species", min_temp_f_at_most="cold"),
          use(3, "search_knowledge", query="??")], "tool_use"),
        ([{"type": "text", "text": "Sorry, those did not work."}], "end_turn"),
    ])
    monkeypatch.setattr(assistant, "client_factory", lambda: fake)
    r = client.post(f"/api/projects/{pid}/assistant", json={"messages": [{"role": "user", "content": "Try things"}]})
    assert r.status_code == 200, r.text
    results = fake.calls[1]["messages"][-1]["content"]
    assert results[0].get("is_error") is True
    assert r.json()["reply"] == "Sorry, those did not work."
    # the conversation must end on a user turn
    bad = client.post(f"/api/projects/{pid}/assistant", json={"messages": [{"role": "assistant", "content": "hi"}]})
    assert bad.status_code == 422


def test_summary_counts_saved_rip_lines(client, tmp_path_factory):
    from conftest import make_terrain_project
    from tr_api.assistant import _site_summary
    from tr_api.common import _project_or_404
    from tr_api.db import fetch_one

    pid, _, _ = make_terrain_project(client, tmp_path_factory, "Assistant summary")
    res = client.post(f"/api/projects/{pid}/design/keylines", json={"keypoint_id": "K1", "spacing_m": 15, "pattern": "graded", "max_lines": 6}).json()
    owner = fetch_one("SELECT owner_id AS id FROM projects WHERE id = :id", id=pid)
    s = _site_summary(pid, _project_or_404(pid, owner))
    kl = next(e for e in s["design_elements"] if e["kind"] == "keyline")
    assert kl["rip_lines"] == res["rip_count"] > 0


def test_steps_decide_tools_and_guide(client, tmp_path_factory, monkeypatch):
    """Off the Design step the assistant coaches: no design tools, the step's guide page, Sonnet."""
    from conftest import make_terrain_project
    from tr_api import assistant

    pid, _, _ = make_terrain_project(client, tmp_path_factory, "Assistant steps")
    fake = FakeClaude([
        ([use(1, "propose_keyline_pattern", keypoint_id="K1")], "tool_use"),  # not offered here; refused if asked
        ([{"type": "text", "text": "Confirm K1 first."}], "end_turn"),
    ])
    monkeypatch.setattr(assistant, "client_factory", lambda: fake)
    ctx = {"selected_keypoint": "K1", "keypoints_confirmed": 0}
    r = client.post(f"/api/projects/{pid}/assistant", json={
        "messages": [{"role": "user", "content": "Propose a keyline pattern from K1"}],
        "step": "terrain", "page_context": ctx})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["model"] == assistant.DEFAULT_MODEL  # no design tools on this step, so no design model
    assert out["proposals"] == []
    assert out["tool_log"][0]["error"] == "propose_keyline_pattern is not available on the Terrain step"
    sent = fake.calls[0]
    assert {t["name"] for t in sent["tools"]} == assistant.STEP_TOOLS["terrain"]
    assert "Where the water goes." in sent["system"][1]["text"]  # the Terrain guide page
    assert '"selected_keypoint": "K1"' in sent["system"][1]["text"]
    assert "cache_control" in sent["system"][0] and "cache_control" not in sent["system"][1]
    assert client.get(f"/api/projects/{pid}/assistant/proposals").json() == []


def test_coaching_works_before_terrain(client, monkeypatch):
    """The Site and Survey steps have no terrain model; the assistant still answers from the project facts."""
    from tr_api import assistant

    boundary = {"type": "Polygon", "coordinates": [[[-122.9, 38.4], [-122.89, 38.4], [-122.89, 38.41], [-122.9, 38.41], [-122.9, 38.4]]]}
    r = client.post("/api/projects", json={"name": "No terrain yet", "address": "", "boundary": boundary, "boundary_source": "drawn"})
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    fake = FakeClaude([
        ([use(1, "get_site_summary")], "tool_use"),
        ([{"type": "text", "text": "Fetch public elevation next."}], "end_turn"),
    ])
    monkeypatch.setattr(assistant, "client_factory", lambda: fake)
    r = client.post(f"/api/projects/{pid}/assistant", json={
        "messages": [{"role": "user", "content": "What should I do next?"}], "step": "survey"})
    assert r.status_code == 200, r.text
    summary = fake.calls[1]["messages"][-1]["content"][0]["content"]
    assert '"terrain": null' in summary and '"surveys": []' in summary
    assert {t["name"] for t in fake.calls[0]["tools"]} == {"get_site_summary", "search_knowledge"}


def test_page_context_is_bounded(client):
    r = client.post("/api/projects/00000000-0000-0000-0000-000000000000/assistant", json={
        "messages": [{"role": "user", "content": "hi"}], "step": "site", "page_context": {"x": "y" * 5000}})
    assert r.status_code == 422
    r = client.post("/api/projects/00000000-0000-0000-0000-000000000000/assistant", json={
        "messages": [{"role": "user", "content": "hi"}], "step": "export"})
    assert r.status_code == 422


def test_question_tags():
    from tr_api.assistant import question_tag

    assert question_tag("How do I confirm a keypoint?") == "how-to"
    assert question_tag("Propose two keyline options") == "design-request"
    assert question_tag("What does a score of 0.49 mean?") == "explain"
