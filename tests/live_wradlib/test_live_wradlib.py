"""Live wradlib comparison: our parser vs. pure wradlib on today's DWD files.

For every product the integration reads, download the newest available file and
decode it twice:

* **ours** — the exact ``radar/`` calls production makes: ``get_rs_grid_index``
  / ``get_radolan_grid_index`` to find the cell, then
  ``read_odim_composite_cell`` (RS, RV), ``read_odim_classification``
  (HymecNG) or ``read_radolan_composite`` (RW, SF) to read it;
* **reference** — wradlib alone (``tests/wradlib_ref.py``): its own readers
  and its own DWD grids, none of our code.

Then require, for a fixed set of locations, the same cell and the same value,
plus an identical full grid per member. The committed-fixture reference tier
proves this once; this tier proves it keeps holding as DWD's files change.

Network + wradlib, so it is scheduled (``live-wradlib.yml``), never gates PRs,
and opens a tracking issue on failure. Run locally with:

    uv run --group wradlib-comparison pytest tests/live_wradlib -m live -v
"""

from __future__ import annotations

import bz2
import io
import tarfile
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import numpy as np
import pytest
import requests

pytest.importorskip("wradlib")

from radar import (  # noqa: E402
    RS_GRID_SHAPE,
    get_radolan_grid_index,
    get_rs_grid_index,
    read_odim_classification,
    read_odim_composite,
    read_odim_composite_cell,
    read_radolan_composite,
    rs_grid_contains,
)
from tests.live_wradlib import report  # noqa: E402
from tests.wradlib_ref import (  # noqa: E402
    RADOLAN_SHAPE,
    de1200_cell,
    radolan_cell,
    read_odim,
    read_radolan,
    scale_odim,
)

pytestmark = [pytest.mark.live, pytest.mark.wradlib]

_COMPOSITE = "https://opendata.dwd.de/weather/radar/composite"
_RADOLAN = "https://opendata.dwd.de/weather/radar/radolan"

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
LEADS = tuple(range(0, 121, 5))


# ---------------------------------------------------------------------------
# Download (walk back from the newest likely release until one is up)
# ---------------------------------------------------------------------------

def _five_minute_candidates() -> list[datetime]:
    ts = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    ts -= timedelta(minutes=ts.minute % 5 + 10)
    return [ts - timedelta(minutes=5 * i) for i in range(18)]


def _hourly_candidates() -> list[datetime]:
    """RW/SF as the integration reads them: the HH:50 releases."""
    now = datetime.now(timezone.utc)
    ts = now.replace(minute=50, second=0, microsecond=0)
    if ts > now - timedelta(minutes=35):
        ts -= timedelta(hours=1)
    return [ts - timedelta(hours=i) for i in range(6)]


_URLS = {
    "rs": (_five_minute_candidates,
           lambda ts: f"{_COMPOSITE}/rs/composite_rs_{ts:%Y%m%d_%H%M}.tar"),
    "rv": (_five_minute_candidates,
           lambda ts: f"{_COMPOSITE}/rv/composite_rv_{ts:%Y%m%d_%H%M}.tar"),
    "hymecng": (_five_minute_candidates,
                lambda ts: f"{_COMPOSITE}/hymecng/composite_HymecNG_{ts:%Y%m%d_%H%M}_000-hd5"),
    "rw": (_hourly_candidates,
           lambda ts: f"{_RADOLAN}/rw/raa01-rw_10000-{ts:%y%m%d%H%M}-dwd---bin.bz2"),
    "sf": (_hourly_candidates,
           lambda ts: f"{_RADOLAN}/sf/raa01-sf_10000-{ts:%y%m%d%H%M}-dwd---bin.bz2"),
}


@lru_cache(maxsize=None)
def _download(product: str) -> tuple[bytes, datetime, str]:
    """Return (content, release, url) of the newest downloadable release."""
    candidates, url_for = _URLS[product]
    tried = []
    for ts in candidates():
        url = url_for(ts)
        tried.append(url)
        try:
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
        except requests.RequestException:
            continue
        report.SOURCES[product] = url
        return resp.content, ts, url
    pytest.fail(f"No downloadable {product} release found. Tried:\n" + "\n".join(tried))


@lru_cache(maxsize=None)
def _tar_members(product: str) -> dict[int, bytes]:
    """{lead: hd5 bytes} for a RADVOR tar; every lead must be present."""
    content, ts, url = _download(product)
    prefix = f"composite_{product}_{ts:%Y%m%d_%H%M}"
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


