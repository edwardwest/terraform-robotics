"""Base images for the master plan sheet: a faded aerial photo (USGS National Map imagery, public domain) or terrain
shading from the project's DEM, resampled onto the sheet's map frame in its UTM grid. Both return RGB arrays, or None
when the source isn't available, so the sheet can fall back to the next option."""

from __future__ import annotations

import logging
import math
from functools import lru_cache

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds, from_origin
from rasterio.warp import Resampling, reproject, transform_bounds

log = logging.getLogger(__name__)

AERIAL_URL = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}"
AERIAL_ATTRIBUTION = "Imagery: USGS The National Map"
USER_AGENT = "TerraformRobotics/0.1 (master plan sheet)"
SAGE = np.array([169, 179, 156], dtype=np.float32)
MAX_TILES = 48
WEB_MERCATOR_HALF = 20037508.342789244


def _fade(rgb: np.ndarray, desaturate: float = 0.45, lighten: float = 0.18) -> np.ndarray:
    """Mute a photo so the plan reads on top of it: pull toward grey, then toward white."""
    f = rgb.astype(np.float32)
    grey = f @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    f = f * (1 - desaturate) + grey[..., None] * desaturate
    f = f * (1 - lighten) + 255 * lighten
    return np.clip(f, 0, 255).astype(np.uint8)


def hillshade(dem_path: str, crs: str, bounds: tuple[float, float, float, float], width: int, height: int) -> np.ndarray | None:
    """Sage-tinted hillshade of the DEM on the given grid (bounds in `crs`), or None where the DEM can't be read."""
    try:
        dst = np.full((height, width), np.nan, dtype=np.float32)
        transform = from_bounds(*bounds, width, height)
        with rasterio.open(dem_path) as src:
            reproject(source=rasterio.band(src, 1), destination=dst, src_transform=src.transform, src_crs=src.crs,
                      src_nodata=src.nodata, dst_transform=transform, dst_crs=crs, dst_nodata=np.nan,
                      resampling=Resampling.bilinear)
    except Exception:  # noqa: BLE001 - a missing or unreadable DEM just means no shading
        log.exception("hillshade: could not read DEM")
        return None
    valid = np.isfinite(dst)
    if valid.mean() < 0.05:
        return None
    z = np.where(valid, dst, np.nanmean(dst))
    px = (bounds[2] - bounds[0]) / width
    dzdy, dzdx = np.gradient(z, px)
    slope = np.arctan(np.hypot(dzdx, dzdy) * 1.5)  # slight vertical exaggeration for readability
    aspect = np.arctan2(-dzdx, dzdy)
    az, alt = math.radians(315), math.radians(45)
    hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    hs = np.clip(hs, 0, 1)
    shade = 0.62 + 0.45 * hs
    rgb = np.clip(SAGE[None, None, :] * shade[..., None], 0, 255)
    rgb[~valid] = SAGE
    return rgb.astype(np.uint8)


def _tile_range(lon0: float, lat0: float, lon1: float, lat1: float, z: int) -> tuple[int, int, int, int]:
    n = 2 ** z

    def xy(lon: float, lat: float) -> tuple[int, int]:
        x = int((lon + 180) / 360 * n)
        lr = math.radians(lat)
        y = int((1 - math.log(math.tan(lr) + 1 / math.cos(lr)) / math.pi) / 2 * n)
        return min(max(x, 0), n - 1), min(max(y, 0), n - 1)

    x0, y0 = xy(lon0, lat1)
    x1, y1 = xy(lon1, lat0)
    return x0, y0, x1, y1


def _fetch_tile(client, z: int, x: int, y: int) -> np.ndarray | None:
    r = client.get(AERIAL_URL.format(z=z, x=x, y=y))
    if r.status_code != 200 or not r.content:
        return None
    with MemoryFile(r.content) as mem, mem.open() as ds:
        a = ds.read()
    if a.shape[0] == 1:
        a = np.repeat(a, 3, axis=0)
    return np.moveaxis(a[:3], 0, -1)


@lru_cache(maxsize=16)
def _aerial_cached(crs: str, bounds: tuple[float, float, float, float], width: int, height: int) -> bytes | None:
    import httpx

    lon0, lat0, lon1, lat1 = transform_bounds(crs, "EPSG:4326", *bounds)
    target = (bounds[2] - bounds[0]) / width  # metres per output pixel
    lat = (lat0 + lat1) / 2

    def res(z: int) -> float:  # metres per tile pixel at this latitude
        return 156543.03392 * math.cos(math.radians(lat)) / 2 ** z

    def count(z: int) -> int:
        x0, y0, x1, y1 = _tile_range(lon0, lat0, lon1, lat1, z)
        return (x1 - x0 + 1) * (y1 - y0 + 1)

    # The coarsest zoom that is still at least as sharp as the output, within the tile budget.
    z = 19
    while z > 10 and (res(z - 1) <= target or count(z) > MAX_TILES):
        z -= 1
    x0, y0, x1, y1 = _tile_range(lon0, lat0, lon1, lat1, z)
    if (x1 - x0 + 1) * (y1 - y0 + 1) > MAX_TILES:
        return None
    mosaic = np.zeros(((y1 - y0 + 1) * 256, (x1 - x0 + 1) * 256, 3), dtype=np.uint8)
    got = 0
    with httpx.Client(timeout=6.0, headers={"User-Agent": USER_AGENT}) as client:
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                t = _fetch_tile(client, z, tx, ty)
                if t is not None and t.shape[:2] == (256, 256):
                    mosaic[(ty - y0) * 256:(ty - y0 + 1) * 256, (tx - x0) * 256:(tx - x0 + 1) * 256] = t
                    got += 1
    if got == 0:
        return None
    size = 2 * WEB_MERCATOR_HALF / 2 ** z  # metres per tile in web mercator
    src_transform = from_origin(-WEB_MERCATOR_HALF + x0 * size, WEB_MERCATOR_HALF - y0 * size, size / 256, size / 256)
    out = np.zeros((3, height, width), dtype=np.uint8)
    for b in range(3):
        reproject(source=np.ascontiguousarray(mosaic[..., b]), destination=out[b], src_transform=src_transform,
                  src_crs="EPSG:3857", dst_transform=from_bounds(*bounds, width, height), dst_crs=crs,
                  resampling=Resampling.bilinear)
    return _fade(np.moveaxis(out, 0, -1)).tobytes()


def aerial(crs: str, bounds: tuple[float, float, float, float], width: int, height: int) -> np.ndarray | None:
    """Faded aerial photo on the given grid, or None if the imagery service can't be reached."""
    key = tuple(round(v, 1) for v in bounds)
    try:
        raw = _aerial_cached(crs, key, width, height)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - network or decode trouble falls back to shading
        log.warning("aerial basemap unavailable", exc_info=True)
        return None
    return None if raw is None else np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)


def png_bytes(rgb: np.ndarray) -> bytes:
    import warnings

    from rasterio.errors import NotGeoreferencedWarning

    h, w, _ = rgb.shape
    warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)  # a plain picture; placed by the SVG
    with MemoryFile() as mem:
        with mem.open(driver="PNG", width=w, height=h, count=3, dtype="uint8") as ds:
            ds.write(np.moveaxis(rgb, -1, 0))
        return mem.read()


__all__ = ["aerial", "hillshade", "png_bytes", "AERIAL_ATTRIBUTION"]
