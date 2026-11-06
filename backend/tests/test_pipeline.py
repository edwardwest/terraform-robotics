import numpy as np
from shapely.geometry import LineString

from tr_geo import Params, analyze, grade_for
from tr_geo.terrain import contours, sample_line, slope_percent
from tr_geo.pipeline import compass_direction


def test_analyze_finds_two_valleys_and_keypoints_at_the_break(terrain, boundary):
    result = analyze(terrain, boundary, Params(valley_threshold_fraction=0.03, min_valley_threshold_m2=2000))
    s = result.summary
    assert s["main_valley_count"] == 2
    assert s["outlet_direction"] in {"S", "SE", "SW"}
    kps = result.layers["keypoints"]
    assert len(kps) == 2
    rows = terrain.shape[0]
    for geom, props in kps:
        r, c = terrain.rowcol(np.array([geom.x]), np.array([geom.y]))
        assert abs(r[0] - 170) < 10, f"keypoint {props['id']} at row {r[0]:.0f}, expected near 170"
        assert min(abs(c[0] - 100), abs(c[0] - 225)) < 15
        assert props["gradient_above_pct"] > props["gradient_below_pct"]
    for layer in ("contours", "flow", "valleys", "ridges"):
        assert result.layers[layer], f"{layer} layer is empty"
        for geom, _ in result.layers[layer]:
            assert boundary.buffer(1e-6).covers(geom)


def test_contours_interval_and_index(terrain):
    lines = contours(terrain, interval=2.0)
    levels = sorted({lvl for _, lvl, _ in lines})
    assert np.allclose(np.diff(levels), 2.0)
    assert any(idx for _, lvl, idx in lines if lvl % 10 == 0)


def test_profile_and_slope(terrain):
    x0 = terrain.transform.c + 50
    y0 = terrain.transform.f - 20
    d, z = sample_line(terrain, LineString([(x0, y0), (x0, y0 - 100)]), samples=50)
    assert d[-1] == 100 and z[0] > z[-1]
    assert 15 < np.nanmedian(slope_percent(terrain)[:100]) < 30


def test_grades_and_compass():
    assert grade_for(0.5, "lidar") == "design"
    assert grade_for(1.0, "public_dem") == "planning"
    assert grade_for(30, "public_dem") == "coarse"
    assert compass_direction(-1, -1) == "SW"
    assert compass_direction(0, 1) == "N"
