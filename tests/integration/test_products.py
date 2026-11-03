"""What every product shares: the files it fetches, and shared downloads."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from custom_components.dwd_precipitation import products
from custom_components.dwd_precipitation.products import (
    HymecNG,
    RadolanRW,
    RadolanSF,
    RadvorRS,
    RadvorRV,
)
from custom_components.dwd_precipitation.utils import AsyncResponse


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
    rw, rw10 = make_coordinator(RadolanRW), make_coordinator(products.RadolanRW10)
    for coord in (rw, rw10):
        coord.download_cache = cache
    with patch.object(products, "async_get", side_effect=fake_get):
        hourly, sliding = await asyncio.gather(
            rw._fetch_and_parse(ts), rw10._fetch_and_parse(ts)
        )
        await rw10._fetch_and_parse(ts)  # later: still within the TTL
    assert downloads == [rw._get_url(ts)]
    assert hourly[0] == sliding[0]
    # The multi-MB RADVOR archives are not shared, so they never sit in it.
    assert not any(getattr(cls, "SHARES_FILES", False) for cls in (RadvorRS, RadvorRV))
