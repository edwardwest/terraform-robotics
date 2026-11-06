import json

import numpy as np
from shapely.geometry import box, mapping

from tr_geo import project_geometry
from tr_geo.terrain import contours
from tr_worker.sources import contours_to_dem


def test_contours_round_trip_to_dem(terrain, tmp_path):
    """Contours traced from a DEM rebuild a surface close to the original between the lines."""
    lines = contours(terrain, interval=1.0)
    features = []
    for line, level, _ in lines:
        ll = project_geometry(line, terrain.crs, "EPSG:4326")
        features.append({"type": "Feature", "geometry": mapping(ll), "properties": {"elevation": level}})
    path = tmp_path / "contours.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))

    src = contours_to_dem(str(path), terrain.crs, resolution_m=2.0)
    assert src.kind == "contours"
    dem = src.dem
    # compare at interior points
    rows, cols = terrain.shape
    x0, y0 = terrain.transform.c, terrain.transform.f
    xs = x0 + np.linspace(40, cols - 40, 15)
    ys = y0 - np.linspace(40, rows - 40, 15)
    gx, gy = np.meshgrid(xs, ys)
    r_t, c_t = terrain.rowcol(gx, gy)
    r_d, c_d = dem.rowcol(gx, gy)
    truth = terrain.elevation[np.round(r_t).astype(int), np.round(c_t).astype(int)]
    rebuilt = dem.elevation[np.round(r_d).astype(int), np.round(c_d).astype(int)]
    assert np.nanmax(np.abs(truth - rebuilt)) < 1.0  # within one contour interval
