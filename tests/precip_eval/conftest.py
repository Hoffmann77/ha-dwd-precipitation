"""Shared fixtures for the evaluation service's tests (HA-free, no network)."""

from __future__ import annotations

import pytest

from radar.odim import read_odim_composite, read_odim_grid
from tests.factories.real import FIXTURES, real_cells

from scripts.precip_eval.stations import Station

RV_FIXTURE = FIXTURES / "composite_rv_sample.hd5"


@pytest.fixture(scope="session")
def rv_member():
    """The RV fixture's analysis member: (grid, values in mm, raw bytes)."""
    values, _ = read_odim_composite(RV_FIXTURE)
    return read_odim_grid(RV_FIXTURE), values, RV_FIXTURE.read_bytes()


@pytest.fixture
def wet_station() -> Station:
    """A station at the centre of the fixture's pinned wet cell."""
    cell = real_cells("rv")["wet"]
    return Station(1, "Wet", cell["lat"], cell["lon"], 100.0, "Test")


@pytest.fixture
def city_stations() -> list[Station]:
    """A few stations across Germany, wet or dry as the fixture has it."""
    return [
        Station(10, "Berlin", 52.52, 13.40, 34.0, "Berlin"),
        Station(11, "Muenchen", 48.14, 11.58, 519.0, "Bayern"),
        Station(12, "Hamburg", 53.55, 9.99, 6.0, "Hamburg"),
        Station(13, "Koeln", 50.94, 6.96, 53.0, "Nordrhein-Westfalen"),
        Station(14, "Aachen", 50.78, 6.08, 173.0, "Nordrhein-Westfalen"),
    ]
