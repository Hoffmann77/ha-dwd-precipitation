"""Unit tests for radar/georef.py RADOLAN grid — no HA, no GDAL, no network.

Exercises the vendored trigonometric projection, which is the path production
uses (get_radolan_grid falls back to crs="trig" when GDAL/osr is unavailable).
"""

import pytest

from radar import get_radolan_grid


def test_grid_shape():
    grid = get_radolan_grid()
    assert grid.shape == (900, 900, 2)


def test_trig_lower_left_corner():
    """Vendored trig projection, lower-left pixel (km) — matches wradlib's doctest."""
    grid = get_radolan_grid(crs="trig")
    assert grid[0, 0, 0] == pytest.approx(-523.4622, abs=1e-3)
    assert grid[0, 0, 1] == pytest.approx(-4658.6447, abs=1e-3)


def test_wgs84_corner_within_germany():
    """WGS84 lower-left corner (~3.59E, 46.95N) via the trig inverse."""
    grid = get_radolan_grid(wgs84=True, crs="trig")
    lon, lat = float(grid[0, 0, 0]), float(grid[0, 0, 1])
    assert 3.0 <= lon <= 7.0
    assert 45.0 <= lat <= 48.0
