"""Product metadata-derivation tests — real _fetch_and_parse with mocked I/O.

Needs the ha-test dependency group installed (products.py imports HA transitively).
"""

from __future__ import annotations

import bz2
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from custom_components.dwd_precipitation import products
from custom_components.dwd_precipitation.products import RadolanRW, RadvorRS
from custom_components.dwd_precipitation.utils import AsyncResponse

from tests.factories.odim import make_rs_tar


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
