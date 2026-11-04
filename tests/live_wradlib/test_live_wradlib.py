"""Live wradlib comparison: our parser vs. pure wradlib on today's DWD files.

For every product the integration reads, download the newest available file and
decode it twice:

* **ours** — the exact ``radar/`` calls production makes:
  ``read_odim_composite_at`` (RS, RV, and RW/SF in their HDF5 edition) or
  ``read_odim_classification_at`` (HymecNG), which find the location's cell on
  the grid the file describes in /where;
* **reference** — wradlib alone (``tests/wradlib_ref.py``): its own readers
  and its own DWD grids, none of our code.

Then require, for a fixed set of locations, the same cell and the same value,
plus an identical full grid per member. The committed-fixture reference tier
proves this once; this tier proves it keeps holding as DWD's files change. If
DWD moves a grid, the integration follows its files, and the cell check here
is what reports it.

Network + wradlib, so it is scheduled (``live-wradlib.yml``), never gates PRs,
and opens a tracking issue on failure. Run locally with:

    uv run --group wradlib-comparison pytest tests/live_wradlib -m live -v
"""

from __future__ import annotations

import io
import tarfile
from datetime import datetime
from functools import lru_cache

import numpy as np
import pytest

pytest.importorskip("wradlib")

from radar.grid import OutsideGrid  # noqa: E402
from radar.odim import (  # noqa: E402
    read_odim_classification,
    read_odim_classification_at,
    read_odim_composite,
    read_odim_composite_at,
    read_odim_grid,
)
from radar import nowcast  # noqa: E402
from radar.urls import radvor_prefix  # noqa: E402
from tests.live_common import download_newest  # noqa: E402
from tests.live_wradlib import report  # noqa: E402
from tests.wradlib_ref import (  # noqa: E402
    de1200_cell,
    read_odim,
    scale_odim,
)

pytestmark = [pytest.mark.live, pytest.mark.wradlib]


# Spread over the whole of Germany, including the grid-edge regions where a
# projection or orientation error shows most. Keep them fixed: a failure
# should name a place that can be looked up again.
FIXED_LOCATIONS = {
    "Kiel": (54.3233, 10.1228),
    "Hamburg": (53.5511, 9.9937),
    "Berlin": (52.5200, 13.4050),
    "Cologne": (50.9375, 6.9603),
    "Dresden": (51.0504, 13.7373),
    "Frankfurt": (50.1109, 8.6821),
    "Munich": (48.1374, 11.5755),
    "Freiburg": (47.9990, 7.8421),
    "Aachen": (50.7753, 6.0839),
    "Goerlitz": (51.1552, 14.9885),
}

# A manual run can name its own (DWD_LOCATIONS); the coverage checks below
# still use the fixed set, which is known to lie inside every grid.
LOCATIONS = report.custom_locations() or FIXED_LOCATIONS

# All RADVOR leads (RS rolling hours / RV 5-minute steps).
LEADS = tuple(nowcast.LEADS)


# ---------------------------------------------------------------------------
# Download (walk back from the newest likely release until one is up)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _download(product: str) -> tuple[bytes, datetime, str]:
    """Return (content, release, url) of the newest downloadable release."""
    content, ts, url = download_newest(product, timeout=120)
    report.SOURCES[product] = url
    return content, ts, url


@lru_cache(maxsize=None)
def _tar_members(product: str) -> dict[int, bytes]:
    """{lead: hd5 bytes} for a RADVOR tar; every lead must be present."""
    content, ts, url = _download(product)
    prefix = radvor_prefix(product, ts)
    with tarfile.open(fileobj=io.BytesIO(content)) as tf:
        names = set(tf.getnames())
        missing = [f"{prefix}_{lead:03d}-hd5" for lead in LEADS
                   if f"{prefix}_{lead:03d}-hd5" not in names]
        assert not missing, f"{url} lacks members {missing}"
        return {lead: tf.extractfile(f"{prefix}_{lead:03d}-hd5").read() for lead in LEADS}


@lru_cache(maxsize=None)
def _ref_grids(product: str) -> dict[int, np.ndarray]:
    """{lead: wradlib-decoded grid}; decoded once, shared by every location."""
    return {lead: scale_odim(*read_odim(hd5)) for lead, hd5 in _tar_members(product).items()}


def _same(ours: float, ref: float) -> bool:
    return (np.isnan(ours) and np.isnan(ref)) or ours == ref


def _cell_or_skip(place: str, payload: bytes, product: str) -> tuple[int, int]:
    """The cell the file's own grid gives, checked against wradlib's DE1200 one.

    Skips a location off the grid. A mismatch means DWD moved or resized the
    grid: the integration follows the file, so this is where it shows.
    """
    lat, lon = LOCATIONS[place]
    try:
        cell = read_odim_grid(io.BytesIO(payload)).cell(lat, lon)
    except OutsideGrid:
        report.record(place, cell="outside grid")
        pytest.skip(f"{place} ({lat}, {lon}) is outside the {product} grid")
    report.record(place, cell=f"{cell[0]}, {cell[1]}")
    assert cell == de1200_cell(lat, lon), f"{product} {place}: the file's grid is not wradlib's DE1200"
    return cell


def _cells(payload: bytes) -> list[tuple[int, int]]:
    """The fixed locations' cells on the file's own grid."""
    grid = read_odim_grid(io.BytesIO(payload))
    return [grid.cell(*loc) for loc in FIXED_LOCATIONS.values()]


