import numpy as np

from tr_geo import hydrology


def test_fill_removes_pits_and_drains_everything():
    z = np.full((20, 20), 10.0)
    z[:, :] -= np.arange(20)[:, None] * 0.1  # slopes south
    z[8:11, 8:11] = 5.0  # a pit
    filled = hydrology.fill_depressions(z)
    assert np.all(filled >= z)
    ds = hydrology.d8_downstream(filled)
    # every cell must reach an edge (-1) without cycles
    for start in range(z.size):
        cur, steps = start, 0
        while ds[cur] >= 0:
            cur = ds[cur]
            steps += 1
            assert steps < z.size


def test_accumulation_counts_all_cells_once_at_outlets():
    z = np.add.outer(np.arange(15, 0, -1.0), np.zeros(12))  # plane draining south
    filled = hydrology.fill_depressions(z)
    ds = hydrology.d8_downstream(filled)
    acc = hydrology.flow_accumulation(filled, ds)
    outlets = ds == -1
    assert np.isclose(acc.reshape(-1)[outlets].sum(), z.size)


def test_trace_channels_finds_valley(terrain):
    filled = hydrology.fill_depressions(terrain.elevation)
    ds = hydrology.d8_downstream(filled)
    acc = hydrology.flow_accumulation(filled, ds)
    channels = hydrology.trace_channels(acc, ds, threshold=3000)
    assert channels
    long_channels = [ch for ch in channels if len(ch.cells) > 100]
    medians = sorted(np.median([c % terrain.shape[1] for c in ch.cells]) for ch in long_channels)
    assert len(medians) == 2
    assert abs(medians[0] - 100) < 5 and abs(medians[1] - 225) < 5
