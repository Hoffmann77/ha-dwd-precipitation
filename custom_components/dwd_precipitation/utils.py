"""Utils module."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiohttp


@dataclass
class AsyncResponse:
    """Minimal HTTP response wrapper returned by async_get."""

    content: bytes


class mydatetime(datetime):
    """Standard datetime class with added support for the % and // operators.

    Timedeltas in microseconds are not supported.

    """

    def __divmod__(self, delta: timedelta) -> tuple[int, timedelta]:
        """Magic __divmod__ method."""
        seconds = int(
            (self - datetime.min.replace(tzinfo=self.tzinfo)).total_seconds()
        )
        remainder = timedelta(
            seconds=seconds % delta.total_seconds(),
            microseconds=self.microsecond,
        )
        quotient = self - remainder
        return quotient, remainder

    def __floordiv__(self, delta: timedelta) -> int:
        """Magic __floordiv__ method."""
        return divmod(self, delta)[0]

    def __mod__(self, delta: timedelta) -> timedelta:
        """Magic __mod__ method."""
        return divmod(self, delta)[1]

    @classmethod
    def from_datetime(cls, dt: datetime) -> mydatetime:
        """Create instance from a datetime obj."""
        return mydatetime(
            year=dt.year,
            month=dt.month,
            day=dt.day,
            hour=dt.hour,
            minute=dt.minute,
            second=dt.second,
            tzinfo=dt.tzinfo,
            fold=dt.fold,
        )


def get_previous_multiple(
        timestamp: datetime,
        interval: timedelta,
        offset: timedelta,
        include: bool = True,
) -> datetime:
    """Return the previous multiple of the given timestamp."""
    dt = mydatetime.from_datetime(timestamp)
    floor, remainder = divmod((dt - offset), interval)

    if not include and not remainder:
        prev_multiple = (floor + offset) - interval
    else:
        prev_multiple = floor + offset

    return datetime.fromtimestamp(
        prev_multiple.timestamp(), tz=dt.tzinfo
    )


async def async_get(
    url: str,
    session: aiohttp.ClientSession,
    attempts: int = 2,
) -> AsyncResponse:
    """Send a HTTP GET request using an aiohttp session.

    Retries on connection errors up to `attempts` times. Raises immediately
    on 4xx/5xx responses without retrying.
    """
    for attempt in range(attempts):
        try:
            async with session.get(url) as response:
                response.raise_for_status()
                return AsyncResponse(content=await response.read())
        except aiohttp.ClientResponseError:
            raise
        except aiohttp.ClientConnectionError as err:
            if attempt < attempts - 1:
                await asyncio.sleep((attempt + 1) * 0.1)
                continue
            raise err