# ---------------------------------------------------------------------------
# Per location: same cell, same value
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("product", ["rs", "rv"])
@pytest.mark.parametrize("place", LOCATIONS)
def test_radvor_location_matches_wradlib(product, place):
    """RS/RV: every lead at the location, as production reads it."""
    members = _tar_members(product)
    cell = _cell_or_skip(place, members[0], product)

    diffs, values = [], {}
    ref_grids = _ref_grids(product)
    for lead, hd5 in members.items():
        ours, _ = read_odim_composite_at(io.BytesIO(hd5), *LOCATIONS[place])
        values[lead] = float(ours)
        ref = ref_grids[lead][cell]
        if not _same(float(ours), float(ref)):
            diffs.append((lead, float(ours), float(ref)))

    if product == "rs":
        report.record(place, **{f"rs_{lead:03d}": report.fmt(values[lead]) for lead in (0, 60, 120)})
    else:
        # RV members are 5-minute amounts; x12 gives the rate in mm/h.
        future = [v for lead, v in values.items() if lead and not np.isnan(v)]
        report.record(
            place,
            rv_000=report.fmt(values[0] * 12),
            rv_max=report.fmt(max(future) * 12 if future else None),
        )
    report.mark(place, product.upper(), not diffs)
    assert not diffs, f"{product} {place} {cell}: (lead, ours, wradlib) {diffs}"


@pytest.mark.parametrize("place", LOCATIONS)
def test_hymecng_location_matches_wradlib(place):
    content, _, url = _download("hymecng")
    cell = _cell_or_skip(place, content, "hymecng")

    ours, _, what = read_odim_classification_at(io.BytesIO(content), *LOCATIONS[place])
    raw_ref, _ = read_odim(content)
    ref = int(raw_ref[cell])
    if ours == int(what["nodata"]):
        label = "no data"
    elif ours == int(what["undetect"]):
        label = report.PRECIP_TYPES[0]
    else:
        label = report.PRECIP_TYPES[ours] if ours < len(report.PRECIP_TYPES) else str(ours)
    report.record(place, hymecng=label)
    report.mark(place, "HymecNG", ours == ref)
    assert ours == ref, f"{place} {cell}: ours={ours}, wradlib={ref} ({url})"
    # A class index, or one of the two sentinels production maps explicitly.
    assert ours <= 10 or ours in (int(what["nodata"]), int(what["undetect"]))


@pytest.mark.parametrize("product", ["rw", "sf"])
@pytest.mark.parametrize("place", LOCATIONS)
def test_radolan_location_matches_wradlib(product, place):
    """RW/SF in their HDF5 edition: the DE1200 cell, as production reads it."""
    content, _, url = _download(product)
    cell = _cell_or_skip(place, content, product)

    ours, _ = read_odim_composite_at(io.BytesIO(content), *LOCATIONS[place])
    ref = scale_odim(*read_odim(content))[cell]
    ours, ref = float(ours), float(ref)
    report.record(place, **{product: report.fmt(None if np.isnan(ours) else ours, 1)})
    report.mark(place, product.upper(), _same(ours, ref))
    assert _same(ours, ref), f"{product} {place} {cell}: ours={ours}, wradlib={ref} ({url})"


# ---------------------------------------------------------------------------
# Per file: the whole decode, and that the locations are actually covered
# ---------------------------------------------------------------------------

def _assert_grids_equal(ours: np.ndarray, ref: np.ndarray, label: str) -> None:
    assert ours.shape == ref.shape, f"{label}: shape {ours.shape} vs {ref.shape}"
    np.testing.assert_array_equal(np.isnan(ours), np.isnan(ref), err_msg=label)
    mask = ~np.isnan(ours)
    np.testing.assert_array_equal(ours[mask], ref[mask], err_msg=label)


def _assert_locations_covered(grid: np.ndarray, cells: list, label: str) -> None:
    """Most fixed locations hold data: all-nodata would make the checks vacuous.

    A single radar outage can blank one location, so only a majority is
    required.
    """
    covered = sum(not np.isnan(grid[c]) for c in cells)
    assert covered * 2 > len(cells), f"{label}: only {covered}/{len(cells)} locations have data"


@pytest.mark.parametrize("product", ["rs", "rv"])
def test_radvor_full_grids_match_wradlib(product):
    members = _tar_members(product)
    cells = _cells(members[0])
    ref_grids = _ref_grids(product)
    for lead, hd5 in members.items():
        ours, _ = read_odim_composite(io.BytesIO(hd5))
        ref = ref_grids[lead]
        _assert_grids_equal(ours, ref, f"{product} lead {lead}")
        _assert_locations_covered(ours, cells, f"{product} lead {lead}")


def test_hymecng_full_grid_matches_wradlib():
    content, _, _ = _download("hymecng")
    ours, _, what = read_odim_classification(io.BytesIO(content))
    ref, _ = read_odim(content)
    np.testing.assert_array_equal(ours, ref)
    nodata = int(what["nodata"])
    as_float = np.where(ours == nodata, np.nan, 0.0)
    _assert_locations_covered(as_float, _cells(content), "hymecng")


@pytest.mark.parametrize("product", ["rw", "sf"])
def test_radolan_full_grid_matches_wradlib(product):
    content, _, _ = _download(product)
    ours, what_ours = read_odim_composite(io.BytesIO(content))
    ref = scale_odim(*read_odim(content))
    assert what_ours.get("prodname") == product.upper()
    _assert_grids_equal(ours, ref, product)
    _assert_locations_covered(ours, _cells(content), product)
