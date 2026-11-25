"""radar/nearby.py: the precipitation around a location."""

from __future__ import annotations

import numpy as np

from radar.nearby import (
    area_max,
    closest_approach,
    coming_from,
    compass,
    nearest_above,
    nearest_class,
    nearest_class_by_sector,
    rain_track,
    upstream_max,
    upstream_nearest,
)

CELL = (1000.0, 1000.0)
PRECIP = range(2, 11)


def window(fill: int = 0, size: int = 11) -> np.ndarray:
    return np.full((size, size), fill, dtype=np.uint8)


def test_the_own_cell_wins() -> None:
    w = window()
    w[5, 5] = 7
    w[5, 6] = 3
    assert nearest_class(w, (5, 5), CELL, PRECIP, 5000) == 7


def test_the_nearest_wet_cell_is_reported() -> None:
    w = window()
    w[5, 9] = 3   # 4 km east
    w[3, 5] = 8   # 2 km north
    assert nearest_class(w, (5, 5), CELL, PRECIP, 5000) == 8


def test_cells_beyond_the_radius_and_dry_classes_are_ignored() -> None:
    w = window(fill=254)       # undetect everywhere
    w[0, 0] = 3                # about 7.1 km away
    w[5, 4] = 0                # no precipitation next door
    w[5, 6] = 1                # not classified next door
    assert nearest_class(w, (5, 5), CELL, PRECIP, 5000) is None


def test_a_clipped_window_off_centre() -> None:
    """At the grid's edge the location is not in the middle of its window."""
    w = window(size=6)
    w[0, 3] = 9
    assert nearest_class(w, (0, 0), CELL, PRECIP, 5000) == 9


# --- the rain around the location (amount windows, mm) -----------------------


def amounts(size: int = 11) -> np.ndarray:
    return np.zeros((size, size), dtype=np.float32)


def test_area_max_takes_the_wettest_cell_within_reach() -> None:
    w = amounts()
    w[4, 4] = 0.5   # diagonal neighbour, 1.41 km
    w[5, 7] = 2.0   # 2 km east: out of a 1.5 km reach
    assert area_max(w, (5, 5), CELL, 1500) == 0.5


def test_area_max_ignores_nodata_and_is_none_without_data() -> None:
    w = np.full((3, 3), np.nan, dtype=np.float32)
    assert area_max(w, (1, 1), CELL, 1500) is None
    w[0, 1] = 0.2
    assert area_max(w, (1, 1), CELL, 1500) == np.float32(0.2)


def test_nearest_above_gives_distance_and_bearing() -> None:
    w = amounts()
    w[5, 9] = 1.0   # 4 km east
    w[2, 5] = 1.0   # 3 km north
    w[5, 4] = 0.01  # 1 km west, below the threshold
    assert nearest_above(w, (5, 5), CELL, 0.025, 5000) == (3000.0, 0)
    w[2, 5] = 0.0
    assert nearest_above(w, (5, 5), CELL, 0.025, 5000) == (4000.0, 90)


def test_nearest_above_own_cell_has_no_bearing_and_none_when_dry() -> None:
    w = amounts()
    assert nearest_above(w, (5, 5), CELL, 0.025, 5000) is None
    w[5, 5] = 1.0
    assert nearest_above(w, (5, 5), CELL, 0.025, 5000) == (0.0, None)


def test_nearest_above_south_west() -> None:
    w = amounts()
    w[8, 2] = 1.0  # 3 km south, 3 km west
    distance, bearing = nearest_above(w, (5, 5), CELL, 0.025, 5000)
    assert round(distance) == 4243
    assert bearing == 225
    assert compass(bearing) == "SW"


def test_compass() -> None:
    assert compass(None) is None
    assert [compass(b) for b in (0, 22, 23, 90, 180, 270, 337, 338, 359)] == [
        "N", "N", "NE", "E", "S", "W", "NW", "N", "N",
    ]


def frames(path: list[tuple[int, int]], size: int = 21) -> list:
    """A 1 mm cell moving along ``path`` (row, col), one point per 5 minutes."""
    out = []
    for i, (row, col) in enumerate(path):
        w = amounts(size)
        w[row, col] = 1.0
        out.append((5 * i, w, (size // 2, size // 2), CELL))
    return out


def test_rain_track_fits_position_and_velocity() -> None:
    # From 8 km west towards the location (10, 10), 1 km per 5 minutes.
    track = rain_track(frames([(10, 2), (10, 3), (10, 4)]), 0.025, 10000)
    assert track is not None
    (y, x), (vy, vx) = track
    assert (round(y), round(x)) == (0, -8000)
    assert (round(vy), round(vx)) == (0, 200)


def test_rain_track_needs_two_steps_with_rain() -> None:
    assert rain_track(frames([(10, 2)]), 0.025, 10000) is None
    assert rain_track(frames([(10, 2), (10, 3)]), 5.0, 10000) is None


def test_closest_approach_head_on() -> None:
    distance, minutes = closest_approach((0.0, -8000.0), (0.0, 200.0))
    assert (distance, minutes) == (0.0, 40.0)


def test_closest_approach_passing_by() -> None:
    # 3 km north of the location, moving east: closest in 40 minutes, 3 km off.
    distance, minutes = closest_approach((-3000.0, -8000.0), (0.0, 200.0))
    assert (distance, minutes) == (3000.0, 40.0)


def test_closest_approach_moving_away_and_standing_still() -> None:
    _, minutes = closest_approach((0.0, 4000.0), (0.0, 200.0))
    assert minutes < 0
    assert closest_approach((0.0, 4000.0), (0.0, 0.0)) == (4000.0, 0.0)


def test_upstream_max_reads_only_the_side_the_rain_comes_from() -> None:
    w = np.zeros((11, 11), dtype=np.float32)
    w[5, 4] = 0.3  # west neighbour
    w[5, 6] = 0.9  # east neighbour
    w[4, 4] = 0.4  # north-west neighbour
    # Rain from the west: own cell, NW, W and SW count, E does not.
    assert upstream_max(w, (5, 5), CELL, 1500, 270) == np.float32(0.4)
    # From the east: only the east neighbour is wet.
    assert upstream_max(w, (5, 5), CELL, 1500, 90) == np.float32(0.9)
    # From the south: the own cell and S, SE, SW are dry.
    assert upstream_max(w, (5, 5), CELL, 1500, 180) == 0.0


def test_coming_from_is_opposite_to_the_motion() -> None:
    assert coming_from((0.0, 100.0)) == 270  # moving east comes from the west
    assert coming_from((100.0, 0.0)) == 0  # moving south comes from the north
    assert coming_from((0.0, 0.0)) is None


def test_nearest_class_by_sector_and_upstream_nearest() -> None:
    w = np.zeros((11, 11), dtype=np.int16)
    w[5, 5] = 4  # own cell: in no sector
    w[5, 2] = 7  # 3 km west
    w[5, 9] = 5  # 4 km east
    w[3, 3] = 8  # NW, about 2.8 km
    sectors = nearest_class_by_sector(w, (5, 5), CELL, PRECIP, 5000)
    assert set(sectors) == {"W", "E", "NW"}
    assert sectors["W"] == (7, 3000.0)
    # From the west: W and NW (and SW) count; NW is nearer.
    assert upstream_nearest(sectors, 270) == 8
    # From the east: only E.
    assert upstream_nearest(sectors, 90) == 5
    # From the south: nothing there.
    assert upstream_nearest(sectors, 180) is None
    # A stored copy holds lists and labels.
    assert upstream_nearest({"S": ["snow", 2.0]}, 200) == "snow"
