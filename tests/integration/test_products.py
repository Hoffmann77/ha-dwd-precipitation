"""Product metadata-derivation tests — real _fetch_and_parse with mocked I/O.

Needs the ha-test dependency group installed (products.py imports HA transitively).
"""

from __future__ import annotations

import bz2
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from types import SimpleNamespace

from custom_components.dwd_precipitation import products
from custom_components.dwd_precipitation.products import (
    HymecNG,
    RadolanRW,
    RadolanSF,
    RadvorRS,
    RadvorRV,
)
from custom_components.dwd_precipitation.radar import RS_GRID_SHAPE
from custom_components.dwd_precipitation.utils import AsyncResponse

from tests.factories.odim import make_hymecng_h5, make_rs_tar, make_rv_tar


class _FakeHass:
    """Stands in for hass: runs executor jobs inline and counts them."""

    def __init__(self) -> None:
        self.executor_jobs = 0

    async def async_add_executor_job(self, target, *args):
        self.executor_jobs += 1
        return target(*args)


def _coord(cls, options: dict | None = None):
    """Build a product coordinator without HA's constructor."""
    coord = cls.__new__(cls)
    coord.hass = _FakeHass()
    coord.async_client = object()
    coord.coords = (51.05, 13.73)
    coord.config_entry = SimpleNamespace(options=options or {})
    return coord



def _rs_what(base: datetime, lead: int) -> dict:
    """ODIM /dataset/what for an RS member: rolling hour [T+lead-60, T+lead]."""
    end = base + timedelta(minutes=lead)
    start = end - timedelta(minutes=60)
    return {
        "prodname": "RS",
        "startdate": start.strftime("%Y%m%d"), "starttime": start.strftime("%H%M%S"),
        "enddate": end.strftime("%Y%m%d"), "endtime": end.strftime("%H%M%S"),
    }


async def _rs_fetch(ts: datetime, values: dict[int, float], full: bool = True):
    """Run RadvorRS._fetch_and_parse, serving each decoded lead from ``values``."""
    decoded: list[int] = []

    def _read(fileobj, _row, _col, **_kw):
        lead = int(fileobj.getvalue())  # make_rs_tar's payload is the lead
        decoded.append(lead)
        return np.float32(values[lead]), _rs_what(ts, lead)

    coord = _coord(RadvorRS, {"full_rolling_series": full})

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_rs_tar(ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=_read),
    ):
        data, meta = await coord._fetch_and_parse(ts)
    assert coord.hass.executor_jobs == 1
    return data, meta, decoded


