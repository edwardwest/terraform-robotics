"""Terrain derivatives: slope, aspect, hillshade, contours and line profiles."""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString
from skimage import measure

from .dem import Dem


def slope_percent(dem: Dem) -> np.ndarray:
    dz_dy, dz_dx = np.gradient(dem.elevation, dem.res)
    return np.hypot(dz_dx, dz_dy) * 100.0


def aspect_degrees(dem: Dem) -> np.ndarray:
    """Downslope direction, degrees clockwise from north."""
    dz_dy, dz_dx = np.gradient(dem.elevation, dem.res)
    # rows increase southward, so -dz_dy is the northward gradient
    return (np.degrees(np.arctan2(-dz_dx, dz_dy)) + 360.0) % 360.0


def hillshade(dem: Dem, azimuth: float = 315.0, altitude: float = 45.0) -> np.ndarray:
    dz_dy, dz_dx = np.gradient(dem.elevation, dem.res)
    slope = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(-dz_dx, dz_dy)
    az, alt = np.radians(azimuth), np.radians(altitude)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    return np.clip(shade, 0, 1)


def contour_levels(zmin: float, zmax: float, interval: float) -> np.ndarray:
    start = np.ceil(zmin / interval) * interval
    return np.arange(start, zmax, interval)


def contours(dem: Dem, interval: float, index_every: int = 5) -> list[tuple[LineString, float, bool]]:
    """Contour lines as (geometry in DEM CRS, elevation, is_index_contour)."""
    z = dem.elevation
    if np.all(np.isnan(z)):
        return []
    zmin, zmax = float(np.nanmin(z)), float(np.nanmax(z))
    filled = np.where(np.isnan(z), zmin - 10 * interval, z)  # keep lines from wrapping nodata edges
    out = []
    for level in contour_levels(zmin, zmax, interval):
        for coords in measure.find_contours(filled, level):
            if len(coords) < 2:
                continue
            x, y = dem.xy(coords[:, 0], coords[:, 1])
            line = LineString(np.column_stack([x, y]))
            if line.length < 2 * dem.res:
                continue
            k = int(round(level / interval))
            out.append((line, float(level), k % index_every == 0))
    return out


def sample_line(dem: Dem, line: LineString, samples: int = 200) -> tuple[np.ndarray, np.ndarray]:
    """Distances (m) and bilinearly interpolated elevations along a line in the DEM's CRS."""
    from scipy.ndimage import map_coordinates

    d = np.linspace(0, line.length, samples)
    pts = [line.interpolate(v) for v in d]
    x = np.array([p.x for p in pts])
    y = np.array([p.y for p in pts])
    r, c = dem.rowcol(x, y)
    z = map_coordinates(dem.elevation, [r, c], order=1, mode="nearest", cval=np.nan)
    return d, z
