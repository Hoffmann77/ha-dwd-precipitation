"""Product metadata-derivation tests — real _fetch_and_parse with mocked I/O.

Needs the ha-test dependency group installed (products.py imports HA transitively).
"""

from __future__ import annotations

import bz2
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from types import SimpleNamespace

from custom_components.dwd_precipitation import products
from custom_components.dwd_precipitation.products import RadolanRW, RadvorRS, RadvorRV
from custom_components.dwd_precipitation.utils import AsyncResponse

from tests.factories.odim import make_rs_tar, make_rv_tar


@pytest.mark.asyncio
async def test_rs_fetch_derives_base_source_timestamp_and_window() -> None:
    """RS: source_timestamp is the base run time (data_end - lead), identical for all leads.

    The ODIM enddate/endtime advances with the lead time, so the previous code
    (which used it directly) was only correct for the 0-min member.
    """
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    # /dataset/what per member — the validity window advances by the lead time.
    whats = [
        {"prodname": "RS", "startdate": "20260518", "starttime": "150000",
         "enddate": "20260518", "endtime": "160000"},
        {"prodname": "RS", "startdate": "20260518", "starttime": "160000",
         "enddate": "20260518", "endtime": "170000"},
        {"prodname": "RS", "startdate": "20260518", "starttime": "170000",
         "enddate": "20260518", "endtime": "180000"},
    ]
    grid = np.zeros((1200, 1100), dtype=np.float32)
    reads = iter([(grid, w) for w in whats])

    coord = RadvorRS.__new__(RadvorRS)
    coord.async_client = object()
    coord.coords = (51.05, 13.73)

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_rs_tar(ts))),
        ),
        patch.object(products, "read_odim_composite", side_effect=lambda _f: next(reads)),
    ):
        _data, meta = await coord._fetch_and_parse(ts)

    base = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    assert [m.source_timestamp for m in meta] == [base, base, base]
    assert [m.lead_time_minutes for m in meta] == [0, 60, 120]
    assert meta[0].data_start == datetime(2026, 5, 18, 15, 0, tzinfo=timezone.utc)
    assert meta[0].data_end == base
    assert meta[2].data_start == datetime(2026, 5, 18, 17, 0, tzinfo=timezone.utc)
    assert meta[2].data_end == datetime(2026, 5, 18, 18, 0, tzinfo=timezone.utc)


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
    """RV: hourly buckets, start/end detection, and per-bucket 5-min samples."""
    ts = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    # Scenario: dry now, rain at leads 30..60 (1.0 mm each), dry afterwards.
    leads = list(range(0, 121, 5))
    values = {lead: (1.0 if 30 <= lead <= 60 else 0.0) for lead in leads}
    reads = iter([
        (np.full((1200, 1100), values[lead], dtype=np.float32), _rv_what(ts, lead))
        for lead in leads
    ])

    coord = RadvorRV.__new__(RadvorRV)
    coord.async_client = object()
    coord.coords = (51.05, 13.73)
    coord.config_entry = SimpleNamespace(options={})

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_rv_tar(ts))),
        ),
        patch.object(products, "read_odim_composite", side_effect=lambda _f: next(reads)),
    ):
        data, meta = await coord._fetch_and_parse(ts)

    # 7 raining members (leads 30..60) fall in the first hour bucket.
    assert data["rv_060"] == pytest.approx(7.0)
    assert data["rv_120"] == pytest.approx(0.0)
    # Peak intensity: 1.0 mm/5min → 12 mm/h in hour 1; hour 2 is dry.
    assert data["max_060"] == pytest.approx(12.0)
    assert data["max_120"] == pytest.approx(0.0)
    # Dry now → rain starts at lead 30 (25 min out); ends at lead 65 boundary (60 min out).
    assert data["start_in"] == 25
    assert data["start_at"] == datetime(2026, 7, 16, 20, 55, tzinfo=timezone.utc)
    assert data["end_in"] == 60
    assert data["end_at"] == datetime(2026, 7, 16, 21, 30, tzinfo=timezone.utc)
    # Rain occurs within the horizon → the "rain expected" flag is set.
    assert data["rain_within_2h"] is True

    # Base run time and bucket metadata.
    assert meta["rv_060"].source_timestamp == ts
    assert meta["rv_060"].lead_time_minutes == 60
    assert meta["rv_060"].data_start == datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    assert meta["rv_060"].data_end == datetime(2026, 7, 16, 21, 30, tzinfo=timezone.utc)

    # Per-bucket 5-min samples: 12 points, last one is lead 60.
    samples = meta["rv_060"].samples
    assert len(samples) == 12
    assert samples[-1]["lead"] == 60
    assert samples[-1]["value"] == pytest.approx(1.0)
    assert samples[-1]["intensity"] == pytest.approx(12.0)
    assert samples[0]["lead"] == 5
    assert samples[0]["value"] == pytest.approx(0.0)
    assert samples[0]["intensity"] == pytest.approx(0.0)

    # The max-intensity sensors reuse the hourly bucket metadata (same samples).
    assert meta["max_060"] is meta["rv_060"]
    assert meta["max_120"] is meta["rv_120"]


@pytest.mark.asyncio
async def test_rv_threshold_from_options_suppresses_light_rain() -> None:
    """RV: light rain below the configured mm/h threshold does not trigger start/end."""
    ts = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    leads = list(range(0, 121, 5))
    values = {lead: (0.2 if lead >= 30 else 0.0) for lead in leads}  # 0.2 mm/5min = 2.4 mm/h
    reads = iter([
        (np.full((1200, 1100), values[lead], dtype=np.float32), _rv_what(ts, lead))
        for lead in leads
    ])

    coord = RadvorRV.__new__(RadvorRV)
    coord.async_client = object()
    coord.coords = (51.05, 13.73)
    # Threshold is now an intensity (mm/h); 2.4 mm/h < 3.0 mm/h → suppressed.
    coord.config_entry = SimpleNamespace(options={"rain_threshold": 3.0})

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_rv_tar(ts))),
        ),
        patch.object(products, "read_odim_composite", side_effect=lambda _f: next(reads)),
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
        (np.full((1200, 1100), values[lead], dtype=np.float32), _rv_what(ts, lead))
        for lead in leads
    ])

    coord = RadvorRV.__new__(RadvorRV)
    coord.async_client = object()
    coord.coords = (51.05, 13.73)
    # 6 mm/h → 0.5 mm/5min gate: 4.8 mm/h is dry, 7.2 mm/h counts.
    coord.config_entry = SimpleNamespace(options={"rain_threshold": 6.0})

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_rv_tar(ts))),
        ),
        patch.object(products, "read_odim_composite", side_effect=lambda _f: next(reads)),
    ):
        data, _meta = await coord._fetch_and_parse(ts)

    # Only the 7.2 mm/h step at lead 60 crosses the gate → start 55 min out.
    assert data["start_in"] == 55
    assert data["rain_within_2h"] is True


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

    coord = RadolanRW.__new__(RadolanRW)
    coord.async_client = object()
    coord.coords = (51.05, 13.73)

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
