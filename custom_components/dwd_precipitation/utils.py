"""Utils module."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import httpx


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
    client: httpx.AsyncClient,
    attempts: int = 2,
    **kwargs,
) -> httpx.Response:
    """Send a HTTP GET request using the httpx client.

    Parameters
    ----------
    url : str
        URL.
    client : httpx.AsyncClient
        Instance of httpx.AsyncClient.
    attempts : int, optional
        Number of attempts to send the request if TransportErrors occur.
        The default is 2.
    **kwargs : dict
        Optional keyword arguments for httpx.AsyncClient.request.

    Returns
    -------
    response : httpx.Response
        The response from the server.

    """
    for attempt in range(attempts):
        try:
            response = await client.get(url, **kwargs)
            response.raise_for_status()
        except httpx.TransportError as err:
            if attempt < attempts:
                await asyncio.sleep((attempt + 1) * 0.1)
                continue
            else:
                raise err
        else:
            return response
