"""Utils module."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import aiohttp

# Only DWD OpenData is a trusted origin. TLS server-certificate validation
# (enabled by default on Home Assistant's shared aiohttp session) authenticates
# the host; this allow-list plus the HTTPS requirement is a regression guard so
# a future refactor can never point a fetch at a plaintext or foreign host.
ALLOWED_HOSTS = frozenset({"opendata.dwd.de"})

# Upper bound on a single download. The largest legitimate payload is an RS/RV
# tar of 25 ODIM_H5 members (a few MB); this generous ceiling is a DoS backstop
# against a hijacked or MITM endpoint returning a huge or decompression-bomb
# body, not a tight per-product size.
DEFAULT_MAX_BYTES = 128 * 1024 * 1024

_READ_CHUNK = 64 * 1024


@dataclass
class AsyncResponse:
    """Minimal HTTP response wrapper returned by async_get."""

    content: bytes


def _validate_url(url: str) -> None:
    """Reject any URL that is not HTTPS on a trusted DWD host."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError(f"Refusing non-HTTPS DWD URL: {url!r}")
    if parts.hostname not in ALLOWED_HOSTS:
        raise ValueError(
            f"Refusing DWD URL with untrusted host {parts.hostname!r}: {url!r}"
        )


async def _read_capped(response: aiohttp.ClientResponse, max_bytes: int) -> bytes:
    """Read the body, refusing to buffer more than ``max_bytes``.

    Checks the declared Content-Length first (cheap early rejection), then caps
    the streamed read as well, since the header may be absent or untruthful.
    """
    declared = response.content_length
    if declared is not None and declared > max_bytes:
        raise ValueError(
            f"DWD response too large: Content-Length {declared} exceeds "
            f"{max_bytes}-byte cap"
        )

    chunks: list[bytes] = []
    total = 0
    async for chunk in response.content.iter_chunked(_READ_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"DWD response exceeded {max_bytes}-byte cap")
        chunks.append(chunk)

    return b"".join(chunks)


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
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> AsyncResponse:
    """Send a HTTP GET request using an aiohttp session.

    Enforces the security invariants for DWD fetches: HTTPS on a trusted host,
    no cross-host redirects (so provenance can't be redirected away), and a hard
    cap on the buffered body size. Retries on connection errors up to `attempts`
    times. Raises immediately on 4xx/5xx responses without retrying.
    """
    _validate_url(url)
    for attempt in range(attempts):
        try:
            async with session.get(url, allow_redirects=False) as response:
                response.raise_for_status()
                if 300 <= response.status < 400:
                    raise ValueError(
                        f"DWD returned an unexpected redirect "
                        f"(HTTP {response.status}) for {url!r}"
                    )
                return AsyncResponse(content=await _read_capped(response, max_bytes))
        except aiohttp.ClientResponseError:
            raise
        except aiohttp.ClientConnectionError as err:
            if attempt < attempts - 1:
                await asyncio.sleep((attempt + 1) * 0.1)
                continue
            raise err
