"""Tests for the neighbourhood helpers in radar.area."""

import math

import numpy as np
import pytest

from custom_components.dwd_precipitation.radar.area import (
    area_max,
    compass,
    disk_offsets,
    nearest_class,
    nearest_rain,
)


def _grid(fill=0.0, shape=(40, 40)):
    return np.full(shape, fill, dtype=np.float32)


def test_disk_offsets_near_radius_is_own_cell_plus_eight_neighbours():
    drow, dcol, dist = disk_offsets(1.5)
    assert len(drow) == 9
    assert dist[0] == 0
    assert dist.max() == pytest.approx(math.sqrt(2))


def test_disk_offsets_are_sorted_by_distance():
    _drow, _dcol, dist = disk_offsets(5.0)
    assert np.all(np.diff(dist) >= 0)
    assert dist.max() <= 5.0


def test_area_max_sees_rain_on_a_neighbour_cell():
    g = _grid()
    g[19, 21] = 0.2  # diagonal neighbour of (20, 20)
    assert area_max(g, 20, 20, 1.5) == pytest.approx(0.2)
    # Two cells away is outside the near radius.
    g2 = _grid()
    g2[20, 22] = 0.2
    assert area_max(g2, 20, 20, 1.5) == pytest.approx(0.0)


def test_area_max_ignores_nodata_and_returns_none_when_all_nodata():
    g = _grid(np.nan)
    assert area_max(g, 20, 20) is None
    g[20, 21] = 0.1
    assert area_max(g, 20, 20) == pytest.approx(0.1)


def test_area_max_clips_at_grid_edge():
    g = _grid()
    g[0, 0] = 1.0
    assert area_max(g, 0, 0) == pytest.approx(1.0)


def test_nearest_rain_distance_and_bearing():
    g = _grid()
    g[17, 20] = 0.5   # 3 km north
    g[20, 16] = 0.5   # 4 km west
    assert nearest_rain(g, 20, 20, 0.0) == (3.0, 0)
    g[20, 22] = 0.5   # 2 km east
    assert nearest_rain(g, 20, 20, 0.0) == (2.0, 90)


def test_nearest_rain_threshold_and_scan_radius():
    g = _grid()
    g[20, 23] = 0.01  # below threshold
    g[20, 27] = 1.0   # 7 km east, outside 5 km
    assert nearest_rain(g, 20, 20, 0.02) is None
    assert nearest_rain(g, 20, 20, 0.02, radius_km=8) == (7.0, 90)


def test_nearest_rain_on_own_cell():
    g = _grid()
    g[20, 20] = 1.0
    assert nearest_rain(g, 20, 20, 0.0) == (0.0, None)


@pytest.mark.parametrize(
    ("bearing", "expected"),
    [(0, "N"), (44, "NE"), (90, "E"), (135, "SE"), (180, "S"), (225, "SW"),
     (270, "W"), (315, "NW"), (359, "N"), (None, None)],
)
def test_compass(bearing, expected):
    assert compass(bearing) == expected


def test_nearest_class_finds_closest_matching_value():
    g = np.zeros((20, 20), dtype=np.uint8)
    g[10, 13] = 7   # snow, 3 km east
    g[8, 10] = 3    # rain, 2 km north
    g[10, 11] = 1   # not classified, ignored
    assert nearest_class(g, 10, 10, range(2, 11)) == 3
    assert nearest_class(np.zeros((20, 20), dtype=np.uint8), 10, 10, range(2, 11)) is None
