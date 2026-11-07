"""The assistant's tool loop with a scripted stand-in for Claude, on synthetic terrain."""

import os
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


class Block(SimpleNamespace):
    def model_dump(self):
        return dict(self.__dict__)


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
