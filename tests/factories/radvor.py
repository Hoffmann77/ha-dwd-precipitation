"""RADVOR (RS/RV) archives and a range-capable server, for every test tier.

HA-free: the parser tier uses them as much as the integration tier.
"""

from __future__ import annotations

import io
import re
import tarfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from radar.nowcast import LEADS
from radar.tar_range import member_names
from radar.urls import radvor_prefix


def radvor_archive(members: Mapping[str, bytes]) -> bytes:
    """Return a ustar archive like DWD's: ``members`` in the given order."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def _lead_payload(lead: int) -> bytes:
    return f"{lead:03d}".encode()


def make_radvor_tar(
    product: str,
    ts: datetime,
    payload: Callable[[int], bytes] = _lead_payload,
) -> bytes:
    """Return release ``ts`` of ``product`` ("rs"/"rv"): all 25 members.

    Member payloads are placeholders (by default the lead, ``b"060"``), since
    callers patch the ODIM reader to turn each into the values they want.
    """
    names = member_names(radvor_prefix(product, ts), LEADS)
    return radvor_archive({name: payload(lead) for name, lead in zip(names, LEADS)})


@dataclass
class Response:
    """What async_get returns, as far as the code under test reads it."""

    content: bytes
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)


class HTTPError(Exception):
    """An HTTP error status (416 for a range past the end)."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class RangeServer:
    """Serves one file like nginx: byte ranges, ETag and If-Range.

    ``fetch(url, headers)`` is the shape fetch_tar_members takes;
    ``async_get`` the shape of utils.async_get, for patching products.
    """

    def __init__(self, content: bytes, *, ranges: bool = True, etag: str = '"v1"'):
        self.content = content
        self.ranges = ranges  # False: answer every request with the whole file
        self.etag = etag
        self.requests: list[dict[str, str]] = []
        self.whole_downloads = 0  # requests that asked for the whole file
        # (after n requests, new content, new etag): the file is replaced.
        self.replace_after: tuple[int, bytes, str] | None = None

    async def fetch(self, url: str, headers: Mapping[str, str] | None = None) -> Response:
        headers = dict(headers or {})
        self.requests.append(headers)
        if "Range" not in headers:
            self.whole_downloads += 1
        if self.replace_after and len(self.requests) > self.replace_after[0]:
            _, self.content, self.etag = self.replace_after
        if not self.ranges or "Range" not in headers:
            return Response(self.content, 200, {"ETag": self.etag})
        if (if_range := headers.get("If-Range")) and if_range != self.etag:
            return Response(self.content, 200, {"ETag": self.etag})
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", headers["Range"])
        assert match, headers["Range"]
        start, end = (int(x) for x in match.groups())
        total = len(self.content)
        if start >= total:
            raise HTTPError(416)
        end = min(end, total - 1)
        return Response(
            self.content[start:end + 1],
            206,
            {"Content-Range": f"bytes {start}-{end}/{total}", "ETag": self.etag},
        )

    async def async_get(self, url, _client, headers=None, **_kw) -> Response:
        return await self.fetch(url, headers)


__all__ = [
    "LEADS",
    "HTTPError",
    "RangeServer",
    "Response",
    "make_radvor_tar",
    "radvor_archive",
]
