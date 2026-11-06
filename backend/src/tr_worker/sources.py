"""Turn each kind of survey into an elevation raster (`tr_geo.Dem`).

- lidar: LAS/LAZ point cloud → bare-earth DTM with PDAL (CLI, present in the worker image)
- dem: GeoTIFF as uploaded
- contours: GeoJSON lines with an elevation property → TIN-interpolated grid
- public_dem: USGS 3DEP, best available resolution, via py3dep (needs network access to USGS)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.interpolate import griddata
from shapely.geometry import MultiPoint, Polygon, shape

from tr_geo import Dem, project_geometry, read_geotiff
from tr_geo.dem import grid_for_bounds

ELEVATION_KEYS = ("elevation_m", "elevation", "elev", "ELEV", "Elevation", "z", "Z", "contour", "CONTOUR")


@dataclass
class Source:
    kind: str
    dem: Dem
    resolution_m: float


def lidar_to_dtm(las_path: str, out_tif: str, resolution_m: float = 0.5) -> Source:
    """Denoise, classify ground with SMRF, and grid ground returns (IDW) into a DTM GeoTIFF."""
    if shutil.which("pdal") is None:
        raise RuntimeError("PDAL is not installed in this environment; LiDAR processing runs in the worker image")
    pipeline = {
        "pipeline": [
            las_path,
            {"type": "filters.outlier", "method": "statistical", "mean_k": 8, "multiplier": 3.0},
            {"type": "filters.range", "limits": "Classification![7:7]"},
            {"type": "filters.assign", "value": ["Classification = 0", "ReturnNumber = 1 WHERE ReturnNumber < 1",
                                                 "NumberOfReturns = 1 WHERE NumberOfReturns < 1"]},
            {"type": "filters.smrf"},
            {"type": "filters.range", "limits": "Classification[2:2]"},
            {"type": "writers.gdal", "filename": out_tif, "resolution": resolution_m, "output_type": "idw",
             "window_size": 6, "gdaldriver": "GTiff", "data_type": "float32", "nodata": -9999},
        ]
    }
    spec = Path(out_tif).with_suffix(".pipeline.json")
    spec.write_text(json.dumps(pipeline))
    result = subprocess.run(["pdal", "pipeline", str(spec)], capture_output=True, text=True, timeout=3600)
    if result.returncode != 0:
        raise RuntimeError(f"PDAL failed: {result.stderr.strip()[-500:]}")
    dem = read_geotiff(out_tif)
    return Source("lidar", dem, dem.res)


def geotiff(path: str) -> Source:
    dem = read_geotiff(path)
    if "4326" in dem.crs:  # geographic: approximate metres per pixel at the raster's latitude
        lat = dem.transform.f + dem.shape[0] * dem.transform.e / 2
        res_m = dem.res * 111_320 * np.cos(np.radians(lat))
    else:
        res_m = dem.res
    return Source("dem", dem, float(res_m))


def contours_to_dem(geojson_path: str, crs: str, resolution_m: float = 1.0) -> Source:
    """Linear (TIN) interpolation between digitised contour vertices. GeoJSON is read as EPSG:4326."""
    data = json.loads(Path(geojson_path).read_text())
    features = data["features"] if data.get("type") == "FeatureCollection" else [data]
    xs, ys, zs = [], [], []
    for f in features:
        props = f.get("properties") or {}
        z = next((props[k] for k in ELEVATION_KEYS if k in props and props[k] is not None), None)
        if z is None:
            continue
        geom = project_geometry(shape(f["geometry"]), "EPSG:4326", crs)
        lines = getattr(geom, "geoms", [geom])
        for line in lines:
            dense = line.segmentize(resolution_m)
            coords = np.asarray(dense.coords)
            xs.extend(coords[:, 0])
            ys.extend(coords[:, 1])
            zs.extend([float(z)] * len(coords))
    if len(zs) < 10:
        raise ValueError("The contour file has no lines with an elevation property " f"(looked for {ELEVATION_KEYS[:4]}…)")
    pts = np.column_stack([xs, ys])
    hull = MultiPoint(pts).convex_hull
    transform, (rows, cols) = grid_for_bounds(hull.bounds, resolution_m)
    gx = transform.c + (np.arange(cols) + 0.5) * resolution_m
    gy = transform.f - (np.arange(rows) + 0.5) * resolution_m
    mx, my = np.meshgrid(gx, gy)
    grid = griddata(pts, np.asarray(zs), (mx, my), method="linear")
    return Source("contours", Dem(grid, transform, crs), resolution_m)


def fetch_3dep(boundary_lnglat: Polygon, out_tif: str) -> Source:
    """Best available USGS 3DEP DEM for the area (1 m where it exists, else 3/10/30 m)."""
    import py3dep  # optional dependency: pip install .[public-data]

    area = boundary_lnglat.buffer(0.002)
    available = {}
    try:
        available = py3dep.check_3dep_availability(area.bounds)
    except Exception:
        pass
    for res in (1, 3, 10, 30):
        if available and not available.get(f"{res}m", False):
            continue
        try:
            da = py3dep.get_dem(area, res, crs=4326)
            da.rio.to_raster(out_tif)
            dem = read_geotiff(out_tif)
            return Source("public_dem", dem, float(res))
        except Exception:
            continue
    raise RuntimeError("Could not fetch USGS 3DEP elevation for this area (outside the US, or the service is unreachable)")
