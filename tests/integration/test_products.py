"""Product metadata-derivation tests — real _fetch_and_parse with mocked I/O.

Needs the ha-test dependency group installed (products.py imports HA transitively).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest


from custom_components.dwd_precipitation import products, rain_events_tracker
from custom_components.dwd_precipitation.coordinator import CoordinatorData
from custom_components.dwd_precipitation.products import (
    HymecNG,
    RadolanRW,
    RadolanSF,
    RadvorRS,
    RadvorRV,
)
from custom_components.dwd_precipitation.radar import RS_GRID_SHAPE, get_rs_grid_index
from custom_components.dwd_precipitation.rain_events_tracker import RainEventsTracker
from custom_components.dwd_precipitation.utils import AsyncResponse

from tests.factories.odim import make_hymecng_h5
from tests.factories.radvor import LEADS, RangeServer, make_radvor_tar


def _executor_jobs(coord):
    """Count the executor jobs the coordinator hands to hass."""
    return patch.object(
        coord.hass, "async_add_executor_job", wraps=coord.hass.async_add_executor_job
    )


def _rs_what(base: datetime, lead: int) -> dict:
    """ODIM /dataset/what for an RS member: rolling hour [T+lead-60, T+lead]."""
    end = base + timedelta(minutes=lead)
    start = end - timedelta(minutes=60)
    return {
        "prodname": "RS",
        "startdate": start.strftime("%Y%m%d"), "starttime": start.strftime("%H%M%S"),
        "enddate": end.strftime("%Y%m%d"), "endtime": end.strftime("%H%M%S"),
    }


async def _rs_fetch(make_coordinator, ts: datetime, values: dict[int, float], full: bool = True):
    """Run RadvorRS._fetch_and_parse, serving each decoded lead from ``values``."""
    decoded: list[int] = []

    def _read(fileobj, _row, _col, **_kw):
        lead = int(fileobj.getvalue())  # make_radvor_tar's payload is the lead
        decoded.append(lead)
        return np.float32(values[lead]), _rs_what(ts, lead)

    coord = make_coordinator(RadvorRS, {"full_rolling_series": full})

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rs", ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=_read),
        _executor_jobs(coord) as jobs,
    ):
        data, meta = await coord._fetch_and_parse(ts)
    # The decode runs off the loop; so does unpacking the archive this server
    # sends whole instead of a range (default mode only).
    assert jobs.call_count == (1 if full else 2)
    return data, meta, decoded


@pytest.mark.asyncio
async def test_rs_fetch_derives_base_source_timestamp_and_window(make_coordinator) -> None:
    """RS: source_timestamp is the base run time (data_end - lead), identical for all leads.

    The ODIM enddate/endtime advances with the lead time, so the previous code
    (which used it directly) was only correct for the 0-min member.
    """
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    data, meta, _ = await _rs_fetch(make_coordinator, ts, {lead: float(lead) for lead in LEADS})

    # The three non-overlapping hours come from leads 0 / 60 / 120.
    assert [data["last_60"], data["next_60"], data["next_60_120"]] == [0.0, 60.0, 120.0]
    base = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    assert [m.source_timestamp for m in meta.values()] == [base] * 5
    assert [m.lead_time_minutes for m in (meta["last_60"], meta["next_60"], meta["next_60_120"])] == [0, 60, 120]
    assert meta["last_60"].data_start == datetime(2026, 5, 18, 15, 0, tzinfo=timezone.utc)
    assert meta["last_60"].data_end == base
    assert meta["next_60_120"].data_start == datetime(2026, 5, 18, 17, 0, tzinfo=timezone.utc)
    assert meta["next_60_120"].data_end == datetime(2026, 5, 18, 18, 0, tzinfo=timezone.utc)

    # The whole 120-minute forecast is the two forecast hours added.
    assert data["next_120"] == pytest.approx(180.0)
    assert meta["next_120"].lead_time_minutes == 120
    assert meta["next_120"].data_start == base
    assert meta["next_120"].data_end == datetime(2026, 5, 18, 18, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_rs_peak_hour_and_rolling_series(make_coordinator) -> None:
    """RS: the wettest future rolling hour, its window, and the 25-point series."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    # A storm straddling the fixed hours: its heaviest hour ends at T+90, which
    # neither "next 60 min" (lead 60) nor "next 60-120 min" (lead 120) sees in full.
    values = {lead: 0.0 for lead in LEADS}
    values.update({0: 30.0, 60: 4.0, 85: 9.0, 90: 18.0, 95: 18.0, 120: 5.0})
    data, meta, _ = await _rs_fetch(make_coordinator, ts, values)

    # Lead 0 (the past hour, 30 mm) is not a forecast and is excluded; the tie
    # between leads 90 and 95 goes to the earlier window.
    assert data["peak_1h"] == pytest.approx(18.0)
    peak = meta["peak_1h"]
    assert peak.lead_time_minutes == 90
    assert peak.data_start == datetime(2026, 5, 18, 16, 30, tzinfo=timezone.utc)
    assert peak.data_end == datetime(2026, 5, 18, 17, 30, tzinfo=timezone.utc)
    assert peak.source_timestamp == ts

    series = peak.rolling_1h
    assert [p["lead"] for p in series] == LEADS
    assert series[0] == {
        "lead": 0,
        "start": "2026-05-18T15:00:00+00:00",
        "end": "2026-05-18T16:00:00+00:00",
        "value": pytest.approx(30.0),
    }
    assert series[18]["value"] == pytest.approx(18.0)  # lead 90
    # The fixed-hour members keep no series of their own.
    assert all(m.rolling_1h is None for m in (meta["last_60"], meta["next_60"], meta["next_60_120"]))


