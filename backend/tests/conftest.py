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
