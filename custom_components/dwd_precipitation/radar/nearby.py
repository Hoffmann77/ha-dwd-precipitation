"""The type of the precipitation nearest to a location, from a HymecNG window.

HymecNG measures the type only where it already rains, so for rain that is
still on its way the own cell says nothing. The nearest cell around it that
holds precipitation is the best estimate of what is coming: an estimate, kept
apart from the measured type of the rain events (ADR 0012) and shown only as
the rain warning's ``expected_type``.

Pure and HA-free, like everything in radar/.

"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np


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