@pytest.mark.asyncio
async def test_rs_dry_forecast_has_no_peak_window(make_coordinator) -> None:
    """RS: a dry forecast peaks at 0 mm, but has no wettest hour to point at."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    data, meta, _ = await _rs_fetch(make_coordinator, ts, {lead: 0.0 for lead in LEADS})

    assert data["peak_1h"] == 0.0
    assert meta["peak_1h"].data_start is None
    assert meta["peak_1h"].data_end is None
    assert meta["peak_1h"].lead_time_minutes is None
    assert len(meta["peak_1h"].rolling_1h) == 25


@pytest.mark.asyncio
async def test_rs_without_option_decodes_only_the_three_hours(make_coordinator) -> None:
    """RS: with the option off only leads 0/60/120 are decoded; RV owns the peak."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    values = {lead: float(lead) for lead in LEADS}
    data, meta, decoded = await _rs_fetch(make_coordinator, ts, values, full=False)

    assert decoded == [0, 60, 120]
    assert data == {
        "last_60": 0.0, "next_60": 60.0, "next_60_120": 120.0, "peak_1h": None, "next_120": 180.0,
    }
    assert meta["peak_1h"] is None
    assert [m.lead_time_minutes for m in (meta["last_60"], meta["next_60"], meta["next_60_120"])] == [0, 60, 120]



@pytest.mark.asyncio
async def test_rs_range_fallback_is_said_once_and_its_end_once(make_coordinator, caplog) -> None:
    """Whole archives instead of ranges: one WARNING per run, one INFO after."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    archive = make_radvor_tar("rs", ts)
    ignores_ranges = RangeServer(archive, ranges=False).async_get  # 200: the whole file
    serves_ranges = RangeServer(archive).async_get

    def _read(fileobj, _row, _col, **_kw):
        lead = int(fileobj.getvalue())
        return np.float32(lead), _rs_what(ts, lead)

    coord = make_coordinator(RadvorRS, {"full_rolling_series": False})
    with patch.object(products, "read_odim_composite_cell", side_effect=_read):
        for server in (ignores_ranges, ignores_ranges, ignores_ranges, serves_ranges):
            with patch.object(products, "async_get", side_effect=server):
                data, _ = await coord._fetch_and_parse(ts)
            assert [data["last_60"], data["next_60"], data["next_60_120"]] == [0.0, 60.0, 120.0]  # values are unaffected

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "Reading whole DWD RS precipitation nowcast archives" in warnings[0].message
    assert any("work again" in r.message and r.levelno == logging.INFO for r in caplog.records)


@pytest.mark.asyncio
async def test_rs_without_option_reads_the_hours_by_range(make_coordinator) -> None:
    """RS: the default mode asks for byte ranges instead of the whole archive."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    server = RangeServer(make_radvor_tar("rs", ts))

    def _read(fileobj, _row, _col, **_kw):
        lead = int(fileobj.getvalue())
        return np.float32(lead), _rs_what(ts, lead)

    coord = make_coordinator(RadvorRS, {"full_rolling_series": False})
    with (
        patch.object(products, "async_get", side_effect=server.async_get),
        patch.object(products, "read_odim_composite_cell", side_effect=_read),
        _executor_jobs(coord) as jobs,
    ):
        data, _ = await coord._fetch_and_parse(ts)

    assert [data["last_60"], data["next_60"], data["next_60_120"]] == [0.0, 60.0, 120.0]
    # The test archive is tiny, so the first window already holds all three.
    assert len(server.requests) == 1
    assert server.requests[0]["Range"].startswith("bytes=0-")
    assert jobs.call_count == 1

def _rv_what(base: datetime, lead: int) -> dict:
    """ODIM /dataset/what for an RV member: 5-min window [T+lead-5, T+lead]."""
    end = base + timedelta(minutes=lead)
    start = end - timedelta(minutes=5)
    return {
        "prodname": "RV_top_view",
        "startdate": start.strftime("%Y%m%d"), "starttime": start.strftime("%H%M%S"),
        "enddate": end.strftime("%Y%m%d"), "endtime": end.strftime("%H%M%S"),
    }


