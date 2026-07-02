"""DWD radar products."""

from __future__ import annotations

import bz2
import logging
import tarfile
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from functools import cached_property, lru_cache
from io import BytesIO

import numpy as np

from .coordinator import BaseProductUpdateCoordinator, ProductMetadata
from .utils import async_get
from .radar import read_radolan_composite, get_radolan_grid, read_odim_composite, get_rs_grid_index
from .const import DWD_RADOLAN_URL, DWD_COMPOSITE_URL

_LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _radolan_wgs84_grid() -> np.ndarray:
    """Return the cached 900×900 RADOLAN WGS84 lon/lat grid.

    Shared across all RADOLAN products, which use an identical grid.
    """
    return get_radolan_grid(wgs84=True)


def _utc(dt: datetime | None) -> datetime | None:
    """Ensure a datetime is UTC-aware; returns None for None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _parse_odim_ts(raw: dict) -> datetime | None:
    """Parse ODIM enddate/endtime fields into a UTC datetime."""
    date, time = raw.get("enddate"), raw.get("endtime")
    if not date or not time:
        return None
    try:
        return datetime.strptime(f"{date}{time}", "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class RadvorRS(BaseProductUpdateCoordinator):
    """DWD RS precipitation nowcast (RADVOR, ODIM_H5 format).

    Returns three lead times (0 / 60 / 120 min) from a single tar archive.
    precipitation → list[float | None], metadata → list[ProductMetadata]
    """

    PRODUCT_KEY = "rs"

    RELEASE_INTERVAL = timedelta(minutes=5)

    RELEASE_DELAY = timedelta(minutes=4, seconds=10)

    RELEASE_OFFSET = timedelta()

    @cached_property
    def index(self) -> tuple[int, int]:
        """Return (row, col) in the RS composite grid."""
        return get_rs_grid_index(*self.coords)

    def _get_url(self, ts: datetime) -> str:
        """Return the URL for the tar archive."""
        return (
            f"{DWD_COMPOSITE_URL}/rs/composite_rs_{ts.strftime('%Y%m%d_%H%M')}.tar"
        )

    async def _fetch_and_parse(self, ts: datetime) -> tuple[list, list]:
        """Fetch one tar archive and extract 3 lead-time ACRR values."""
        response = await async_get(self._get_url(ts), self.async_client)

        tar_bytes = BytesIO(response.content)
        prefix = f"composite_rs_{ts.strftime('%Y%m%d_%H%M')}"
        row, col = self.index
        data: list = []
        metadata: list = []

        with tarfile.open(fileobj=tar_bytes, mode="r") as tf:
            for suffix in ("000", "060", "120"):
                member_name = f"{prefix}_{suffix}-hd5"
                try:
                    f = tf.extractfile(member_name)
                except KeyError:
                    f = None
                if f is None:
                    _LOGGER.warning("RS tar member not found: %s", member_name)
                    data.append(None)
                    metadata.append(None)
                    continue

                _data, _what = read_odim_composite(BytesIO(f.read()))
                val = float(_data[row, col])
                data.append(None if np.isnan(val) else val)
                metadata.append(ProductMetadata(
                    source_product=_what.get("prodname") or _what.get("product"),
                    source_timestamp=_parse_odim_ts(_what),
                    lead_time_minutes=int(suffix),
                ))

        return data, metadata


class RadolanProduct(BaseProductUpdateCoordinator, ABC):
    """Abstract coordinator for bz2-compressed RADOLAN binary products.

    Concrete subclasses provide PRODUCT_KEY, timing constants, and get_url().
    precipitation → float, metadata → ProductMetadata

    """

    @cached_property
    def index(self) -> tuple[int, int]:
        """Return the nearest-cell (row, col) in the RADOLAN 900×900 WGS84 grid."""
        lat, lon = self.coords
        grid = _radolan_wgs84_grid()
        dist_sq = (grid[:, :, 1] - lat) ** 2 + (grid[:, :, 0] - lon) ** 2

        return np.unravel_index(np.argmin(dist_sq), dist_sq.shape)

    @abstractmethod
    def _get_url(self, ts: datetime) -> str:
        """Return the bz2 file URL for the given release timestamp."""

    async def _fetch_and_parse(self, ts: datetime) -> tuple[float, ProductMetadata]:
        """Fetch one bz2 RADOLAN file and return (scalar_value, ProductMetadata)."""
        response = await async_get(self._get_url(ts), self.async_client)
        f = bz2.open(BytesIO(response.content))
        data, raw = read_radolan_composite(f)

        return float(data[self.index]), ProductMetadata(
            source_product=raw.get("producttype"),
            source_timestamp=_utc(raw.get("datetime")),
        )


class RadolanRW(RadolanProduct):
    """DWD RADOLAN RW: 1-hour precipitation analysis."""

    PRODUCT_KEY = "rw"

    RELEASE_INTERVAL = timedelta(hours=1)

    RELEASE_DELAY = timedelta(minutes=28)

    RELEASE_OFFSET = timedelta(minutes=50)

    def _get_url(self, ts: datetime) -> str:
        """Return the bz2 URL."""
        return (
            f"{DWD_RADOLAN_URL}/rw/raa01-rw_10000-"
            f"{ts.strftime('%y%m%d%H%M')}-dwd---bin.bz2"
        )


class RadolanSF(RadolanProduct):
    """DWD RADOLAN SF: 24-hour precipitation analysis."""

    PRODUCT_KEY = "sf"

    RELEASE_INTERVAL = timedelta(hours=1)

    RELEASE_DELAY = timedelta(minutes=28)

    RELEASE_OFFSET = timedelta(minutes=50)

    def _get_url(self, ts: datetime) -> str:
        """Return the bz2 URL."""
        return (
            f"{DWD_RADOLAN_URL}/sf/raa01-sf_10000-"
            f"{ts.strftime('%y%m%d%H%M')}-dwd---bin.bz2"
        )


class RadolanSFLastYesterday(RadolanSF):
    """DWD RADOLAN SF: yesterday's 24-hour total (daily, local time)."""

    PRODUCT_KEY = "sf_2350"

    RELEASE_INTERVAL = timedelta(hours=24)

    RELEASE_DELAY = timedelta(minutes=28)

    RELEASE_OFFSET = timedelta(hours=23, minutes=50)

    USE_LOCAL_TIME = True
