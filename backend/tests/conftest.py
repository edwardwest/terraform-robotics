import os
import numpy as np
import pytest
from affine import Affine
from shapely.geometry import box

from tr_geo.dem import Dem

ORIGIN_X, ORIGIN_Y = 500_000.0, 4_250_000.0  # UTM zone 10N, northern California


def two_valley_terrain(rows=360, cols=320, res=1.0, break_row=170):
    """Slope falling to the south with two valleys; each valley floor turns from steep to gentle at break_row."""
    r = np.arange(rows)[:, None].astype(float)
    c = np.arange(cols)[None, :].astype(float)
    steep, gentle = 0.22, 0.04
    # smooth transition between the two gradients around break_row
    t = 0.5 * (1 + np.tanh((r - break_row) / 12.0))
    grad = steep * (1 - t) + gentle * t
    base = 120.0 - np.cumsum(grad, axis=0) * res
    valleys = np.zeros_like(c)
    for vc in (100, 225):
        # broad valley plus a narrow channel notch along its floor
        valleys = valleys - 4.0 * np.exp(-((c - vc) ** 2) / (2 * 14**2)) - 2.0 * np.exp(-((c - vc) ** 2) / (2 * 2**2))
    z = base + valleys + 0.002 * c  # slight tilt so flat ties resolve
    return Dem(z, Affine(res, 0, ORIGIN_X, 0, -res, ORIGIN_Y), "EPSG:32610")


@pytest.fixture
def terrain():
    return two_valley_terrain()


@pytest.fixture
def boundary(terrain):
    rows, cols = terrain.shape
    inset = 15 * terrain.res
    return box(ORIGIN_X + inset, ORIGIN_Y - rows * terrain.res + inset, ORIGIN_X + cols * terrain.res - inset, ORIGIN_Y - inset)


@pytest.fixture(scope="session")
def signing_key():
    """An RSA key standing in for Clerk's: `token(sub, ...)` mints session tokens the API will accept."""
    import time

    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()

    def token(sub, email=None, name=None, azp="http://localhost:3000", expires_in=300, key=private):
        now = int(time.time())
        claims = {"sub": sub, "iat": now, "nbf": now, "exp": now + expires_in, "azp": azp,
                  "iss": "https://example.clerk.accounts.dev"}
        if email:
            claims["email"] = email
        if name:
            claims["name"] = name
        return jwt.encode(claims, key, algorithm="RS256")

    return {"public_pem": public_pem, "token": token}


@pytest.fixture(scope="session")
def client(tmp_path_factory, signing_key):
    DB_URL = os.environ["TEST_DATABASE_URL"]
    os.environ["DATABASE_URL"] = DB_URL
    os.environ["STORAGE_URL"] = "file://" + str(tmp_path_factory.mktemp("storage"))
    os.environ["JOB_RUNNER"] = "inline"
    os.environ["CLERK_JWT_KEY"] = signing_key["public_pem"]
    os.environ["CLERK_AUTHORIZED_PARTIES"] = "http://localhost:3000"
    from fastapi.testclient import TestClient

    from tr_api.config import get_settings
    from tr_api.storage import get_storage

    get_settings.cache_clear()
    get_storage.cache_clear()
    from tr_api.main import app

    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {signing_key['token']('user_alice', email='alice@example.com', name='Alice')}"
    return c




def make_terrain_project(client, tmp_path_factory, name="Design test"):
    """A project on the synthetic two-valley terrain with a finished terrain job. Returns (id, boundary, terrain)."""
    import time

    from shapely.geometry import box, mapping

    from tr_geo import project_geometry, write_geotiff

    terrain = two_valley_terrain()
    rows, cols = terrain.shape
    x0, y0 = terrain.transform.c, terrain.transform.f
    b = mapping(project_geometry(box(x0 + 15, y0 - rows + 15, x0 + cols - 15, y0 - 15), terrain.crs, "EPSG:4326"))
    boundary = {"type": "Polygon", "coordinates": [[list(p) for p in b["coordinates"][0]]]}
    pid = client.post("/api/projects", json={"name": name, "boundary": boundary}).json()["id"]
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