@pytest.mark.asyncio
async def test_rv_fetch_derives_buckets_and_timing(make_coordinator) -> None:
    """RV: peak intensity, start/end detection, and the raw 5-min series."""
    ts = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    # Scenario: dry now, rain at leads 30..60 (1.0 mm each), dry afterwards.
    leads = LEADS
    values = {lead: (1.0 if 30 <= lead <= 60 else 0.0) for lead in leads}
    reads = iter([
        (np.float32(values[lead]), _rv_what(ts, lead))
        for lead in leads
    ])

    coord = make_coordinator(RadvorRV)

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rv", ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=lambda _f, _r, _c, **_kw: next(reads)),
    ):
        data, meta = await coord._fetch_and_parse(ts)

    # Peak intensity: 1.0 mm/5min → 12 mm/h in hour 1; hour 2 is dry.
    assert data["max_060"] == pytest.approx(12.0)
    assert data["max_120"] == pytest.approx(0.0)
    assert data["max_000_120"] == pytest.approx(12.0)
    # The two-hour sum sensors were removed; only max intensity remains.
    assert "rv_060" not in data
    assert "rv_120" not in data
    # Dry now → rain starts at lead 30 (25 min out); ends at lead 65 boundary (60 min out).
    assert data["start_in"] == 25
    assert data["start_at"] == datetime(2026, 7, 16, 20, 55, tzinfo=timezone.utc)
    assert data["end_in"] == 60
    assert data["end_at"] == datetime(2026, 7, 16, 21, 30, tzinfo=timezone.utc)
    # Rain occurs within the horizon → the "rain expected" flag is set.
    assert data["rain_within_2h"] is True

    # Base run time and per-hour bucket metadata (no samples on these anymore).
    assert meta["max_060"].source_timestamp == ts
    assert meta["max_060"].lead_time_minutes == 60
    assert meta["max_060"].data_start == datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    assert meta["max_060"].data_end == datetime(2026, 7, 16, 21, 30, tzinfo=timezone.utc)
    assert meta["max_060"].samples is None
    assert meta["max_120"].samples is None
    assert meta["max_000_120"].lead_time_minutes == 120
    assert meta["max_000_120"].data_start == datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    assert meta["max_000_120"].data_end == datetime(2026, 7, 16, 22, 30, tzinfo=timezone.utc)

    # The raw 5-min series (25 points, leads 0..120) rides on the rain flag.
    samples = meta["rain_within_2h"].samples
    assert len(samples) == 25
    assert samples[0]["lead"] == 0
    assert samples[-1]["lead"] == 120
    # Lead 60 is the last raining member: 1.0 mm/5min → 12 mm/h.
    lead_60 = next(s for s in samples if s["lead"] == 60)
    assert lead_60["value"] == pytest.approx(1.0)
    assert lead_60["intensity"] == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_rv_threshold_from_options_suppresses_light_rain(make_coordinator) -> None:
    """RV: light rain below the configured mm/h threshold does not trigger start/end."""
    ts = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    leads = LEADS
    values = {lead: (0.2 if lead >= 30 else 0.0) for lead in leads}  # 0.2 mm/5min = 2.4 mm/h
    reads = iter([
        (np.float32(values[lead]), _rv_what(ts, lead))
        for lead in leads
    ])

    # Threshold is now an intensity (mm/h); 2.4 mm/h < 3.0 mm/h → suppressed.
    coord = make_coordinator(RadvorRV, {"precipitation_threshold": 3.0})

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rv", ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=lambda _f, _r, _c, **_kw: next(reads)),
    ):
        data, _meta = await coord._fetch_and_parse(ts)

    # 0.2 mm/5min (2.4 mm/h) never exceeds the 3.0 mm/h threshold → no rain.
    assert data["start_in"] is None
    assert data["start_at"] is None
    assert data["end_in"] is None
    assert data["rain_within_2h"] is False


@pytest.mark.asyncio
async def test_rv_threshold_is_interpreted_as_mm_per_hour(make_coordinator) -> None:
    """RV: the mm/h threshold is divided by 12 before comparison to 5-min values."""
    ts = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    leads = LEADS
    # Dry now; 0.4 mm/5min (=4.8 mm/h) at lead 30, 0.6 mm/5min (=7.2 mm/h) at lead 60.
    values = {lead: 0.0 for lead in leads}
    values[30] = 0.4
    values[60] = 0.6
    reads = iter([
        (np.float32(values[lead]), _rv_what(ts, lead))
        for lead in leads
    ])

    # 6 mm/h → 0.5 mm/5min gate: 4.8 mm/h is dry, 7.2 mm/h counts.
    coord = make_coordinator(RadvorRV, {"precipitation_threshold": 6.0})

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rv", ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=lambda _f, _r, _c, **_kw: next(reads)),
    ):
        data, _meta = await coord._fetch_and_parse(ts)

    # Only the 7.2 mm/h step at lead 60 crosses the gate → start 55 min out.
    assert data["start_in"] == 55
    assert data["rain_within_2h"] is True


@pytest.mark.asyncio
async def test_rv_end_algorithm_option_selects_clearing(make_coordinator) -> None:
    """RV: the clearing algorithm looks past a lull to the last forecast wave."""
    ts = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    leads = LEADS
    # Dry now; a wave at lead 10, a lull, then a second wave at lead 60.
    values = {lead: (1.0 if lead in (10, 60) else 0.0) for lead in leads}

    def _make_reads():
        return iter([
            (np.float32(values[lead]), _rv_what(ts, lead))
            for lead in leads
        ])

    # Default (episode): ends at the first lull after the lead-10 wave.
    coord = make_coordinator(RadvorRV)
    episode_reads = _make_reads()
    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rv", ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=lambda _f, _r, _c, **_kw: next(episode_reads)),
    ):
        episode, _ = await coord._fetch_and_parse(ts)
    assert episode["start_in"] == 5
    assert episode["end_in"] == 10

    # Clearing: waits out the lull to the boundary after the lead-60 wave. A
    # new coordinator, as an options change reloads the entry.
    coord = make_coordinator(RadvorRV, {"precipitation_end_algorithm": "clearing"})
    clearing_reads = _make_reads()
    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rv", ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=lambda _f, _r, _c, **_kw: next(clearing_reads)),
    ):
        clearing, _ = await coord._fetch_and_parse(ts)
    assert clearing["start_in"] == 5
    assert clearing["end_in"] == 60
    assert clearing["end_at"] == datetime(2026, 7, 16, 21, 30, tzinfo=timezone.utc)


def _hymecng_reader(class_value: int, nodata: int = 255, undetect: int = 254):
    """Return a fake read_odim_classification_cell yielding ``class_value``."""
    dataset_what = {
        "prodname": "HymecNG_top_view",
        "product": "COMP",
        "startdate": "20260729", "starttime": "173000",
        "enddate": "20260729", "endtime": "173000",
    }
    moment_what = {"quantity": "CLASS", "nodata": float(nodata), "undetect": float(undetect)}
    return lambda _f, _row, _col, **_kw: (class_value, dataset_what, moment_what)