@pytest.mark.asyncio
async def test_rs_fetch_derives_base_source_timestamp_and_window() -> None:
    """RS: source_timestamp is the base run time (data_end - lead), identical for all leads.

    The ODIM enddate/endtime advances with the lead time, so the previous code
    (which used it directly) was only correct for the 0-min member.
    """
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    data, meta, _ = await _rs_fetch(ts, {lead: float(lead) for lead in range(0, 121, 5)})

    # The three non-overlapping hours come from leads 0 / 60 / 120.
    assert data[:3] == [0.0, 60.0, 120.0]
    base = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    assert [m.source_timestamp for m in meta] == [base, base, base, base]
    assert [m.lead_time_minutes for m in meta[:3]] == [0, 60, 120]
    assert meta[0].data_start == datetime(2026, 5, 18, 15, 0, tzinfo=timezone.utc)
    assert meta[0].data_end == base
    assert meta[2].data_start == datetime(2026, 5, 18, 17, 0, tzinfo=timezone.utc)
    assert meta[2].data_end == datetime(2026, 5, 18, 18, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_rs_peak_hour_and_rolling_series() -> None:
    """RS: the wettest future rolling hour, its window, and the 25-point series."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    # A storm straddling the fixed hours: its heaviest hour ends at T+90, which
    # neither "next 1h" (lead 60) nor "next 1-2h" (lead 120) sees in full.
    values = {lead: 0.0 for lead in range(0, 121, 5)}
    values.update({0: 30.0, 60: 4.0, 85: 9.0, 90: 18.0, 95: 18.0, 120: 5.0})
    data, meta, _ = await _rs_fetch(ts, values)

    # Lead 0 (the past hour, 30 mm) is not a forecast and is excluded; the tie
    # between leads 90 and 95 goes to the earlier window.
    assert data[3] == pytest.approx(18.0)
    peak = meta[3]
    assert peak.lead_time_minutes == 90
    assert peak.data_start == datetime(2026, 5, 18, 16, 30, tzinfo=timezone.utc)
    assert peak.data_end == datetime(2026, 5, 18, 17, 30, tzinfo=timezone.utc)
    assert peak.source_timestamp == ts

    series = peak.rolling_1h
    assert [p["lead"] for p in series] == list(range(0, 121, 5))
    assert series[0] == {
        "lead": 0,
        "start": "2026-05-18T15:00:00+00:00",
        "end": "2026-05-18T16:00:00+00:00",
        "value": pytest.approx(30.0),
    }
    assert series[18]["value"] == pytest.approx(18.0)  # lead 90
    # The fixed-hour members keep no series of their own.
    assert all(m.rolling_1h is None for m in meta[:3])


@pytest.mark.asyncio
async def test_rs_dry_forecast_has_no_peak_window() -> None:
    """RS: a dry forecast peaks at 0 mm, but has no wettest hour to point at."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    data, meta, _ = await _rs_fetch(ts, {lead: 0.0 for lead in range(0, 121, 5)})

    assert data[3] == 0.0
    assert meta[3].data_start is None
    assert meta[3].data_end is None
    assert meta[3].lead_time_minutes is None
    assert len(meta[3].rolling_1h) == 25


@pytest.mark.asyncio
async def test_rs_without_option_decodes_only_the_three_hours() -> None:
    """RS: with the option off only leads 0/60/120 are decoded; RV owns the peak."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    values = {lead: float(lead) for lead in range(0, 121, 5)}
    data, meta, decoded = await _rs_fetch(ts, values, full=False)

    assert decoded == [0, 60, 120]
    assert data == [0.0, 60.0, 120.0, None]
    assert meta[3] is None
    assert [m.lead_time_minutes for m in meta[:3]] == [0, 60, 120]


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
async def test_rv_fetch_derives_buckets_and_timing() -> None:
    """RV: peak intensity, start/end detection, and the raw 5-min series."""
    ts = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    # Scenario: dry now, rain at leads 30..60 (1.0 mm each), dry afterwards.
    leads = list(range(0, 121, 5))
    values = {lead: (1.0 if 30 <= lead <= 60 else 0.0) for lead in leads}
    reads = iter([
        (np.float32(values[lead]), _rv_what(ts, lead))
        for lead in leads
    ])

    coord = _coord(RadvorRV)

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_rv_tar(ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=lambda _f, _r, _c, **_kw: next(reads)),
    ):
        data, meta = await coord._fetch_and_parse(ts)

    # Peak intensity: 1.0 mm/5min → 12 mm/h in hour 1; hour 2 is dry.
    assert data["max_060"] == pytest.approx(12.0)
    assert data["max_120"] == pytest.approx(0.0)
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
async def test_rv_threshold_from_options_suppresses_light_rain() -> None:
    """RV: light rain below the configured mm/h threshold does not trigger start/end."""
    ts = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    leads = list(range(0, 121, 5))
    values = {lead: (0.2 if lead >= 30 else 0.0) for lead in leads}  # 0.2 mm/5min = 2.4 mm/h
    reads = iter([
        (np.float32(values[lead]), _rv_what(ts, lead))
        for lead in leads
    ])

    coord = _coord(RadvorRV)
    # Threshold is now an intensity (mm/h); 2.4 mm/h < 3.0 mm/h → suppressed.
    coord.config_entry = SimpleNamespace(options={"precipitation_threshold": 3.0})

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_rv_tar(ts))),
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
async def test_rv_threshold_is_interpreted_as_mm_per_hour() -> None:
    """RV: the mm/h threshold is divided by 12 before comparison to 5-min values."""
    ts = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    leads = list(range(0, 121, 5))
    # Dry now; 0.4 mm/5min (=4.8 mm/h) at lead 30, 0.6 mm/5min (=7.2 mm/h) at lead 60.
    values = {lead: 0.0 for lead in leads}
    values[30] = 0.4
    values[60] = 0.6
    reads = iter([
        (np.float32(values[lead]), _rv_what(ts, lead))
        for lead in leads
    ])

    coord = _coord(RadvorRV)
    # 6 mm/h → 0.5 mm/5min gate: 4.8 mm/h is dry, 7.2 mm/h counts.
    coord.config_entry = SimpleNamespace(options={"precipitation_threshold": 6.0})

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_rv_tar(ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=lambda _f, _r, _c, **_kw: next(reads)),
    ):
        data, _meta = await coord._fetch_and_parse(ts)

    # Only the 7.2 mm/h step at lead 60 crosses the gate → start 55 min out.
    assert data["start_in"] == 55
    assert data["rain_within_2h"] is True


@pytest.mark.asyncio
async def test_rv_end_algorithm_option_selects_clearing() -> None:
    """RV: the clearing algorithm looks past a lull to the last forecast wave."""
    ts = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    leads = list(range(0, 121, 5))
    # Dry now; a wave at lead 10, a lull, then a second wave at lead 60.
    values = {lead: (1.0 if lead in (10, 60) else 0.0) for lead in leads}

    def _make_reads():
        return iter([
            (np.float32(values[lead]), _rv_what(ts, lead))
            for lead in leads
        ])

    coord = _coord(RadvorRV)

    # Default (episode): ends at the first lull after the lead-10 wave.
    coord.config_entry = SimpleNamespace(options={})
    episode_reads = _make_reads()
    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_rv_tar(ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=lambda _f, _r, _c, **_kw: next(episode_reads)),
    ):
        episode, _ = await coord._fetch_and_parse(ts)
    assert episode["start_in"] == 5
    assert episode["end_in"] == 10

    # Clearing: waits out the lull to the boundary after the lead-60 wave.
    coord.config_entry = SimpleNamespace(options={"precipitation_end_algorithm": "clearing"})
    clearing_reads = _make_reads()
    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_rv_tar(ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=lambda _f, _r, _c, **_kw: next(clearing_reads)),
    ):
        clearing, _ = await coord._fetch_and_parse(ts)
    assert clearing["start_in"] == 5
    assert clearing["end_in"] == 60
    assert clearing["end_at"] == datetime(2026, 7, 16, 21, 30, tzinfo=timezone.utc)


def _hymecng_reader(class_value: int, nodata: int = 255, undetect: int = 254):
    """Return a fake read_odim_classification yielding a uniform class grid."""
    raw = np.full(RS_GRID_SHAPE, class_value, dtype=np.uint8)
    dataset_what = {
        "prodname": "HymecNG_top_view",
        "product": "COMP",
        "startdate": "20260729", "starttime": "173000",
        "enddate": "20260729", "endtime": "173000",
    }
    moment_what = {"quantity": "CLASS", "nodata": float(nodata), "undetect": float(undetect)}
    return lambda _f, **_kw: (raw, dataset_what, moment_what)


@pytest.mark.asyncio
async def test_hymecng_fetch_maps_class_index_to_label() -> None:
    """HymecNG: end-to-end fetch + real reader maps the cell class to a label."""
    ts = datetime(2026, 7, 29, 17, 30, tzinfo=timezone.utc)
    hd5 = make_hymecng_h5(shape=RS_GRID_SHAPE, fill=7)  # SNOW everywhere

    coord = _coord(HymecNG)

    get_mock = AsyncMock(return_value=AsyncResponse(content=hd5.getvalue()))
    with patch.object(products, "async_get", new=get_mock):
        data, meta = await coord._fetch_and_parse(ts)

    assert data == "snow"
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
async def test_hymecng_class_and_sentinel_mapping(class_value, expected) -> None:
    """HymecNG: class indices, undetect, and nodata map to the right sensor state."""
    ts = datetime(2026, 7, 29, 17, 30, tzinfo=timezone.utc)
    coord = _coord(HymecNG)

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=b"x")),
        ),
        patch.object(
            products, "read_odim_classification", side_effect=_hymecng_reader(class_value)
        ),
    ):
        data, _meta = await coord._fetch_and_parse(ts)

    assert data == expected


@pytest.mark.asyncio
async def test_radolan_fetch_derives_window_from_interval() -> None:
    """RADOLAN: data_end == nominal datetime, data_start == datetime - intervalseconds."""
    ts = datetime(2025, 6, 1, 12, 50, tzinfo=timezone.utc)
    raw = {
        "producttype": "RW",
        "datetime": datetime(2025, 6, 1, 12, 50, tzinfo=timezone.utc),
        "intervalseconds": 3600,
    }
    grid = np.zeros((900, 900), dtype=np.float32)

    coord = _coord(RadolanRW)

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=bz2.compress(b"x"))),
        ),
        patch.object(products, "read_radolan_composite", return_value=(grid, raw)),
    ):
        _value, meta = await coord._fetch_and_parse(ts)

    assert meta.source_timestamp == datetime(2025, 6, 1, 12, 50, tzinfo=timezone.utc)
    assert meta.data_end == datetime(2025, 6, 1, 12, 50, tzinfo=timezone.utc)
    assert meta.data_start == datetime(2025, 6, 1, 11, 50, tzinfo=timezone.utc)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cell_value", "expected"),
    [
        (-9999.0, None),   # the reader's nodataflag: radar outage / masked cell
        (np.nan, None),
        (0.0, 0.0),        # dry is a real reading, not missing
        (1.7, 1.7),
    ],
)
async def test_radolan_nodata_cell_reads_as_none(cell_value, expected) -> None:
    """RADOLAN nodata becomes None (sensor unknown), never -9999 mm."""
    ts = datetime(2025, 6, 1, 12, 50, tzinfo=timezone.utc)
    raw = {
        "producttype": "RW",
        "datetime": ts,
        "intervalseconds": 3600,
        "nodataflag": -9999,
    }
    coord = _coord(RadolanRW)
    grid = np.zeros((900, 900), dtype=np.float64)
    grid[coord.index] = cell_value

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=bz2.compress(b"x"))),
        ),
        patch.object(products, "read_radolan_composite", return_value=(grid, raw)),
    ):
        value, _meta = await coord._fetch_and_parse(ts)

    assert value == (pytest.approx(expected) if expected is not None else None)


_FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cls", "fixture"),
    [(RadolanRW, "radolan_rw_sample.bin.bz2"), (RadolanSF, "radolan_sf_sample.bin.bz2")],
)
async def test_radolan_real_file_nodata_reads_as_none(cls, fixture) -> None:
    """On a real DWD file, a cell outside radar coverage reads as None.

    The south-west corner of the 900 km grid lies in France, beyond the radars'
    range, so DWD flags it nodata; the real reader must not leak -9999.
    """
    content = (_FIXTURES / fixture).read_bytes()
    coord = _coord(cls)
    coord.coords = (46.9572, 3.5943)  # centre of cell (0, 0)
    assert coord.index == (0, 0)

    with patch.object(
        products, "async_get", new=AsyncMock(return_value=AsyncResponse(content=content))
    ):
        value, _meta = await coord._fetch_and_parse(datetime(2026, 7, 3, 6, 50, tzinfo=timezone.utc))

    assert value is None


async def _rv_fetch(ts: datetime, values: dict[int, float | None]):
    """Run RadvorRV._fetch_and_parse, serving each lead from ``values`` (None = missing member)."""
    def _read(fileobj, _row, _col, **_kw):
        lead = int(fileobj.getvalue())  # make_rv_tar's payload is the lead
        value = values[lead]
        return np.float32("nan" if value is None else value), _rv_what(ts, lead)

    coord = _coord(RadvorRV)
    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_rv_tar(ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=_read),
    ):
        data, meta = await coord._fetch_and_parse(ts)
    assert coord.hass.executor_jobs == 1
    return data, meta


@pytest.mark.asyncio
async def test_rv_peak_hour_matches_rs_for_the_same_rain() -> None:
    """RV-summed rolling hours give RS's peak, window and future series exactly.

    The two sources back one sensor, switched by an option, so the state must
    not move when a user flips it.
    """
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    leads = list(range(0, 121, 5))
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

    rv_data, rv_meta = await _rv_fetch(ts, rv)
    rs_data, rs_meta, _ = await _rs_fetch(ts, rs)

    assert rv_data["peak_1h"] == pytest.approx(rs_data[3])
    # Wettest hour ends at +95: steps +40..+95 catch the tail of the first
    # shower too (0.9 + 0.3), beating the window ending at +100 (5.6 mm).
    assert rv_data["peak_1h"] == pytest.approx(0.9 + 0.3 + 0.6 + 1.7 + 2.2)
    for attr in ("lead_time_minutes", "data_start", "data_end"):
        assert getattr(rv_meta["peak_1h"], attr) == getattr(rs_meta[3], attr), attr
    assert rv_meta["peak_1h"].lead_time_minutes == 95
    assert rv_meta["peak_1h"].data_start == datetime(2026, 5, 18, 16, 35, tzinfo=timezone.utc)
    assert rv_meta["peak_1h"].data_end == datetime(2026, 5, 18, 17, 35, tzinfo=timezone.utc)

    # RV's series is the 13 wholly-future hours, point for point equal to RS's.
    rv_series = rv_meta["peak_1h"].rolling_1h
    rs_series = {p["lead"]: p for p in rs_meta[3].rolling_1h}
    assert [p["lead"] for p in rv_series] == list(range(60, 121, 5))
    assert len(rs_series) == 25
    for point in rv_series:
        assert point == rs_series[point["lead"]]


@pytest.mark.asyncio
async def test_rv_peak_hour_treats_missing_step_as_dry() -> None:
    """RV: a missing 5-minute member counts as 0, as RS does at the coverage edge."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    rv: dict[int, float | None] = {lead: 0.0 for lead in range(0, 121, 5)}
    rv.update({5: None, 60: 1.0, 65: 2.0})
    data, meta = await _rv_fetch(ts, rv)

    assert data["peak_1h"] == pytest.approx(3.0)
    # Lead 5 opens the T+0..T+60 window; its start falls back to end - 60 min.
    first = meta["peak_1h"].rolling_1h[0]
    assert first == {
        "lead": 60,
        "start": "2026-05-18T16:00:00+00:00",
        "end": "2026-05-18T17:00:00+00:00",
        "value": pytest.approx(1.0),
    }
