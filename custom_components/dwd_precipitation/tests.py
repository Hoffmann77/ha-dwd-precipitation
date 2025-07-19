# -*- coding: utf-8 -*-
"""
Created on Tue Mar 12 19:50:36 2024

@author: Bobby
"""
import gzip
from io import BytesIO
from datetime import datetime, timedelta, timezone
from functools import cached_property

from utils import get_previous_multiple, async_get


DWD_RADAR_URL = "https://opendata.dwd.de/weather/radar/"


RELEASE_INTERVAL = timedelta(hours=24)

RELEASE_DELAY = timedelta(minutes=28)

RELEASE_OFFSET = timedelta(hours=23, minutes=50)


def get_latest_release() -> datetime:
    """Return the latest release timestamp."""
    now = datetime(year=2025, month=7, day=12, hour=11)
    print(now)

    now = now - RELEASE_DELAY
    print(now)

    return get_previous_multiple(
        now, RELEASE_INTERVAL, RELEASE_OFFSET,
    )


print(get_latest_release())


class RadvorRQ:

    PRODUCT_KEY = "rq"

    RELEASE_INTERVAL = timedelta(minutes=15)

    RELEASE_DELAY = timedelta(minutes=5)

    RELEASE_OFFSET = timedelta()

    def __init__(self, lat: float, lon: float):
        """Initialize Product."""
        self.lat = lat
        self.lon = lon
        self.data = None
        self.curr_release = None

    @cached_property
    def index(self):
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
        now = datetime.now(timezone.utc) - self.RELEASE_DELAY

        return get_previous_multiple(
            now, self.RELEASE_INTERVAL, self.RELEASE_OFFSET,
        )

    def get_urls(self, *suffixes) -> list[str]:
        """Return the urls."""
        ts = self.get_latest_release()
        ts = ts.strftime("%y%m%d%H%M")
        urls = []
        for suffix in suffixes:
            urls.append(
                f"{DWD_RADAR_URL}radvor/rq/RQ{ts}_{suffix}.gz"
            )

        return urls

    def update(self, async_client):
        """Update the data."""
        new_data = []

        for url in self.get_urls("060", "120"):
            print(url)
            response = async_client.get(url)
            #response = async_get(url, async_client)
            # 404 if not available

            response = BytesIO(response.content)

            f = gzip.open(response)

            data, metadata = read_radolan_composite(f)

            print(metadata)

            print(data[self.index])
            new_data.append(data[self.index])

        self.data = new_data




#rq = RadvorRQ(51.919, 8.357)

#client = httpx.Client()

#rq.update(client)