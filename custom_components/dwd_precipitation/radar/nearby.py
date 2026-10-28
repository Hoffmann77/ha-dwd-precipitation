"""The precipitation around a location, from a window of radar cells.

A single 1 km cell is a noisy point sample: a shower passing a few hundred
metres away is missed. The neighbourhood evaluation (the option of that name)
looks at the cells around the location instead: the wettest cell within a
short radius (area_max), the distance and direction of the nearest rain
within a wider one (nearest_above), and where the rain around it is heading
(rain_track, closest_approach), so that rain passing by is told apart from
rain coming towards the location. Grid rows run from north to south and
columns from west to east, so a cell's offset gives its bearing; grid north
is within a few degrees of true north, well within an 8-point compass.

HymecNG measures the type only where it already rains, so for rain that is
still on its way the own cell says nothing. The nearest cell around it that
holds precipitation is the best estimate of what is coming: an estimate, kept
apart from the measured type of the rain events (ADR 0012) and shown only as
the rain warning's ``expected_type``.

Pure and HA-free, like everything in radar/.

"""

from __future__ import annotations

from collections.abc import Iterable

import math

import numpy as np

COMPASS_8 = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def _distances(
    window: np.ndarray, center: tuple[int, int], cell_m: tuple[float, float]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return each cell's distance from ``center`` in metres, and its offset.

    The offsets are (rows south, columns east) in metres. Distances are
    measured between cell centres, so the own cell is at 0 m.

    """
    rows, cols = np.indices(window.shape)
    dy = (rows - center[0]) * cell_m[0]
    dx = (cols - center[1]) * cell_m[1]
    return np.hypot(dy, dx), dy, dx


def area_max(
    window: np.ndarray,
    center: tuple[int, int],
    cell_m: tuple[float, float],
    radius_m: float,
) -> float | None:
    """Return the largest value within ``radius_m`` of the location.

    For an amount window: the rain within reach, rather than on the own cell.
    NaN (no data) cells are ignored; None when every cell within reach is NaN.

    """
    dist, _, _ = _distances(window, center, cell_m)
    values = window[(dist <= radius_m) & ~np.isnan(window)]
    if values.size == 0:
        return None
    return float(values.max())


def nearest_above(
    window: np.ndarray,
    center: tuple[int, int],
    cell_m: tuple[float, float],
    threshold: float,
    radius_m: float,
) -> tuple[float, int | None] | None:
    """Return the distance (m) and bearing of the nearest cell above ``threshold``.

    The bearing is in whole degrees (0 north, 90 east), None for the own cell.
    None when no cell within ``radius_m`` is above the threshold.

    """
    dist, dy, dx = _distances(window, center, cell_m)
    hit = (dist <= radius_m) & (np.nan_to_num(window, nan=-np.inf) > threshold)
    if not hit.any():
        return None
    i = int(np.argmin(np.where(hit, dist, np.inf)))
    if dist.flat[i] == 0:
        return 0.0, None
    bearing = math.degrees(math.atan2(dx.flat[i], -dy.flat[i])) % 360.0
    return float(dist.flat[i]), round(bearing) % 360


def compass(bearing: float | None) -> str | None:
    """Return the 8-point compass direction (N, NE, ...) of a bearing in degrees."""
    if bearing is None:
        return None
    return COMPASS_8[int(((bearing % 360.0) + 22.5) // 45.0) % 8]


def nearest_class(
    window: np.ndarray,
    center: tuple[int, int],
    cell_m: tuple[float, float],
    classes: Iterable[int],
    radius_m: float,
) -> int | None:
    """Return the class of the nearest cell within ``radius_m`` that is in ``classes``.

    ``window`` holds class indices around the location, which sits at
    ``center`` (row, col); ``cell_m`` is the cell size (y, x) in metres.
    Distances are measured between cell centres, so the own cell is at 0 m.
    None when no such cell is within reach.

    """
    rows, cols = np.indices(window.shape)
    dist = np.hypot((rows - center[0]) * cell_m[0], (cols - center[1]) * cell_m[1])
    hit = (dist <= radius_m) & np.isin(window, list(classes))
    if not hit.any():
        return None
    return int(window.flat[int(np.argmin(np.where(hit, dist, np.inf)))])


def _centroid(
    window: np.ndarray,
    center: tuple[int, int],
    cell_m: tuple[float, float],
    threshold: float,
    radius_m: float,
) -> tuple[float, float] | None:
    """Return the amount-weighted centre of the rain within ``radius_m`` (m).

    As (south, east) offsets from the location; None without rain above
    ``threshold`` in reach.

    """
    dist, dy, dx = _distances(window, center, cell_m)
    wet = (dist <= radius_m) & (np.nan_to_num(window, nan=-np.inf) > threshold)
    if not wet.any():
        return None
    weight = window[wet]
    return float(np.average(dy[wet], weights=weight)), float(np.average(dx[wet], weights=weight))


def rain_track(
    frames: Iterable[tuple[int, np.ndarray, tuple[int, int], tuple[float, float]]],
    threshold: float,
    radius_m: float,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Return where the rain around the location is now and how it moves.

    ``frames`` are (lead in minutes, window, center, cell size) of successive
    forecast steps. The centre of the rain within ``radius_m`` (_centroid) is
    fitted with a straight line over the leads that have rain: its position
    at lead 0 and its velocity, both as (south, east) in metres and metres
    per minute. None with fewer than two such leads.

    """
    leads: list[int] = []
    points: list[tuple[float, float]] = []
    for lead, window, center, cell_m in frames:
        if (point := _centroid(window, center, cell_m, threshold, radius_m)) is not None:
            leads.append(lead)
            points.append(point)
    if len(leads) < 2:
        return None
    t = np.asarray(leads, dtype=float)
    yx = np.asarray(points)
    vy, y0 = np.polyfit(t, yx[:, 0], 1)
    vx, x0 = np.polyfit(t, yx[:, 1], 1)
    return (float(y0), float(x0)), (float(vy), float(vx))


def closest_approach(
    position: tuple[float, float], velocity: tuple[float, float]
) -> tuple[float, float]:
    """Return how close rain on this track comes to the location, and when.

    ``position`` (m) and ``velocity`` (m/min) as rain_track gives them. Returns
    the distance (m) at the closest point and the minutes until it; minutes of
    0 or less mean the rain is already moving away. Rain that does not move
    is at its closest now.

    """
    py, px = position
    vy, vx = velocity
    speed2 = vy * vy + vx * vx
    if speed2 == 0:
        return math.hypot(py, px), 0.0
    t = -(py * vy + px * vx) / speed2
    return math.hypot(py + vy * t, px + vx * t), t
