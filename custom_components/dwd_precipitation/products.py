"""DWD radar products."""

import gzip
import bz2
import logging
from io import BytesIO
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from functools import cached_property
# from collections import namedtuple

import numpy as np
from homeassistant.util import dt as dt_util

from .utils import get_previous_multiple, async_get
from .radar import read_radolan_composite, get_radolan_grid
from .const import DWD_RADOLAN_URL, DWD_RADVOR_URL

if TYPE_CHECKING:
    import httpx

_LOGGER = logging.getLogger(__name__)


class Product(ABC):
    """Base DWD radar product."""

    PRODUCT_KEY = "rq"

    RELEASE_INTERVAL = timedelta(minutes=15)

    RELEASE_DELAY = timedelta(minutes=5)

    RELEASE_OFFSET = timedelta()

    USE_LOCAL_TIME = False

    def __init__(self, lat: float, lon: float) -> None:
        """Initialize Product."""
        self.lat = lat
        self.lon = lon
        self.data = None
        self.source = None
        self.curr_release = None

    @cached_property
    def index(self):
        """Return the index for the parsed radolan data."""
        grid = get_radolan_grid(wgs84=True)
        lon_grid = grid[:,:,0]
        lat_grid = grid[:,:,1]

        # Compute the squared Euclidean distances
        dist_sq = (lat_grid - self.lat)**2 + (lon_grid - self.lon)**2

        # Find index with minimum distance
        return np.unravel_index(np.argmin(dist_sq), dist_sq.shape)

    @property
    def requires_update(self) -> bool:
        """Return if the product needs to be updated."""
        if self.curr_release is None:
            return True

        if self.curr_release < self.get_latest_release():
            return True

        return False

    def get_latest_release(self) -> datetime:
        """Return the latest release timestamp."""
        now = dt_util.now() if self.USE_LOCAL_TIME else dt_util.utcnow()

        prev_multiple = get_previous_multiple(
            now - self.RELEASE_DELAY,
            self.RELEASE_INTERVAL,
            self.RELEASE_OFFSET,
        )

        return dt_util.as_utc(prev_multiple)

    @abstractmethod
    def get_url(self, ts: datetime, *args, **kwargs) -> str | list[str]:
        """Return the url."""
        pass

    @abstractmethod
    def update(self, async_client) -> None:
        """Update the data."""
        pass


class RadvorRQ(Product):
    """DWD RQ precipitation forecast."""

    PRODUCT_KEY = "rq"

    RELEASE_INTERVAL = timedelta(minutes=15)

    RELEASE_DELAY = timedelta(minutes=5)

    RELEASE_OFFSET = timedelta()

    def get_url(self, ts: datetime, *suffixes: str) -> list[str]:
        """Return the urls."""
        ts = ts.strftime("%y%m%d%H%M")
        urls = []
        for suffix in suffixes:
            urls.append(
                f"{DWD_RADVOR_URL}/rq/RQ{ts}_{suffix}.gz"
            )

        return urls

    async def update(self, async_client) -> None:
        """Update the data."""
        new_data = []
        ts = self.get_latest_release()

        for url in self.get_url(ts, "000", "060", "120"):
            try:
                response = await async_get(url, async_client)
                # 404 if not available
            except:# httpx.TransportError:
                return


            response = BytesIO(response.content)

            f = gzip.open(response)

            data, metadata = read_radolan_composite(f)
            new_data.append(data[self.index])

        self.current_release = ts
        self.data = new_data


class RadolanProduct(Product):
    """DWD radolan product."""

    async def update(self, async_client):
        """Update the data."""
        ts = self.get_latest_release()
        url = self.get_url(ts)
        try:
            response = await async_get(url, async_client)
        except:
            return

        # 404 if not available

        response = BytesIO(response.content)

        f = bz2.open(response)

        data, metadata = read_radolan_composite(f)

        new_data = data[self.index]

        self.current_release = ts
        self.data = new_data


class RadolanRW(RadolanProduct):
    """DWD radolan RW 1 hour precipitation analysis."""

    PRODUCT_KEY = "rw"

    RELEASE_INTERVAL = timedelta(hours=1)

    RELEASE_DELAY = timedelta(minutes=28)

    RELEASE_OFFSET = timedelta(minutes=50)

    def get_url(self, ts: datetime) -> list[str]:
        """Return the urls."""
        ts = ts.strftime("%y%m%d%H%M")

        return (
            f"{DWD_RADOLAN_URL}/rw/raa01-rw_10000-{ts}-dwd---bin.bz2"
        )


class RadolanSF(RadolanProduct):
    """DWD radolan SF 24 hour precipitation analysis."""

    PRODUCT_KEY = "sf"

    RELEASE_INTERVAL = timedelta(minutes=60)

    RELEASE_DELAY = timedelta(minutes=28)

    RELEASE_OFFSET = timedelta(minutes=50)

    def get_url(self, ts: datetime) -> list[str]:
        """Return the urls."""
        ts = ts.strftime("%y%m%d%H%M")

        return (
            f"{DWD_RADOLAN_URL}/sf/raa01-sf_10000-{ts}-dwd---bin.bz2"
        )


# class RadolanSFFirstToday(RadolanSF):
#     """DWD radolan SF 24 hour precipitation analysis."""

#     PRODUCT_KEY = "sf_0050"

#     RELEASE_INTERVAL = timedelta(hours=24)

#     RELEASE_DELAY = timedelta(minutes=28)

#     RELEASE_OFFSET = timedelta(minutes=50)

#     USE_LOCAL_TIME = True


class RadolanSFLastYesterday(RadolanSF):
    """DWD radolan SF 24 hour precipitation analysis."""

    PRODUCT_KEY = "sf_2350"

    RELEASE_INTERVAL = timedelta(hours=24)

    RELEASE_DELAY = timedelta(minutes=28)

    RELEASE_OFFSET = timedelta(hours=23, minutes=50)

    USE_LOCAL_TIME = True