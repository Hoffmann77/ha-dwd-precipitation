"""The 5x5 windows, on the grid the RV fixture describes."""

from __future__ import annotations

import math

import numpy as np

from tests.factories.real import real_cells

from scripts.precip_eval.stations import Station
from scripts.precip_eval.windows import (
    CELL_COLUMNS,
    RADIUS,
    cut_windows,
    grid_description,
    station_cell,
    station_cells,
)


def test_station_lands_on_the_cell_the_integration_reads(rv_member, wet_station):
    grid, _, _ = rv_member
    pinned = real_cells("rv")["wet"]

    cell = station_cell(grid, wet_station)

    assert cell is not None
    assert (cell.row, cell.col) == (pinned["row"], pinned["col"])
    # The pinned lat/lon is the cell's centre.
    assert math.isclose(cell.frac_x, 0.5, abs_tol=1e-6)
    assert math.isclose(cell.frac_y, 0.5, abs_tol=1e-6)


def test_position_inside_the_cell_follows_the_station(rv_member, wet_station):
    grid, _, _ = rv_member
    centre = station_cell(grid, wet_station)
    # ~200 m east and ~200 m north of the centre stay in the same cell.
    moved = Station(2, "Moved", wet_station.lat + 0.0018, wet_station.lon + 0.0029, 0.0, "Test")

    cell = station_cell(grid, moved)

    assert (cell.row, cell.col) == (centre.row, centre.col)
    assert 0.6 < cell.frac_x < 0.8
    assert 0.6 < cell.frac_y < 0.8


def test_window_is_the_grid_around_the_cell_in_thousandths(rv_member, wet_station):
    grid, values, _ = rv_member
    cell = station_cell(grid, wet_station)

    window = cut_windows(values, [cell])[0]

    expected = values[
        cell.row - RADIUS : cell.row + RADIUS + 1, cell.col - RADIUS : cell.col + RADIUS + 1
    ].astype(np.float64)
    assert window.shape == (len(CELL_COLUMNS),)
    np.testing.assert_array_equal(window, np.rint(expected.ravel() * 1000))
    # c22 is the station's own cell: the value the integration reports.
    assert window[CELL_COLUMNS.index("c22")] == round(real_cells("rv")["wet"]["value"] * 1000)


def test_stations_off_the_grid_or_at_its_edge_are_left_out(rv_member):
    grid, _, _ = rv_member
    nodata = real_cells("rv")["nodata"]  # cell (0, 0): the grid's corner
    stations = [
        Station(1, "Corner", nodata["lat"], nodata["lon"], 0.0, "Test"),
        Station(2, "Atlantic", 40.0, -20.0, 0.0, "Test"),
    ]

    assert station_cells(grid, stations) == []


def test_grid_description_is_stable(rv_member):
    grid, _, _ = rv_member

    assert grid_description(grid) == grid_description(grid)
    assert '"xsize": 1100' in grid_description(grid)
