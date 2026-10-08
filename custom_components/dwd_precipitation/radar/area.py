"""Neighbourhood helpers: evaluate the radar cells around the location.

A single 1x1 km cell is a noisy point sample: a shower passing a few hundred
metres away is missed, and one speckled cell raises a false alarm. These
helpers look at a small disk of cells around the location instead:

* :func:`area_max` — the wettest cell within a short radius (default 1.5 km,
  i.e. the location's cell and its eight neighbours). Fed through the usual
  start/end detection, this turns "rain on my cell" into "rain within ~1 km".
* :func:`nearest_rain` — distance and compass bearing of the closest cell above
  a threshold within a wider scan radius (default 5 km).

The RS/RV composites use a 1 km polar-stereographic grid with row 0 at the top
(north) and columns increasing eastwards, so a cell offset (drow, dcol) maps to
(-drow km north, dcol km east). Grid north deviates from true north by a few
degrees away from the projection's central meridian (10° E), which is well
within the precision of an 8-point compass direction.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

# Grid spacing of the RS/RV/HymecNG composites.
CELL_KM = 1.0

DEFAULT_NEAR_RADIUS_KM = 1.5
DEFAULT_SCAN_RADIUS_KM = 5.0

COMPASS_8 = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@lru_cache(maxsize=8)
def disk_offsets(radius_km: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (drow, dcol, distance_km) for every cell within ``radius_km``.

    Sorted by distance so the first match of a mask is the nearest cell.
    """
    r = math.floor(radius_km / CELL_KM)
    drow, dcol = np.mgrid[-r:r + 1, -r:r + 1]
    dist = np.hypot(drow, dcol) * CELL_KM
    keep = dist <= radius_km + 1e-9
    drow, dcol, dist = drow[keep], dcol[keep], dist[keep]
    order = np.argsort(dist, kind="stable")
    return drow[order], dcol[order], dist[order]


def _window(
    grid: np.ndarray, row: int, col: int, radius_km: float
) -> tuple[np.ndarray, np.ndarray, tuple[np.ndarray, np.ndarray]]:
    """Return the in-grid cell values within the disk, their distances and offsets."""
    drow, dcol, dist = disk_offsets(radius_km)
    rows = row + drow
    cols = col + dcol
    inside = (rows >= 0) & (rows < grid.shape[0]) & (cols >= 0) & (cols < grid.shape[1])
    return grid[rows[inside], cols[inside]], dist[inside], (drow[inside], dcol[inside])


def area_max(
    grid: np.ndarray, row: int, col: int, radius_km: float = DEFAULT_NEAR_RADIUS_KM
) -> float | None:
    """Return the largest value within ``radius_km`` of (row, col).

    NaN (nodata) cells are ignored; ``None`` when every cell is nodata.
    """
    values, _dist, _off = _window(grid, row, col, radius_km)
    values = values[~np.isnan(values)]
    if values.size == 0:
        return None
    return float(values.max())


def bearing_deg(drow: int, dcol: int) -> float:
    """Compass bearing (0 = north, 90 = east) of a cell offset from the centre."""
    return math.degrees(math.atan2(dcol, -drow)) % 360.0


def compass(bearing: float | None) -> str | None:
    """Return the 8-point compass direction for a bearing in degrees."""
    if bearing is None:
        return None
    return COMPASS_8[int(((bearing % 360.0) + 22.5) // 45.0) % 8]


def nearest_rain(
    grid: np.ndarray,
    row: int,
    col: int,
    threshold: float,
    radius_km: float = DEFAULT_SCAN_RADIUS_KM,
) -> tuple[float, float | None] | None:
    """Return (distance_km, bearing_deg) of the nearest cell above ``threshold``.

    The location's own cell yields distance 0 and bearing ``None``. Returns
    ``None`` when no cell within ``radius_km`` exceeds the threshold.
    """
    values, dist, (drow, dcol) = _window(grid, row, col, radius_km)
    wet = np.flatnonzero(np.nan_to_num(values, nan=-1.0) > threshold)
    if wet.size == 0:
        return None
    i = int(wet[0])  # offsets are sorted by distance
    if dist[i] == 0:
        return 0.0, None
    return round(float(dist[i]), 1), round(bearing_deg(int(drow[i]), int(dcol[i])))
