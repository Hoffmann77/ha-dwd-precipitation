"""RADOLAN (RW, SF): the HDF5 edition, its window and nodata."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from custom_components.dwd_precipitation import products
from custom_components.dwd_precipitation.products import (
    RadolanRW,
    RadolanSF,
)
from custom_components.dwd_precipitation.utils import AsyncResponse


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
    """RADOLAN: the HDF5 URL, the cell at the location, and the window from ODIM what."""
    ts = datetime(2025, 6, 1, 12, 50, tzinfo=timezone.utc)
    coord = make_coordinator(cls)
    get = AsyncMock(return_value=AsyncResponse(content=b"hdf5"))
    read = patch.object(
        products,
        "read_odim_composite_at",
        return_value=(np.float32(1.7), _radolan_what(product, ts, hours)),
    )
    with patch.object(products, "async_get", new=get), read as reader:
        value, meta = await coord._fetch_and_parse(ts)

    url = get.call_args.args[0]
    assert url.endswith(f"/{product.lower()}/raa01-{product.lower()}_10000-2506011250-dwd---bin.hdf5")
    # The location goes to the reader, which finds it on the file's own grid.
    assert reader.call_args.args[1:] == coord.coords
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
            "read_odim_composite_at",
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
