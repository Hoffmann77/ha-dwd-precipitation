"""The 5x5 window around each station, on the grid a radar file describes.

The station's cell is found on the file's own grid, as the integration does
(ADR 0010), and its window is cut out of the member read whole: one inflate
per member rather than one per station (docs/interpolation-evaluation.md,
"Reading the grid").

"""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from radar.grid import Grid, OutsideGrid

from .stations import Station

RADIUS = 2  # cells on each side of the station's cell
SIZE = 2 * RADIUS + 1

# The window's cells as database columns, row-major as the grid is stored:
# c00 is the north-west corner, c22 the station's own cell, c44 the
# south-east corner.
CELL_COLUMNS = tuple(f"c{r}{c}" for r in range(SIZE) for c in range(SIZE))

# Values are stored in thousandths of a mm, the resolution ODIM stores ACRR at
# (gain 0.001), so the integer round-trips the reader's value exactly.
SCALE = 1000


def grid_description(grid: Grid) -> str:
    """Return a grid as a canonical JSON string, the key it is stored under."""
    return json.dumps(dataclasses.asdict(grid), sort_keys=True)


@dataclass(frozen=True)
class StationCell:
    """A station's cell on one grid, and where in that cell the station is."""

    station_id: int
    row: int  # 0 = the grid's north edge, as stored
    col: int
    frac_x: float  # position inside the cell: 0 = west edge, 1 = east edge
    frac_y: float  # 0 = south edge, 1 = north edge


def station_cell(grid: Grid, station: Station) -> StationCell | None:
    """Return the station's cell on ``grid``, or None if its window does not fit.

    The cell is ``Grid.cell``'s, the one the integration reads; the position
    inside it is the same projected offset before flooring. A station off the
    grid, or so close to its edge that the 5x5 window would leave it, is not
    logged on this grid.

    """
    try:
        row, col = grid.cell(station.lat, station.lon)
    except OutsideGrid:
        return None
    if not (RADIUS <= row < grid.ysize - RADIUS and RADIUS <= col < grid.xsize - RADIUS):
        return None
    x, y = grid.projection.xy(station.lat, station.lon)
    fx = (x - grid.x_ll) / grid.xscale
    fy = (y - grid.y_ll) / grid.yscale
    return StationCell(station.station_id, row, col, fx - math.floor(fx), fy - math.floor(fy))


def station_cells(grid: Grid, stations: Iterable[Station]) -> list[StationCell]:
    """Return the cells of every station whose window fits on ``grid``."""
    return [cell for s in stations if (cell := station_cell(grid, s)) is not None]


def cut_windows(values: np.ndarray, cells: list[StationCell]) -> np.ndarray:
    """Return every station's window from one member, in thousandths of a mm.

    ``values`` is the member as read_odim_composite returns it (mm, NaN for
    no data). The result has one row per cell, in ``cells`` order, and the 25
    columns of CELL_COLUMNS; no data stays NaN.

    """
    rows = np.array([c.row for c in cells], dtype=np.intp)
    cols = np.array([c.col for c in cells], dtype=np.intp)
    offsets = np.arange(-RADIUS, RADIUS + 1)
    rr = rows[:, None, None] + offsets[None, :, None]
    cc = cols[:, None, None] + offsets[None, None, :]
    windows = values[rr, cc].astype(np.float64).reshape(len(cells), SIZE * SIZE)
    return np.rint(windows * SCALE)
