"""Keyline, pattern and swale geometry on synthetic two-valley terrain."""

import numpy as np
import pytest
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import unary_union

from tr_geo import analyze
from tr_geo.design import (
    DEFAULT_GRADE,
    Surface,
    check_rip,
    graded_pattern,
    keyline_stops,
    keyline_through,
    line_metrics,
    parallel_pattern,
    swale_metrics,
    swale_on_contour,
    valley_near,
)


@pytest.fixture(scope="module")
def site():
    from conftest import two_valley_terrain, ORIGIN_X, ORIGIN_Y
    from shapely.geometry import box

    dem = two_valley_terrain()
    rows, cols = dem.shape
    boundary = box(ORIGIN_X + 15, ORIGIN_Y - rows + 15, ORIGIN_X + cols - 15, ORIGIN_Y - 15)
    result = analyze(dem, boundary)
    ridges = unary_union([g for g, _ in result.layers["ridges"]])
    valleys = [g for g, _ in result.layers["valleys"]]
    kp = result.layers["keypoints"][0][0]
    return dem, boundary, ridges, valleys, kp


def test_keyline_holds_grade_and_falls_toward_ridges(site):
    dem, boundary, ridges, valleys, kp = site
    surface = Surface(dem)
    stops = keyline_stops(ridges, valleys, kp)
    line, arms = keyline_through(surface, (kp.x, kp.y), DEFAULT_GRADE, stops=stops, within=boundary)
    assert line.length > 60
    z0 = surface.z1(kp.x, kp.y)
    for arm in arms:
        pts = np.array(arm.points)
        z = surface.z(pts[:, 0], pts[:, 1])
        s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
        # every traced point sits on the target fall within a few centimetres
        target = z0 - DEFAULT_GRADE * s
        assert np.nanmax(np.abs(z[: len(target) - 1] - target[:-1])) < 0.05
        # each arm ends lower than the keypoint: water drifts out of the valley
        assert z[-1] < z0
        assert arm.stop in {"ridge", "boundary"}
    # the arms leave the valley on opposite sides (contours across a valley form a V pointing upstream,
    # so on this gentle slope they also swing downstream)
    (x0, _), (x1, _) = line.coords[0], line.coords[-1]
    assert min(x0, x1) < kp.x - 40 and max(x0, x1) > kp.x + 40


def test_parallel_pattern_whole_site_and_valley(site):
    dem, boundary, ridges, valleys, kp = site
    surface = Surface(dem)
    line, _ = keyline_through(surface, (kp.x, kp.y), stops=keyline_stops(ridges, valleys, kp), within=boundary)
    whole = parallel_pattern(surface, line, 10.0, boundary)
    assert len(whole) > 10
    assert all(boundary.buffer(0.01).contains(p.geom) for p in whole)
    assert {p.props["position"] for p in whole} == {"above", "below"}
    valley = valley_near(valleys, kp)
    assert valley is not None
    in_valley = parallel_pattern(surface, line, 10.0, boundary, valley=valley, ridges=ridges)
    assert 0 < len(in_valley) <= len(whole)
    assert all(p.geom.intersects(valley.buffer(5)) for p in in_valley)
    total_whole = sum(p.geom.length for p in whole)
    total_valley = sum(p.geom.length for p in in_valley)
    assert total_valley < total_whole


def test_graded_pattern_lines_each_hold_grade(site):
    dem, boundary, ridges, valleys, kp = site
    surface = Surface(dem)
    valley = valley_near(valleys, kp)
    lines, truncated = graded_pattern(surface, valley, (kp.x, kp.y), 15.0, DEFAULT_GRADE, boundary, stops=keyline_stops(ridges, valleys, kp, hole_m=1e6), max_lines=8)
    assert len(lines) >= 4
    for pl in lines:
        m = line_metrics(surface, pl.geom, valley)
        assert m["fall_to_ridges_min"] is not None and m["fall_to_ridges_min"] > -0.0005
        assert check_rip(m) == [] or all("scour" in n for n in check_rip(m))


def test_line_metrics_flags_water_toward_valley(site):
    dem, *_ = site
    surface = Surface(dem)
    from conftest import ORIGIN_X, ORIGIN_Y

    # straight east-west line above the gentle zone: across a valley it dips, so water runs toward the valley
    line = LineString([(ORIGIN_X + 60, ORIGIN_Y - 100), (ORIGIN_X + 140, ORIGIN_Y - 100)])
    valley_line = LineString([(ORIGIN_X + 100, ORIGIN_Y - 20), (ORIGIN_X + 100, ORIGIN_Y - 340)])
    m = line_metrics(surface, line, valley_line)
    assert m["fall_to_ridges_min"] < 0
    assert any("toward the valley" in n for n in check_rip(m))


def test_swale_is_level_and_sized(site):
    dem, boundary, ridges, valleys, kp = site
    surface = Surface(dem)
    from conftest import ORIGIN_X, ORIGIN_Y

    start = (ORIGIN_X + 40, ORIGIN_Y - 250)
    end = (ORIGIN_X + 150, ORIGIN_Y - 250)
    sw = swale_on_contour(surface, start, end)
    d, z = surface.profile(sw.geom)
    assert np.nanmax(np.abs(z - sw.elevation_m)) < 0.05  # dead level
    assert sw.geom.length > 90
    m, notes = swale_metrics(surface, sw, width_m=2.0, depth_m=0.5, boundary=boundary)
    assert m["cut_volume_m3"] == pytest.approx(m["length_m"] * (2 / 3) * 2.0 * 0.5, rel=0.01)
    assert m["catchment_m2"] > 1000  # the slope above it drains onto it
    assert m["terrain_slope_max_pct"] < 15 or notes


def test_untraceable_keyline_is_a_clean_error(site):
    dem, boundary, ridges, valleys, kp = site
    surface = Surface(dem)
    from shapely.geometry import Point as P

    outside = P(boundary.bounds[0] - 5, boundary.bounds[1] + 50)
    with pytest.raises(ValueError):
        keyline_through(surface, (outside.x, outside.y), within=boundary)
    with pytest.raises(ValueError):  # grade far steeper than the ground: no crossing on either side
        keyline_through(surface, (kp.x, kp.y), 0.5, within=boundary)


def test_swale_on_closed_contour_runs_start_to_end():
    from affine import Affine

    from tr_geo.dem import Dem

    n = 200
    r, c = np.mgrid[0:n, 0:n].astype(float)
    z = 100 - 0.15 * np.hypot(r - n / 2, c - n / 2)  # a cone: every contour is a closed ring
    dem = Dem(z, Affine(1, 0, 0, 0, -1, n), "EPSG:32610")
    surface = Surface(dem, smooth_m=0)
    rng = np.random.default_rng(1)
    for _ in range(40):
        a0, a1 = rng.uniform(0, 2 * np.pi, 2)
        rad = 60
        start = (n / 2 + rad * np.cos(a0), n / 2 + rad * np.sin(a0))
        end = (n / 2 + rad * np.cos(a1), n / 2 + rad * np.sin(a1))
        try:
            sw = swale_on_contour(surface, start, end)
        except ValueError:
            continue
        s0, s1 = sw.geom.coords[0], sw.geom.coords[-1]
        assert np.hypot(s0[0] - start[0], s0[1] - start[1]) < np.hypot(s1[0] - start[0], s1[1] - start[1])