@pytest.mark.asyncio
async def test_hymecng_fetch_maps_class_index_to_label(make_coordinator) -> None:
    """HymecNG: end-to-end fetch + real reader maps the cell class to a label."""
    ts = datetime(2026, 7, 29, 17, 30, tzinfo=timezone.utc)
    hd5 = make_hymecng_h5(shape=RS_GRID_SHAPE, fill=7)  # SNOW everywhere

    coord = make_coordinator(HymecNG)

    get_mock = AsyncMock(return_value=AsyncResponse(content=hd5.getvalue()))
    with patch.object(products, "async_get", new=get_mock):
        data, meta = await coord._fetch_and_parse(ts)

    assert data == {"precipitation_type": "snow"}
    meta = meta["precipitation_type"]
    assert meta.source_product == "HymecNG_top_view"
    assert meta.source_timestamp == ts
    assert meta.data_end == ts
    # The single ODIM_H5 file (no tar) is addressed by the expected URL.
    assert get_mock.call_args.args[0].endswith(
        "/composite/hymecng/composite_HymecNG_20260729_1730_000-hd5"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "class_value, expected",
    [
        (0, "no_precipitation"),
        (3, "rain"),
        (5, "freezing_rain"),
        (9, "hail"),
        (10, "large_hail"),
        (254, "no_precipitation"),  # undetect → scanned, dry
        (255, None),                # nodata → outside coverage → unavailable
        (200, None),                # unexpected index → unavailable
    ],
)
async def test_hymecng_class_and_sentinel_mapping(make_coordinator, class_value, expected) -> None:
    """HymecNG: class indices, undetect, and nodata map to the right sensor state."""
    ts = datetime(2026, 7, 29, 17, 30, tzinfo=timezone.utc)
    coord = make_coordinator(HymecNG)

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=b"x")),
        ),
        patch.object(
            products,
            "read_odim_classification_cell",
            side_effect=_hymecng_reader(class_value),
        ),
    ):
        data, _meta = await coord._fetch_and_parse(ts)

    assert data == {"precipitation_type": expected}


def _radolan_what(product: str, end: datetime, hours: int) -> dict:
    """ODIM /dataset1/what of a RADOLAN analysis covering ``hours`` up to ``end``."""
    start = end - timedelta(hours=hours)
    return {
        "prodname": product,
        "startdate": start.strftime("%Y%m%d"), "starttime": start.strftime("%H%M%S"),
        "enddate": end.strftime("%Y%m%d"), "endtime": end.strftime("%H%M%S"),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(("cls", "product", "hours"), [(RadolanRW, "RW", 1), (RadolanSF, "SF", 24)])
async def test_radolan_reads_the_hdf5_edition_and_its_window(make_coordinator, cls, product, hours) -> None:
    """RADOLAN: the HDF5 URL, one DE1200 cell, and the window from ODIM what."""
    ts = datetime(2025, 6, 1, 12, 50, tzinfo=timezone.utc)
    coord = make_coordinator(cls)
    get = AsyncMock(return_value=AsyncResponse(content=b"hdf5"))
    read = patch.object(
        products,
        "read_odim_composite_cell",
        return_value=(np.float32(1.7), _radolan_what(product, ts, hours)),
    )
    with patch.object(products, "async_get", new=get), read as reader:
        value, meta = await coord._fetch_and_parse(ts)

    url = get.call_args.args[0]
    assert url.endswith(f"/{product.lower()}/raa01-{product.lower()}_10000-2506011250-dwd---bin.hdf5")
    assert reader.call_args.args[1:] == coord.index
    assert reader.call_args.kwargs["expected_shape"] == RS_GRID_SHAPE
    assert coord.index == get_rs_grid_index(*coord.coords)
    assert value == {"amount": pytest.approx(1.7)}
    meta = meta["amount"]
    assert meta.source_product == product
    assert meta.source_timestamp == meta.data_end == ts
    assert meta.data_start == ts - timedelta(hours=hours)


@pytest.mark.asyncio
@pytest.mark.parametrize(("cell_value", "expected"), [(np.nan, None), (0.0, 0.0), (1.7, 1.7)])
async def test_radolan_nodata_cell_reads_as_none(make_coordinator, cell_value, expected) -> None:
    """RADOLAN nodata (NaN from the ODIM reader) becomes None; dry stays 0."""
    ts = datetime(2025, 6, 1, 12, 50, tzinfo=timezone.utc)
    coord = make_coordinator(RadolanRW)
    with (
        patch.object(products, "async_get", new=AsyncMock(return_value=AsyncResponse(content=b"x"))),
        patch.object(
            products,
            "read_odim_composite_cell",
            return_value=(np.float32(cell_value), _radolan_what("RW", ts, 1)),
        ),
    ):
        value, _meta = await coord._fetch_and_parse(ts)

    assert value == {"amount": pytest.approx(expected) if expected is not None else None}


_FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("coords", "expected"),
    [
        ((46.2, 3.9), None),        # France, beyond the radars: nodata
        ((51.05, 13.73), 0.0),      # Dresden, dry that hour
    ],
)
async def test_radolan_real_hdf5_file(make_coordinator, coords, expected) -> None:
    """A real RW HDF5 file (2026-10-12 12:50) decodes through the production path."""
    content = (_FIXTURES / "radolan_rw_sample.hdf5").read_bytes()
    coord = make_coordinator(RadolanRW)
    coord.coords = coords

    with patch.object(
        products, "async_get", new=AsyncMock(return_value=AsyncResponse(content=content))
    ):
        value, meta = await coord._fetch_and_parse(datetime(2026, 10, 12, 12, 50, tzinfo=timezone.utc))

    assert value == {"amount": expected}
    meta = meta["amount"]
    assert meta.source_product == "RW"
    assert meta.data_end == datetime(2026, 10, 12, 12, 50, tzinfo=timezone.utc)
    assert meta.data_start == datetime(2026, 10, 12, 11, 50, tzinfo=timezone.utc)


