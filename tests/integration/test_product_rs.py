"""RS (RADVOR rolling hours): fetch, range reads, payload."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np
import pytest

from custom_components.dwd_precipitation import products
from custom_components.dwd_precipitation.products import RadvorRS

from tests.factories.radvor import LEADS, RangeServer, make_radvor_tar
from tests.integration.product_helpers import (
    executor_jobs,
    rs_fetch,
    rs_what,
)


@pytest.mark.asyncio
async def test_rs_fetch_derives_base_source_timestamp_and_window(make_coordinator) -> None:
    """RS: source_timestamp is the base run time (data_end - lead), identical for all leads.

    The ODIM enddate/endtime advances with the lead time, so the previous code
    (which used it directly) was only correct for the 0-min member.
    """
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    data, meta, _ = await rs_fetch(make_coordinator, ts, {lead: float(lead) for lead in LEADS})

    # The three non-overlapping hours come from leads 0 / 60 / 120.
    assert [data["last_60"], data["next_60"], data["next_60_120"]] == [0.0, 60.0, 120.0]
    base = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    assert [m.source_timestamp for m in meta.values()] == [base] * 4
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
async def test_rs_decodes_only_the_three_hours(make_coordinator) -> None:
    """RS: only leads 0/60/120 are decoded; RV builds the peak hour."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    values = {lead: float(lead) for lead in LEADS}
    data, meta, decoded = await rs_fetch(make_coordinator, ts, values)

    assert decoded == [0, 60, 120]
    assert data == {"last_60": 0.0, "next_60": 60.0, "next_60_120": 120.0, "next_120": 180.0}
    assert [m.lead_time_minutes for m in (meta["last_60"], meta["next_60"], meta["next_60_120"])] == [0, 60, 120]
    assert all(m.rolling_1h is None for m in meta.values())


@pytest.mark.asyncio
async def test_rs_range_fallback_is_said_once_and_its_end_once(make_coordinator, caplog) -> None:
    """Whole archives instead of ranges: one WARNING per run, one INFO after."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    archive = make_radvor_tar("rs", ts)
    ignores_ranges = RangeServer(archive, ranges=False).async_get  # 200: the whole file
    serves_ranges = RangeServer(archive).async_get

    def _read(fileobj, _row, _col, **_kw):
        lead = int(fileobj.getvalue())
        return np.float32(lead), rs_what(ts, lead)

    coord = make_coordinator(RadvorRS)
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
@pytest.mark.parametrize("full_rolling_series", [False, True])
async def test_rs_reads_the_hours_by_range(make_coordinator, full_rolling_series) -> None:
    """RS asks for byte ranges instead of the whole archive, whatever the options.

    The full rolling-hour series is built from RV, so the option no longer
    makes RS download whole archives (~5x the data).
    """
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    server = RangeServer(make_radvor_tar("rs", ts))

    def _read(fileobj, _row, _col, **_kw):
        lead = int(fileobj.getvalue())
        return np.float32(lead), rs_what(ts, lead)

    coord = make_coordinator(RadvorRS, {"full_rolling_series": full_rolling_series})
    with (
        patch.object(products, "async_get", side_effect=server.async_get),
        patch.object(products, "read_odim_composite_cell", side_effect=_read),
        executor_jobs(coord) as jobs,
    ):
        data, _ = await coord._fetch_and_parse(ts)

    assert [data["last_60"], data["next_60"], data["next_60_120"]] == [0.0, 60.0, 120.0]
    # The test archive is tiny, so the first window already holds all three.
    assert len(server.requests) == 1
    assert server.requests[0]["Range"].startswith("bytes=0-")
    assert jobs.call_count == 1


def test_rs_next_120_needs_both_forecast_hours() -> None:
    """Half a forecast is not a 120-minute total: a missing hour makes it None."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    meta = products.ProductMetadata(source_product="RS", source_timestamp=ts)

    assert products._next_120(0.1, 0.2, meta, meta)[0] == pytest.approx(0.3)
    assert products._next_120(0.1, 0.2, meta, meta)[0] == 0.3  # rounded, not 0.30000000000000004
    assert products._next_120(None, 0.2, meta, meta) == (None, None)
    assert products._next_120(0.1, None, meta, meta) == (None, None)
    assert products._next_120(0.0, 0.0, meta, meta)[0] == 0.0
