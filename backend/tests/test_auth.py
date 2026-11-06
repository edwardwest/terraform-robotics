"""Authentication and per-user isolation. Needs TEST_DATABASE_URL like test_api.py."""

import os

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")

SQUARE = {"type": "Polygon", "coordinates": [[[-122.3, 37.8], [-122.29, 37.8], [-122.29, 37.81], [-122.3, 37.81], [-122.3, 37.8]]]}


@pytest.fixture
def api(client):
    """The authenticated client from test_api, plus a helper for other identities."""
    return client


def _as(client, token):
    return {"Authorization": f"Bearer {token}"}


def test_signed_out_requests_are_rejected(api):
    r = api.get("/api/projects", headers={"Authorization": ""})
    assert r.status_code == 401
    assert api.get("/api/health", headers={"Authorization": ""}).status_code == 200  # health stays public


def test_me_creates_user_from_claims(api):
    r = api.get("/api/me")
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com" and r.json()["name"] == "Alice"


def test_users_only_see_their_own_projects(api, signing_key):
    pid = api.post("/api/projects", json={"name": "Alice's farm", "boundary": SQUARE}).json()["id"]
    bob = _as(api, signing_key["token"]("user_bob", email="bob@example.com"))
    assert api.get(f"/api/projects/{pid}", headers=bob).status_code == 404
    assert all(p["id"] != pid for p in api.get("/api/projects", headers=bob).json())
    assert api.post(f"/api/projects/{pid}/terrain-jobs", headers=bob, json={}).status_code == 404
    assert api.get(f"/files/projects/{pid}/terrain/dem.tif", headers=bob).status_code == 404
    assert any(p["id"] == pid for p in api.get("/api/projects").json())


@pytest.mark.parametrize("case", ["expired", "wrong_key", "wrong_party", "garbage"])
def test_bad_tokens_are_rejected(api, signing_key, case):
    from cryptography.hazmat.primitives.asymmetric import rsa

    t = signing_key["token"]
    token = {
        "expired": lambda: t("user_alice", expires_in=-60),
        "wrong_key": lambda: t("user_alice", key=rsa.generate_private_key(public_exponent=65537, key_size=2048)),
        "wrong_party": lambda: t("user_alice", azp="https://evil.example"),
        "garbage": lambda: "not-a-jwt",
    }[case]()
    assert api.get("/api/projects", headers=_as(api, token)).status_code == 401