async def _rv_fetch(make_coordinator, ts: datetime, values: dict[int, float | None]):
    """Run RadvorRV._fetch_and_parse, serving each lead from ``values`` (None = missing member)."""
    def _read(fileobj, _row, _col, **_kw):
        lead = int(fileobj.getvalue())  # make_radvor_tar's payload is the lead
        value = values[lead]
        return np.float32("nan" if value is None else value), _rv_what(ts, lead)

    coord = make_coordinator(RadvorRV)
    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rv", ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=_read),
        _executor_jobs(coord) as jobs,
    ):
        data, meta = await coord._fetch_and_parse(ts)
    assert jobs.call_count == 1
    return data, meta


@pytest.mark.asyncio
async def test_rv_peak_hour_matches_rs_for_the_same_rain(make_coordinator) -> None:
    """RV-summed rolling hours give RS's peak, window and future series exactly.

    The two sources back one sensor, switched by an option, so the state must
    not move when a user flips it.
    """
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    leads = LEADS
    # 5-minute rain: a shower around +40 min and a heavier cell around +95 min.
    rv = {lead: 0.0 for lead in leads}
    rv.update({35: 0.4, 40: 0.9, 45: 0.3, 85: 0.6, 90: 1.7, 95: 2.2, 100: 0.8})
    # RS members are the rolling hour ending at each lead (the past hour being
    # whatever it was; RV cannot see it, and it plays no part in the peak).
    rs = {
        lead: round(sum(rv[k] for k in leads if lead - 60 < k <= lead and k > 0), 3)
        for lead in leads
    }
    rs[0] = 12.0

    rv_data, rv_meta = await _rv_fetch(make_coordinator, ts, rv)
    rs_data, rs_meta, _ = await _rs_fetch(make_coordinator, ts, rs)

    assert rv_data["peak_1h"] == pytest.approx(rs_data["peak_1h"])
    # Wettest hour ends at +95: steps +40..+95 catch the tail of the first
    # shower too (0.9 + 0.3), beating the window ending at +100 (5.6 mm).
    assert rv_data["peak_1h"] == pytest.approx(0.9 + 0.3 + 0.6 + 1.7 + 2.2)
    for attr in ("lead_time_minutes", "data_start", "data_end"):
        assert getattr(rv_meta["peak_1h"], attr) == getattr(rs_meta["peak_1h"], attr), attr
    assert rv_meta["peak_1h"].lead_time_minutes == 95
    assert rv_meta["peak_1h"].data_start == datetime(2026, 5, 18, 16, 35, tzinfo=timezone.utc)
    assert rv_meta["peak_1h"].data_end == datetime(2026, 5, 18, 17, 35, tzinfo=timezone.utc)

    # RV's series is the 13 wholly-future hours, point for point equal to RS's.
    rv_series = rv_meta["peak_1h"].rolling_1h
    rs_series = {p["lead"]: p for p in rs_meta["peak_1h"].rolling_1h}
    assert [p["lead"] for p in rv_series] == list(range(60, 121, 5))
    assert len(rs_series) == 25
    for point in rv_series:
        assert point == rs_series[point["lead"]]


@pytest.mark.asyncio
async def test_rv_intensity_now_is_the_analysis_step_as_a_rate(make_coordinator) -> None:
    """RV: lead 0 (the 5 minutes ending at T) becomes mm/h, with its window."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    rv: dict[int, float | None] = {lead: 0.0 for lead in LEADS}
    # The float32 reading carries noise below the ODIM 0.001 mm resolution.
    rv.update({0: 0.123, 5: 2.0})
    data, meta = await _rv_fetch(make_coordinator, ts, rv)

    assert data["amount_000"] == 0.123
    assert data["intensity_000"] == 1.476  # exact at 0.001 mm resolution, not 1.47600001
    assert meta["intensity_000"].lead_time_minutes == 0
    assert meta["intensity_000"].source_timestamp == ts
    assert meta["intensity_000"].data_start == datetime(2026, 5, 18, 15, 55, tzinfo=timezone.utc)
    assert meta["intensity_000"].data_end == ts


@pytest.mark.asyncio
async def test_rv_intensity_now_is_unknown_without_the_analysis(make_coordinator) -> None:
    """RV: a missing lead-0 member leaves both values None rather than 0."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    rv: dict[int, float | None] = {lead: 0.0 for lead in LEADS}
    rv[0] = None
    data, _ = await _rv_fetch(make_coordinator, ts, rv)

    assert data["intensity_000"] is None
    assert data["amount_000"] is None


