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

import numpy as np
import pytest

from radar import get_radolan_grid, read_radolan_composite

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
    """Our WGS84 grid's nearest cell to the recorded lat/lon == recorded (row, col).

    Mirrors the production nearest-cell logic (RadolanProduct.index) and checks
    it against the fixture's pyproj/wradlib-derived coordinates.
    """
    meta, _data, _attrs = rw
    grid = get_radolan_grid(*meta["grid_shape"], wgs84=True)
    lat, lon = meta["lat"], meta["lon"]
    dist_sq = (grid[:, :, 1] - lat) ** 2 + (grid[:, :, 0] - lon) ** 2
    row, col = np.unravel_index(np.argmin(dist_sq), dist_sq.shape)
    assert (int(row), int(col)) == (meta["grid_row"], meta["grid_col"])
