"""Map tiles from the terrain model: Terrarium-encoded elevation (for MapLibre hillshade and 3D) and slope classes.

Tiles are cut on request with rio-tiler from the stored DEM (a tiled GeoTIFF), so nothing extra is precomputed.
"""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from uuid import UUID

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .auth import CurrentUser
from .common import _project_or_404, terrain_or_404
from .storage import get_storage

router = APIRouter()

# Slope classes (percent) → white with increasing opacity, so steep ground reads brighter on the black map.
SLOPE_CLASSES = [(5, 0), (15, 40), (25, 80), (35, 130), (1000, 190)]
EMPTY_PNG_CACHE: dict[str, bytes] = {}
CACHE_HEADERS = {"Cache-Control": "private, max-age=86400"}


def terrarium(z: np.ndarray) -> np.ndarray:
    """Encode elevations (m) as Terrarium RGB: elevation = R*256 + G + B/256 - 32768."""
    v = np.clip(z + 32768.0, 0, 65535.99)
    r = np.floor(v / 256)
    g = np.floor(v - r * 256)
    b = np.floor((v - r * 256 - g) * 256)
    return np.stack([r, g, b]).astype("uint8")


def _fill_nodata(z: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Nearest-valid fill, so tiles at the edge of the model do not drop to sea level in 3D."""
    if valid.all() or not valid.any():
        return z
    from scipy import ndimage

    idx = ndimage.distance_transform_edt(~valid, return_distances=False, return_indices=True)
    return z[tuple(idx)]


@lru_cache(maxsize=8)
def slope_path(dem_path: str) -> str:
    """A slope-percent GeoTIFF next to the cached DEM, built once per DEM."""
    import rasterio

    out = os.path.join(tempfile.gettempdir(), "tr-slope", dem_path.replace("/", "_"))
    if os.path.exists(out):
        return out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with rasterio.open(dem_path) as src:
        z = src.read(1).astype("float64")
        if src.nodata is not None:
            z[z == src.nodata] = np.nan
        res = abs(src.transform.a)
        dzy, dzx = np.gradient(z, res)
        slope = np.hypot(dzx, dzy) * 100
        profile = src.profile.copy()
    profile.update(dtype="float32", nodata=-1.0)
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(np.where(np.isnan(slope), -1.0, slope).astype("float32"), 1)
    return out


def _render(data: np.ndarray) -> bytes:
    from rio_tiler.utils import render

    return render(data, img_format="PNG")


def _empty(kind: str) -> bytes:
    if kind not in EMPTY_PNG_CACHE:
        bands = 3 if kind == "dem" else 4
        EMPTY_PNG_CACHE[kind] = _render(np.zeros((bands, 256, 256), dtype="uint8"))
    return EMPTY_PNG_CACHE[kind]


def dem_bounds_lnglat(dem_path: str) -> list[float]:
    import rasterio
    from rasterio.warp import transform_bounds

    with rasterio.open(dem_path) as src:
        return [round(v, 7) for v in transform_bounds(src.crs, "EPSG:4326", *src.bounds)]


@router.get("/api/projects/{project_id}/tiles/{kind}/{z}/{x}/{y}.png")
def tile(project_id: UUID, kind: str, z: int, x: int, y: int, user: CurrentUser):
    if kind not in ("dem", "slope"):
        raise HTTPException(404, "Unknown tile layer")
    _project_or_404(project_id, user)
    t = terrain_or_404(project_id)
    dem_path = get_storage().local_path(t["dem_path"])
    from rio_tiler.errors import TileOutsideBounds
    from rio_tiler.io import Reader

    path = dem_path if kind == "dem" else slope_path(dem_path)
    try:
        with Reader(path) as src:
            img = src.tile(x, y, z, tilesize=256, resampling_method="bilinear")
    except TileOutsideBounds:
        return Response(_empty(kind), media_type="image/png", headers=CACHE_HEADERS)
    data = img.data[0].astype("float64")
    valid = img.mask > 0
    if kind == "dem":
        if not valid.any():
            return Response(_empty(kind), media_type="image/png", headers=CACHE_HEADERS)
        rgb = terrarium(_fill_nodata(data, valid))
        return Response(_render(rgb), media_type="image/png", headers=CACHE_HEADERS)
    alpha = np.zeros(data.shape, dtype="uint8")
    lower = -np.inf
    for upper, a in SLOPE_CLASSES:
        alpha[(data >= lower) & (data < upper)] = a
        lower = upper
    alpha[~valid | (data < 0)] = 0
    rgba = np.stack([np.full(data.shape, 255, "uint8")] * 3 + [alpha])
    return Response(_render(rgba), media_type="image/png", headers=CACHE_HEADERS)
