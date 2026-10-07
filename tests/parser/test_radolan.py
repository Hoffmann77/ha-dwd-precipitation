"""RADOLAN parser regression tests against a committed real fixture.

No HA, no wradlib, no network. Deterministic golden-value check that
read_radolan_composite still parses a real DWD RW file correctly, and that the
vendored RADOLAN grid puts the recorded rain cell at the recorded (row, col).

The fixture is produced by scripts/create_fixture.py; tests skip when it is
absent so a fresh checkout without the binary still collects cleanly.
"""

import bz2
import json
from pathlib import Path

import pytest

from radar import get_radolan_grid_index, read_radolan_composite

FIXTURES = Path(__file__).parent.parent / "fixtures"
RW_BZ2 = FIXTURES / "radolan_rw_sample.bin.bz2"
META = FIXTURES / "radolan_metadata.json"

pytestmark = pytest.mark.skipif(
    not (RW_BZ2.exists() and META.exists()),
    reason="RADOLAN fixture not found — run scripts/create_fixture.py",
)


@pytest.fixture(scope="module")
def rw():
    meta = json.loads(META.read_text())["rw"]
    with bz2.open(RW_BZ2) as f:
        data, attrs = read_radolan_composite(f)
    return meta, data, attrs


def test_header_fields(rw):
    meta, _data, attrs = rw
    assert attrs["producttype"] == meta["producttype"]
    assert int(attrs["intervalseconds"]) == meta["intervalseconds"]


def test_shape(rw):
    meta, data, _attrs = rw
    assert list(data.shape) == meta["grid_shape"]


def test_expected_value_at_cell(rw):
    meta, data, _attrs = rw
    val = float(data[meta["grid_row"], meta["grid_col"]])
    assert val == pytest.approx(meta["expected_mm"], abs=1e-3)


def test_grid_index_matches_recorded_cell(rw):
    """The production lookup puts the recorded lat/lon at the recorded (row, col).

    The fixture's lat/lon is the centre of that cell on wradlib's grid, so the
    cell is unambiguous.
    """
    meta, _data, _attrs = rw
    cell = get_radolan_grid_index(meta["lat"], meta["lon"], *meta["grid_shape"])
    assert cell == (meta["grid_row"], meta["grid_col"])


# Cells wradlib's 900x900 grid gives for these locations (the reference tier
# re-derives them; pinned here so the check also runs without wradlib).
@pytest.mark.parametrize(
    ("lat", "lon", "cell"),
    [
        (53.5511, 9.9937, (744, 523)),    # Hamburg
        (52.5200, 13.4050, (633, 762)),   # Berlin
        (47.9990, 7.8421, (98, 351)),     # Freiburg
        (48.1374, 11.5755, (113, 648)),   # Munich
        (50.9375, 6.9603, (447, 299)),    # Cologne
    ],
)
def test_grid_index_matches_wradlib_pins(lat, lon, cell):
    assert get_radolan_grid_index(lat, lon) == cell


def test_grid_index_clamps_off_grid_locations():
    """A location off the 900 km grid gets the nearest edge cell, never a wrap."""
    assert get_radolan_grid_index(56.5, 20.0) == (899, 899)
    assert get_radolan_grid_index(45.0, 0.0) == (0, 0)
