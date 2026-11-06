"""Digital elevation models: a small container plus read, write, reproject and clip helpers.

All analysis happens on a `Dem` in a projected CRS (metres), usually the local UTM zone.
Nodata cells are NaN.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import rasterio
from affine import Affine
from pyproj import CRS, Transformer
from rasterio.features import geometry_mask
from rasterio.warp import Resampling, calculate_default_transform, reproject
from shapely.geometry import Polygon, mapping
import shapely


@dataclass
class Dem:
    elevation: np.ndarray  # float64, rows x cols, NaN = nodata
    transform: Affine  # pixel → CRS coordinates (top-left origin, north-up)
    crs: str  # e.g. "EPSG:32610"

    @property
    def res(self) -> float:
        return float(abs(self.transform.a))

    @property
    def shape(self) -> tuple[int, int]:
        return self.elevation.shape

    def xy(self, rows: np.ndarray, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Cell centres in CRS coordinates."""
        rows = np.asarray(rows, dtype=float)
        cols = np.asarray(cols, dtype=float)
        x = self.transform.c + (cols + 0.5) * self.transform.a
        y = self.transform.f + (rows + 0.5) * self.transform.e
        return x, y

    def rowcol(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        col = (np.asarray(x, dtype=float) - self.transform.c) / self.transform.a - 0.5
        row = (np.asarray(y, dtype=float) - self.transform.f) / self.transform.e - 0.5
        return row, col


def utm_crs_for(lon: float, lat: float) -> str:
    """EPSG code of the WGS84 UTM zone containing a point."""
    zone = int((lon + 180) // 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


def project_geometry(geom, src_crs: str, dst_crs: str):
    transformer = Transformer.from_crs(CRS.from_user_input(src_crs), CRS.from_user_input(dst_crs), always_xy=True)

    def _apply(coords: np.ndarray) -> np.ndarray:
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(geom, _apply)


def read_geotiff(path: str) -> Dem:
    with rasterio.open(path) as src:
        arr = src.read(1).astype("float64")
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
        crs = src.crs.to_string() if src.crs else None
        if crs is None:
            raise ValueError("DEM has no coordinate reference system")
        return Dem(arr, src.transform, crs)


def write_geotiff(dem: Dem, path: str) -> None:
    profile = {
        "driver": "GTiff",
        "height": dem.shape[0],
        "width": dem.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": dem.crs,
        "transform": dem.transform,
        "nodata": -9999.0,
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "compress": "deflate",
    }
    data = np.where(np.isnan(dem.elevation), -9999.0, dem.elevation).astype("float32")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def reproject_dem(dem: Dem, dst_crs: str, res: float) -> Dem:
    """Reproject and resample (bilinear) to a square-pixel grid in `dst_crs`."""
    rows, cols = dem.shape
    left, top = dem.transform.c, dem.transform.f
    right = left + cols * dem.transform.a
    bottom = top + rows * dem.transform.e
    transform, width, height = calculate_default_transform(
        dem.crs, dst_crs, cols, rows, left=left, bottom=bottom, right=right, top=top, resolution=res
    )
    out = np.full((height, width), np.nan, dtype="float64")
    reproject(
        source=dem.elevation,
        destination=out,
        src_transform=dem.transform,
        src_crs=dem.crs,
        dst_transform=transform,
        dst_crs=dst_crs,
        resampling=Resampling.bilinear,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    return Dem(out, transform, dst_crs)


def resample_to_grid(dem: Dem, transform: Affine, shape: tuple[int, int], crs: str) -> Dem:
    """Resample (bilinear) onto an exact target grid. Cells the source doesn't cover are NaN."""
    out = np.full(shape, np.nan, dtype="float64")
    reproject(
        source=dem.elevation,
        destination=out,
        src_transform=dem.transform,
        src_crs=dem.crs,
        dst_transform=transform,
        dst_crs=crs,
        resampling=Resampling.bilinear,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    return Dem(out, transform, crs)


def grid_for_bounds(bounds: tuple[float, float, float, float], res: float) -> tuple[Affine, tuple[int, int]]:
    """A north-up grid covering (minx, miny, maxx, maxy) at `res`, snapped to whole cells."""
    minx, miny, maxx, maxy = bounds
    minx, miny = np.floor(minx / res) * res, np.floor(miny / res) * res
    maxx, maxy = np.ceil(maxx / res) * res, np.ceil(maxy / res) * res
    cols, rows = int(round((maxx - minx) / res)), int(round((maxy - miny) / res))
    return Affine(res, 0, minx, 0, -res, maxy), (rows, cols)


def working_resolution(area_m2: float, source_res: float, max_cells: int = 1_500_000) -> float:
    """Finest resolution, no finer than the source, that keeps the grid under `max_cells`."""
    min_res = float(np.sqrt(area_m2 / max_cells))
    return max(source_res, min_res, 0.5)


def crop_to_polygon(dem: Dem, polygon: Polygon, buffer_m: float = 0.0) -> Dem:
    """Crop to the polygon's bounding box (plus buffer). Cells outside stay valid; use `polygon_mask` to mask."""
    minx, miny, maxx, maxy = polygon.buffer(buffer_m).bounds
    r0, c0 = dem.rowcol(np.array([minx]), np.array([maxy]))
    r1, c1 = dem.rowcol(np.array([maxx]), np.array([miny]))
    r0 = max(int(np.floor(r0[0])), 0)
    c0 = max(int(np.floor(c0[0])), 0)
    r1 = min(int(np.ceil(r1[0])) + 1, dem.shape[0])
    c1 = min(int(np.ceil(c1[0])) + 1, dem.shape[1])
    if r1 <= r0 or c1 <= c0:
        raise ValueError("Polygon does not overlap the DEM")
    sub = dem.elevation[r0:r1, c0:c1].copy()
    t = dem.transform * Affine.translation(c0, r0)
    return Dem(sub, t, dem.crs)


def polygon_mask(dem: Dem, polygon: Polygon) -> np.ndarray:
    """True for cells whose centre is inside the polygon."""
    return geometry_mask([mapping(polygon)], out_shape=dem.shape, transform=dem.transform, invert=True)