@pytest.mark.asyncio
async def test_rv_peak_hour_treats_missing_step_as_dry(make_coordinator) -> None:
    """RV: a missing 5-minute member counts as 0, as RS does at the coverage edge."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    rv: dict[int, float | None] = {lead: 0.0 for lead in LEADS}
    rv.update({5: None, 60: 1.0, 65: 2.0})
    data, meta = await _rv_fetch(make_coordinator, ts, rv)

    assert data["peak_1h"] == pytest.approx(3.0)
    # Lead 5 opens the T+0..T+60 window; its start falls back to end - 60 min.
    first = meta["peak_1h"].rolling_1h[0]
    assert first == {
        "lead": 60,
        "start": "2026-05-18T16:00:00+00:00",
        "end": "2026-05-18T17:00:00+00:00",
        "value": pytest.approx(1.0),
    }


# ---------------------------------------------------------------------------
# RV: rain_events glue (fill, track, persist)
# ---------------------------------------------------------------------------


class _FakeStore:
    """Stands in for homeassistant.helpers.storage.Store."""

    def __init__(self, data=None) -> None:
        self.data = data
        self.delays: list[float] = []

    async def async_load(self):
        return self.data

    def async_delay_save(self, data_func, delay):
        self.data = data_func()
        self.delays.append(delay)

    async def async_save(self, data):
        self.data = data


def _rv_release_tar(ts: datetime) -> bytes:
    """An RV tar whose member payloads name their release and lead."""
    return make_radvor_tar("rv", ts, lambda lead: f"{ts:%H%M}:{lead:03d}".encode())


class _RVWorld:
    """Serves RV releases (whole or by range) for a rain function."""

    def __init__(self, rain, missing=(), garbled=(), delay=0.0) -> None:
        self.rain = rain  # step end -> mm
        self.missing = set(missing)  # releases DWD does not serve
        self.garbled = set(garbled)  # releases served with the wrong window
        self.delay = delay  # seconds each range read takes
        self.requests: list[tuple[datetime, dict | None]] = []

    async def get(self, url, _client, headers=None, **_kw):
        stamp = url.rsplit("_", 2)[-2] + url.rsplit("_", 1)[-1][:4]
        ts = datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
        self.requests.append((ts, headers))
        if headers and self.delay:
            await asyncio.sleep(self.delay)
        if ts in self.missing:
            import aiohttp
            from yarl import URL

            info = aiohttp.RequestInfo(URL(url), "GET", {}, URL(url))
            raise aiohttp.ClientResponseError(info, (), status=404, message="Not Found")
        return await RangeServer(_rv_release_tar(ts)).fetch(url, headers)

    def read(self, fileobj, _row, _col, **_kw):
        stamp, lead = fileobj.getvalue().decode().split(":")
        base = DAY_RV.replace(hour=int(stamp[:2]), minute=int(stamp[2:]))
        step_end = base + timedelta(minutes=int(lead))
        if base in self.garbled:
            base -= timedelta(minutes=5)
        return np.float32(self.rain(step_end)), _rv_what(base, int(lead))


DAY_RV = datetime(2026, 10, 12, tzinfo=timezone.utc)


def _rv_tracked(make_coordinator, store=None, options=None):
    coord = make_coordinator(RadvorRV, options)
    coord.published: list[dict | None] = []
    coord.async_update_listeners = lambda: coord.published.append(
        coord.data.data["rain_events"]
    )
    coord._rain_tracker = RainEventsTracker(
        coord.hass,
        coord.config_entry,
        coord.options.rain_event_threshold,
        coord._async_fetch_analysis,
        coord._publish_rain_view,
        store=store if store is not None else _FakeStore(),
    )
    return coord


@contextmanager
def _serving(world):
    with (
        patch.object(products, "async_get", side_effect=world.get),
        patch.object(products, "read_odim_composite_cell", side_effect=world.read),
    ):
        yield


async def _rv_refresh(coord, world, hhmm):
    """What the coordinator does for one release: fetch, then store the data."""
    ts = DAY_RV.replace(hour=int(hhmm[:2]), minute=int(hhmm[3:]))
    with _serving(world):
        data, metadata = await coord._fetch_and_parse(ts)
        await coord._async_on_new_release(ts, data, metadata)
    coord.data = CoordinatorData(data, metadata)
    return data, metadata


async def _rv_release(coord, world, hhmm):
    """One release, including the background fill it may start."""
    _, metadata = await _rv_refresh(coord, world, hhmm)
    if coord._rain_tracker.fill_task is not None:
        with _serving(world):
            await coord._rain_tracker.fill_task
    return coord.data.data, metadata


def _rain_between(lo, hi, mm=1.0):
    lo_t = DAY_RV.replace(hour=int(lo[:2]), minute=int(lo[3:]))
    hi_t = DAY_RV.replace(hour=int(hi[:2]), minute=int(hi[3:]))
    return lambda t: mm if lo_t < t <= hi_t else 0.0


@pytest.mark.asyncio
async def test_rv_first_release_fills_the_hour_by_range_reads(make_coordinator) -> None:
    world = _RVWorld(_rain_between("13:30", "14:10"))
    coord = _rv_tracked(make_coordinator)

    data, _ = await _rv_release(coord, world, "14:00")

    events = data["rain_events"]
    assert events["history_complete"] is True
    assert events["steps"][:12] == [0.0] * 6 + [1.0] * 6
    event = events["events"][0]
    assert (event["status"], event["start"]) == ("ongoing", "2026-10-12T13:30:00+00:00")
    # One whole archive for the release itself, then 11 analyses by range.
    fills = [h for _, h in world.requests if h]
    assert len(fills) == 11 and all(h["Range"].startswith("bytes=0-") for h in fills)


@pytest.mark.asyncio
async def test_rv_next_release_fills_nothing_and_keeps_the_id(make_coordinator) -> None:
    world = _RVWorld(_rain_between("13:30", "15:00"))
    coord = _rv_tracked(make_coordinator)
    first, _ = await _rv_release(coord, world, "14:00")
    world.requests.clear()

    second, _ = await _rv_release(coord, world, "14:05")

    assert [h for _, h in world.requests] == [None]  # just the release itself
    assert second["rain_events"]["events"][0]["id"] == first["rain_events"]["events"][0]["id"]


@pytest.mark.asyncio
async def test_rv_failed_fill_stops_the_round_and_warns_once(make_coordinator, caplog) -> None:
    rain = _rain_between("13:30", "15:00")
    missing = {DAY_RV.replace(hour=13, minute=55)}
    world = _RVWorld(rain, missing=missing)
    coord = _rv_tracked(make_coordinator)

    data, _ = await _rv_release(coord, world, "14:00")
    # Newest first: 13:55 fails, and the older steps wait for the next round.
    assert data["rain_events"]["steps"][:11] == [None] * 11
    await _rv_release(coord, world, "14:05")

    warnings = [r for r in caplog.records if "to fill the rain_events history" in r.message]
    assert len(warnings) == 1
    assert "nothing is wrong with your setup" in warnings[0].message
    # The RV sensors themselves are unaffected.
    assert data["max_060"] == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_rv_unreadable_fill_asks_for_a_report(make_coordinator, caplog) -> None:
    """A file that arrived but does not hold the expected window is not DWD
    being late, so the warning must not say so."""
    world = _RVWorld(
        _rain_between("13:30", "15:00"), garbled={DAY_RV.replace(hour=13, minute=55)}
    )
    await _rv_release(_rv_tracked(make_coordinator), world, "14:00")

    warnings = [r for r in caplog.records if "to fill the rain_events history" in r.message]
    assert len(warnings) == 1
    assert "Could not read" in warnings[0].message
    assert "please report it" in warnings[0].message
    assert "nothing is wrong with your setup" not in warnings[0].message


@pytest.mark.asyncio
async def test_rv_fill_budget_running_out_is_not_a_failure(make_coordinator, caplog) -> None:
    world = _RVWorld(_rain_between("13:30", "15:00"), delay=0.05)
    coord = _rv_tracked(make_coordinator)
    with patch.object(rain_events_tracker, "RAIN_FILL_BUDGET", timedelta(seconds=0.12)):
        data, _ = await _rv_release(coord, world, "14:00")

    steps = data["rain_events"]["steps"][:11]
    assert 0 < steps.count(None) < 11  # filled some, newest first, then stopped
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not coord._rain_tracker.fill_latch.failing


@pytest.mark.asyncio
async def test_rv_fill_runs_after_the_refresh(make_coordinator) -> None:
    """Setup waits for the RV refresh; the fill must not hold it."""
    world = _RVWorld(_rain_between("13:30", "14:10"))
    coord = _rv_tracked(make_coordinator)

    data, _ = await _rv_refresh(coord, world, "14:00")

    assert data["rain_events"] is None  # nothing shown yet in this run
    assert data["max_060"] == pytest.approx(12.0)
    assert world.requests[0][1] is None  # the release itself came first
    # HA starts the background task eagerly, so its first range read may
    # already be out; but the refresh returned without waiting for it.
    assert not coord._rain_tracker.fill_task.done()

    with _serving(world):
        await coord._rain_tracker.fill_task
    assert coord.published == [coord.data.data["rain_events"]]
    assert coord.published[0]["history_complete"] is True


@pytest.mark.asyncio
async def test_rv_missed_release_keeps_the_previous_view_until_filled(make_coordinator) -> None:
    world = _RVWorld(_rain_between("13:30", "15:00"))
    coord = _rv_tracked(make_coordinator)
    await _rv_release(coord, world, "14:00")
    shown, _ = await _rv_release(coord, world, "14:05")
    assert coord._rain_tracker.fill_task.done()  # 14:05 needed no fill

    # 14:10 never arrived; 14:15 has a step to fill.
    data, _ = await _rv_refresh(coord, world, "14:15")
    assert data["rain_events"] is shown["rain_events"]

    with _serving(world):
        await coord._rain_tracker.fill_task
    assert coord.data.data["rain_events"]["base"] == "2026-10-12T14:15:00+00:00"
    assert coord.data.data["rain_events"]["history_complete"] is True


@pytest.mark.asyncio
async def test_rv_releases_queue_behind_a_running_fill(make_coordinator) -> None:
    """A release must never reach the tracker before an older one."""
    world = _RVWorld(_rain_between("13:30", "15:00"))
    coord = _rv_tracked(make_coordinator)
    await _rv_refresh(coord, world, "14:00")
    first = coord._rain_tracker.fill_task
    await _rv_refresh(coord, world, "14:05")
    assert coord._rain_tracker.fill_task is not first

    with _serving(world):
        await coord._rain_tracker.fill_task
    assert first.done()
    # Only the newest release published; the tracker saw both, in order.
    assert [v["base"] for v in coord.published] == ["2026-10-12T14:05:00+00:00"]
    assert coord._rain_tracker.state.base == DAY_RV.replace(hour=14, minute=5)
    assert coord.published[0]["events"][0]["id"] == "20261012t1400-0"


@pytest.mark.asyncio
async def test_rv_state_survives_a_restart_through_the_store(make_coordinator) -> None:
    world = _RVWorld(_rain_between("13:30", "15:00"))
    store = _FakeStore()
    first, _ = await _rv_release(_rv_tracked(make_coordinator, store), world, "14:00")

    restarted = _rv_tracked(make_coordinator, _FakeStore(store.data))
    world.requests.clear()
    after, _ = await _rv_release(restarted, world, "14:20")

    assert after["rain_events"]["events"][0]["id"] == first["rain_events"]["events"][0]["id"]
    # Only the 20 minutes of downtime are filled.
    assert len([h for _, h in world.requests if h]) == 3


@pytest.mark.asyncio
async def test_rv_saves_promptly_only_while_something_is_at_stake(make_coordinator) -> None:
    from custom_components.dwd_precipitation.rain_events_tracker import (
        RAIN_IDLE_SAVE_DELAY,
        RAIN_SAVE_DELAY,
    )

    store = _FakeStore()
    coord = _rv_tracked(make_coordinator, store)
    await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
    assert store.delays[-1] == RAIN_IDLE_SAVE_DELAY.total_seconds()

    await _rv_release(coord, _RVWorld(_rain_between("15:00", "15:10")), "14:05")
    assert store.delays[-1] == RAIN_SAVE_DELAY.total_seconds()


@pytest.mark.asyncio
async def test_rv_unreadable_store_starts_over(make_coordinator, caplog) -> None:
    coord = _rv_tracked(make_coordinator, _FakeStore({"measured_start": "not a time", "measured": [1.0]}))
    data, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
    assert data["rain_events"]["schema"] == 1
    assert any("Discarding the saved rain_events state" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_rv_store_that_cannot_be_loaded_starts_over(make_coordinator, caplog) -> None:
    """A store HA cannot load (another version, say) is discarded, not retried."""

    class _Unloadable(_FakeStore):
        async def async_load(self):
            raise NotImplementedError("stored version 2, expected 1")

    coord = _rv_tracked(make_coordinator, _Unloadable())
    data, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
    second, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:05")

    assert data["rain_events"]["schema"] == 1
    assert second["rain_events"]["schema"] == 1
    discarded = [r for r in caplog.records if "Discarding the saved" in r.message]
    assert len(discarded) == 1


@pytest.mark.asyncio
async def test_rv_tracker_failure_leaves_the_sensors_alone(make_coordinator, caplog) -> None:
    coord = _rv_tracked(make_coordinator)
    with patch.object(rain_events_tracker, "update_rain_events", side_effect=RuntimeError("bug")):
        data, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
    assert data["rain_events"] is None
    assert data["max_060"] == 0.0
    assert any("Could not update the Rain events sensor" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_rv_new_release_hook_does_not_raise(make_coordinator, caplog) -> None:
    """Metadata without the series fails the tracker, not the RV update."""
    coord = _rv_tracked(make_coordinator)
    data: dict = {}
    await coord._async_on_new_release(
        DAY_RV, data, {"rain_within_2h": products.ProductMetadata("RV", DAY_RV)}
    )
    assert data["rain_events"] is None
    assert any("Could not update the Rain events sensor" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_rv_fetching_a_past_release_leaves_the_tracker_alone(make_coordinator) -> None:
    """async_fetch_release (the totals' backfill path) has no side effects."""
    world = _RVWorld(_rain_between("13:30", "15:00"))
    coord = _rv_tracked(make_coordinator)
    with _serving(world):
        cdata = await coord.async_fetch_release(DAY_RV.replace(hour=14))

    assert cdata.data["max_060"] == pytest.approx(12.0)
    assert "rain_events" not in cdata.data
    assert coord._rain_tracker.state is None
    assert coord._rain_tracker.fill_task is None


@pytest.mark.asyncio
async def test_rv_threshold_option_sets_the_wet_step(make_coordinator) -> None:
    coord = _rv_tracked(make_coordinator, options={"rain_event_threshold": 0.6})
    data, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
    assert data["rain_events"]["wet_step_mm"] == 0.05


def test_rs_next_120_needs_both_forecast_hours() -> None:
    """Half a forecast is not a 120-minute total: a missing hour makes it None."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    meta = products.ProductMetadata(source_product="RS", source_timestamp=ts)

    assert products._next_120(0.1, 0.2, meta, meta)[0] == pytest.approx(0.3)
    assert products._next_120(0.1, 0.2, meta, meta)[0] == 0.3  # rounded, not 0.30000000000000004
    assert products._next_120(None, 0.2, meta, meta) == (None, None)
    assert products._next_120(0.1, None, meta, meta) == (None, None)
    assert products._next_120(0.0, 0.0, meta, meta)[0] == 0.0


@pytest.mark.parametrize(
    ("cls", "url"),
    [
        (RadvorRS, "https://opendata.dwd.de/weather/radar/composite/rs/composite_rs_20261012_0740.tar"),
        (RadvorRV, "https://opendata.dwd.de/weather/radar/composite/rv/composite_rv_20261012_0740.tar"),
        (HymecNG, "https://opendata.dwd.de/weather/radar/composite/hymecng/composite_HymecNG_20261012_0740_000-hd5"),
        (RadolanRW, "https://opendata.dwd.de/weather/radar/radolan/rw/raa01-rw_10000-2610120740-dwd---bin.hdf5"),
        (products.RadolanRW10, "https://opendata.dwd.de/weather/radar/radolan/rw/raa01-rw_10000-2610120740-dwd---bin.hdf5"),
        (RadolanSF, "https://opendata.dwd.de/weather/radar/radolan/sf/raa01-sf_10000-2610120740-dwd---bin.hdf5"),
        (products.RadolanSFLastYesterday, "https://opendata.dwd.de/weather/radar/radolan/sf/raa01-sf_10000-2610120740-dwd---bin.hdf5"),
    ],
)
async def test_every_product_fetches_the_file_dwd_publishes(make_coordinator, cls, url) -> None:
    """The URLs, spelled out: radar/urls.py must not move any of them."""
    ts = datetime(2026, 10, 12, 7, 40, tzinfo=timezone.utc)
    assert make_coordinator(cls)._get_url(ts) == url


def test_every_product_class_has_a_url() -> None:
    from custom_components.dwd_precipitation import PRODUCT_CLASSES
    from custom_components.dwd_precipitation.radar.urls import PRODUCT_URLS

    assert {cls.PRODUCT_KEY for cls in PRODUCT_CLASSES} == set(PRODUCT_URLS)


@pytest.mark.asyncio
async def test_products_reading_the_same_file_download_it_once(make_coordinator) -> None:
    """RW's :00 run is one of RW-10min's; one download serves both."""
    from custom_components.dwd_precipitation.utils import DownloadCache

    ts = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    content = (Path(__file__).parents[1] / "fixtures" / "radolan_rw_sample.hdf5").read_bytes()
    downloads: list[str] = []

    async def fake_get(url, _client, **_kw):
        downloads.append(url)
        await asyncio.sleep(0)
        return AsyncResponse(content=content)

    cache = DownloadCache(ttl=300)
    rw, rw10, rs = make_coordinator(RadolanRW), make_coordinator(products.RadolanRW10), make_coordinator(RadvorRS)
    for coord in (rw, rw10, rs):
        coord.download_cache = cache
    with patch.object(products, "async_get", side_effect=fake_get):
        hourly, sliding = await asyncio.gather(
            rw._fetch_and_parse(ts), rw10._fetch_and_parse(ts)
        )
        await rw10._fetch_and_parse(ts)  # later: still within the TTL
    assert downloads == [rw._get_url(ts)]
    assert hourly[0] == sliding[0]
    # RADVOR archives are not shared, so they never sit in the cache.
    assert not RadvorRS.SHARES_FILES and not RadvorRV.SHARES_FILES
