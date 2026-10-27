"""radar/nearby.py: the type of the nearest precipitation around a location."""

from __future__ import annotations

import numpy as np

from radar.nearby import nearest_class

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
