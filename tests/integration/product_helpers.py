"""Shared helpers of the product tests: fake ODIM metadata and fetch runners."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import numpy as np

from custom_components.dwd_precipitation import products
from custom_components.dwd_precipitation.products import RadvorRS, RadvorRV
from custom_components.dwd_precipitation.utils import AsyncResponse

from tests.factories.radvor import make_radvor_tar


def executor_jobs(coord):
    """Count the executor jobs the coordinator hands to hass."""
    return patch.object(
        coord.hass, "async_add_executor_job", wraps=coord.hass.async_add_executor_job
    )


def rs_what(base: datetime, lead: int) -> dict:
    """ODIM /dataset/what for an RS member: rolling hour [T+lead-60, T+lead]."""
    end = base + timedelta(minutes=lead)
    start = end - timedelta(minutes=60)
    return {
        "prodname": "RS",
        "startdate": start.strftime("%Y%m%d"), "starttime": start.strftime("%H%M%S"),
        "enddate": end.strftime("%Y%m%d"), "endtime": end.strftime("%H%M%S"),
    }


async def rs_fetch(make_coordinator, ts: datetime, values: dict[int, float]):
    """Run RadvorRS._fetch_and_parse, serving each decoded lead from ``values``."""
    decoded: list[int] = []

    def _read(fileobj, _row, _col, **_kw):
        lead = int(fileobj.getvalue())  # make_radvor_tar's payload is the lead
        decoded.append(lead)
        return np.float32(values[lead]), rs_what(ts, lead)

    coord = make_coordinator(RadvorRS)

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rs", ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=_read),
        executor_jobs(coord) as jobs,
    ):
        data, meta = await coord._fetch_and_parse(ts)
    # The decode runs off the loop, and so does unpacking the archive, which
    # this server sends whole instead of the ranges asked for.
    assert jobs.call_count == 2
    return data, meta, decoded


def rv_what(base: datetime, lead: int) -> dict:
    """ODIM /dataset/what for an RV member: 5-min window [T+lead-5, T+lead]."""
    end = base + timedelta(minutes=lead)
    start = end - timedelta(minutes=5)
    return {
        "prodname": "RV_top_view",
        "startdate": start.strftime("%Y%m%d"), "starttime": start.strftime("%H%M%S"),
        "enddate": end.strftime("%Y%m%d"), "endtime": end.strftime("%H%M%S"),
    }


async def rv_fetch(
    make_coordinator, ts: datetime, values: dict[int, float | None], coord=None
):
    """Run RadvorRV._fetch_and_parse, serving each lead from ``values`` (None = nodata).

    On ``coord`` if given, so a test can feed one coordinator several releases.
    """
    def _read(fileobj, _row, _col, **_kw):
        lead = int(fileobj.getvalue())  # make_radvor_tar's payload is the lead
        value = values[lead]
        return np.float32("nan" if value is None else value), rv_what(ts, lead)

    coord = coord or make_coordinator(RadvorRV)
    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rv", ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=_read),
        executor_jobs(coord) as jobs,
    ):
        data, meta = await coord._fetch_and_parse(ts)
    assert jobs.call_count == 1
    return data, meta