def _de1200_cell_or_skip(place: str) -> tuple[int, int]:
    """Our DE1200 cell after checking it against wradlib; skip if off the grid."""
    lat, lon = LOCATIONS[place]
    if not rs_grid_contains(lat, lon):
        report.record(place, cell="outside grid")
        pytest.skip(f"{place} ({lat}, {lon}) is outside the RS/RV/HymecNG grid")
    cell = get_rs_grid_index(lat, lon)
    report.record(place, cell=f"{cell[0]}, {cell[1]}")
    assert cell == de1200_cell(lat, lon), f"{place}: cell differs from wradlib"
    return cell


# ---------------------------------------------------------------------------
# Per location: same cell, same value
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("product", ["rs", "rv"])
@pytest.mark.parametrize("place", LOCATIONS)
def test_radvor_location_matches_wradlib(product, place):
    """RS/RV: every lead at the location, as production reads it."""
    cell = _de1200_cell_or_skip(place)

    diffs, values = [], {}
    ref_grids = _ref_grids(product)
    for lead, hd5 in _tar_members(product).items():
        ours, _ = read_odim_composite_cell(
            io.BytesIO(hd5), *cell, expected_shape=RS_GRID_SHAPE
        )
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
    cell = _de1200_cell_or_skip(place)

    content, _, url = _download("hymecng")
    raw_ours, _, what = read_odim_classification(
        io.BytesIO(content), expected_shape=RS_GRID_SHAPE
    )
    raw_ref, _ = read_odim(content)
    ours, ref = int(raw_ours[cell]), int(raw_ref[cell])
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
    lat, lon = LOCATIONS[place]
    ref_cell = radolan_cell(lat, lon)
    if not all(0 <= i < n for i, n in zip(ref_cell, RADOLAN_SHAPE)):
        # Ours clamps to the edge cell here by design, wradlib does not.
        report.record(place, **{product: "outside grid"})
        pytest.skip(f"{place} ({lat}, {lon}) is outside the RADOLAN grid")
    cell = get_radolan_grid_index(lat, lon)
    assert cell == ref_cell, f"{place}: cell differs from wradlib"

    content, _, url = _download(product)
    data_ours, attrs = read_radolan_composite(bz2.open(io.BytesIO(content)))
    data_ref, _ = read_radolan(content)
    ours, ref = float(data_ours[cell]), float(data_ref[cell])
    nodata = float(attrs.get("nodataflag", -9999))
    report.record(place, **{product: report.fmt(None if ours == nodata else ours, 1)})
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
    cells = [get_rs_grid_index(*loc) for loc in FIXED_LOCATIONS.values()]
    ref_grids = _ref_grids(product)
    for lead, hd5 in _tar_members(product).items():
        ours, _ = read_odim_composite(io.BytesIO(hd5), expected_shape=RS_GRID_SHAPE)
        ref = ref_grids[lead]
        _assert_grids_equal(ours, ref, f"{product} lead {lead}")
        _assert_locations_covered(ours, cells, f"{product} lead {lead}")


def test_hymecng_full_grid_matches_wradlib():
    content, _, _ = _download("hymecng")
    ours, _, what = read_odim_classification(io.BytesIO(content), expected_shape=RS_GRID_SHAPE)
    ref, _ = read_odim(content)
    np.testing.assert_array_equal(ours, ref)
    nodata = int(what["nodata"])
    as_float = np.where(ours == nodata, np.nan, 0.0)
    _assert_locations_covered(
        as_float, [get_rs_grid_index(*loc) for loc in FIXED_LOCATIONS.values()], "hymecng"
    )


@pytest.mark.parametrize("product", ["rw", "sf"])
def test_radolan_full_grid_matches_wradlib(product):
    content, _, _ = _download(product)
    ours, attrs_ours = read_radolan_composite(bz2.open(io.BytesIO(content)))
    ref, attrs_ref = read_radolan(content)
    assert attrs_ours["producttype"] == attrs_ref["producttype"]
    assert attrs_ours["datetime"] == attrs_ref["datetime"]
    ours, ref = np.asarray(ours, dtype=float), np.asarray(ref, dtype=float)
    _assert_grids_equal(ours, ref, product)
    # RADOLAN marks nodata with a sentinel rather than NaN.
    nodata = float(attrs_ours.get("nodataflag", -9999))
    _assert_locations_covered(
        np.where(ours == nodata, np.nan, ours),
        [get_radolan_grid_index(*loc) for loc in FIXED_LOCATIONS.values()],
        product,
    )
