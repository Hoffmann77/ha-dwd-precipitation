"""Read selected members of a remote tar archive with HTTP range requests.

RADVOR RS/RV releases are plain (uncompressed) ustar archives of 25 ODIM_H5
members in a fixed order, served by DWD OpenData as static files with range
support. Most callers need only a few members — RS decodes three, the RV
backfill only the analysis — so downloading the whole archive (3.5-17.5 MB)
moves several times more bytes than are used.

A tar member is a 512-byte header followed by its data, padded to 512 bytes.
Nothing indexes the headers, so a member deep in the archive is found by
estimating where its header sits from the members already seen, reading a
window around that estimate, and scanning the window's 512-byte blocks for
headers. Headers are recognised by their name and checksum, so a block of
HDF5 data cannot pass for one.

DWD promises neither the member order nor range support, so every surprise —
a 200 instead of a 206, an unexpected first member, a header that cannot be
found within the request budget, a file that changed between requests —
falls back to downloading the whole archive and reading it with ``tarfile``.
A failed fetch (404, network) is not a surprise and propagates.

HA-free: the caller passes ``fetch(url, headers) -> response`` with
``status``, ``headers`` (case-insensitive mapping) and ``content`` (bytes),
which must raise on any 4xx/5xx except 416.

"""

from __future__ import annotations

import io
import logging
import os
import re
import tarfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

_LOGGER = logging.getLogger(__name__)

BLOCK = 512

# First request: the archive head. Measured on OpenData (2026-10-10..12) the
# first member is 50-350 kB for RV and 120-720 kB for RS, so no single size
# fits: 128 KiB covers a dry-day RV analysis in one request, and anything
# larger costs one more request for exactly the remainder rather than a large
# head that is mostly someone else's data.
HEAD_BYTES = 128 * 1024

# Behind the last member: two zero blocks, then padding to tarfile's 10 KiB
# record size.
TRAILER_MAX = 2 * BLOCK + tarfile.RECORDSIZE

# Requests one call may spend on locating members before it gives up and
# downloads the archive instead. A normal RS read takes three.
MAX_REQUESTS = 10

# A member larger than this is not a radar grid.
MAX_MEMBER_BYTES = 64 * 1024 * 1024

# Window sizes in strides (the average bytes per member seen so far): the next
# member is read with this much room for being larger than average, ...
NEXT_MEMBER_STRIDES = 1.5
# ... and an interpolated or extrapolated header is searched this far either
# side of its estimate (doubled after each window that finds nothing).
ESTIMATE_MARGIN_STRIDES = 0.5

_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")


class RangeResponse(Protocol):
    """What ``fetch`` returns."""

    status: int
    headers: Mapping[str, str]
    content: bytes


Fetch = Callable[[str, Mapping[str, str]], Awaitable[RangeResponse]]

# Turns a whole archive into the wanted members; the default runs in place.
Extract = Callable[[bytes, Sequence[str]], Awaitable[dict[str, bytes]]]


class _Fallback(Exception):
    """Range reading cannot continue; read the whole archive instead."""


class _WholeArchive(Exception):
    """The server sent the whole archive (HTTP 200); use it as it is."""

    def __init__(self, content: bytes) -> None:
        """Keep the whole archive the server sent.

        Raised when a range request was answered with the complete file (HTTP
        200): the server ignores ranges, or the file was replaced and If-Range
        made it send the new one. The content is then used as it is, without a
        second download.

        """
        super().__init__("server sent the whole archive")
        self.content = content


@dataclass
class TarRead:
    """Outcome of :func:`fetch_tar_members`."""

    members: dict[str, bytes]
    requests: int
    bytes_read: int
    # Whether the whole archive was downloaded (fallback or HTTP 200).
    whole: bool


@dataclass
class _Remote:
    """One remote file: cached byte ranges and the request bookkeeping."""

    fetch: Fetch
    url: str
    total: int | None = None
    etag: str | None = None
    requests: int = 0
    bytes_read: int = 0
    segments: list[tuple[int, bytes]] = field(default_factory=list)

    def cached(self, start: int, end: int) -> bytes | None:
        """Return bytes [start, end) if one fetched segment holds them.

        Each range request's answer is kept as a segment. None when no single
        segment covers the range; reading from what is held costs no request.

        """
        for seg_start, data in self.segments:
            if seg_start <= start and end <= seg_start + len(data):
                return data[start - seg_start:end - seg_start]
        return None

    async def slice(self, start: int, end: int) -> bytes:
        """Return bytes [start, end), fetching only what no segment starts with.

        Cuts a member out once its header is known: a member often begins
        inside a window already fetched to find its header, so that part is
        reused and only the rest is requested.

        """
        if (data := self.cached(start, end)) is not None:
            return data
        for seg_start, seg in self.segments:
            seg_end = seg_start + len(seg)
            if seg_start <= start < seg_end:
                return seg[start - seg_start:] + await self.read(seg_end, end)
        return await self.read(start, end)

    async def read(self, start: int, end: int) -> bytes:
        """Fetch bytes [start, end), clamped to the file.

        One Range request, checked against what was asked for, and kept as a
        segment. Anything unexpected (no 206, a mismatching range, a file
        replaced in between, the request budget spent) raises, so the caller
        downloads the whole archive instead. A 404 or network error propagates
        as it is.

        """
        if self.total is not None:
            end = min(end, self.total)
        if start >= end:
            raise _Fallback(f"empty range {start}-{end}")
        if (data := self.cached(start, end)) is not None:
            return data
        if self.requests >= MAX_REQUESTS:
            raise _Fallback("request budget spent")

        headers = {"Range": f"bytes={start}-{end - 1}", "Accept-Encoding": "identity"}
        if self.etag:
            # A file replaced between two reads must not be stitched together:
            # with If-Range the server answers 200 and the whole new file.
            headers["If-Range"] = self.etag

        self.requests += 1
        try:
            response = await self.fetch(self.url, headers)
        except Exception as err:
            if getattr(err, "status", None) == 416:
                raise _Fallback("range not satisfiable") from err
            raise

        self.bytes_read += len(response.content)
        if response.status == 200:
            raise _WholeArchive(response.content)
        if response.status != 206:
            raise _Fallback(f"unexpected HTTP {response.status}")

        match = _CONTENT_RANGE.fullmatch(response.headers.get("Content-Range", ""))
        if match is None:
            raise _Fallback("206 without a usable Content-Range")
        got_start, got_end, total = (int(g) for g in match.groups())
        if (
            got_start != start
            or got_end != min(end, total) - 1
            or len(response.content) != got_end - got_start + 1
            or (self.total is not None and total != self.total)
        ):
            raise _Fallback("206 does not match the requested range")

        self.total = total
        if self.etag is None:
            # If-Range also takes the Last-Modified date, for a server
            # without ETags.
            self.etag = response.headers.get("ETag") or response.headers.get(
                "Last-Modified"
            )
        self.segments.append((start, response.content))
        return response.content


def _padded(size: int) -> int:
    """Return ``size`` rounded up to whole tar blocks.

    Tar stores member data in 512-byte blocks, so the next header starts at the
    next block boundary after a member's data.

    """
    return -(-size // BLOCK) * BLOCK


def _scan(
    seg_start: int,
    data: bytes,
    prefix: bytes,
    positions: Mapping[str, int],
    known: dict[int, tuple[int, int]],
) -> bool:
    """Record every member header found in a segment; return whether any was new.

    ``data`` was read at offset ``seg_start``; found headers go into ``known``
    as position -> (offset, size). Only 512-byte-aligned blocks that start with
    the member name prefix are parsed, and ``tarfile`` verifies the header
    checksum, so member data cannot be mistaken for a header.

    """
    found = False
    first = _padded(seg_start)
    for offset in range(first, seg_start + len(data) - BLOCK + 1, BLOCK):
        rel = offset - seg_start
        if not data.startswith(prefix, rel):
            continue
        try:
            info = tarfile.TarInfo.frombuf(
                data[rel:rel + BLOCK], "utf-8", "surrogateescape"
            )
        except tarfile.HeaderError:
            continue
        pos = positions.get(info.name)
        if pos is None or not info.isreg() or info.size > MAX_MEMBER_BYTES:
            continue
        if pos not in known:
            known[pos] = (offset, info.size)
            found = True
    return found


def _next_header(known: dict[int, tuple[int, int]], pos: int) -> int:
    """Return the offset just past member ``pos`` (where the next header sits).

    Its header block, plus its data padded to whole blocks, measured from where
    its header was found.

    """
    offset, size = known[pos]
    return offset + BLOCK + _padded(size)


async def _locate(
    remote: _Remote,
    pos: int,
    count: int,
    prefix: bytes,
    positions: Mapping[str, int],
    known: dict[int, tuple[int, int]],
) -> None:
    """Find member ``pos``'s header, reading windows around estimates.

    The members sit in lead order without an index, so its position is
    estimated from the members already found: right after the previous one,
    interpolated between two known headers where possible, or near the end of
    the file for the last member. A window around the estimate is read and
    scanned, and a window that finds nothing is widened the next time round.
    Raises _Fallback when the member cannot be found.

    """
    widen = 1.0
    # Bounded separately from the request budget: a window served from cache
    # costs no request, and must not let a fruitless search spin.
    for _ in range(MAX_REQUESTS):
        if pos in known:
            return
        lower = max(p for p in known if p < pos)
        upper = min((p for p in known if p > pos), default=None)
        after_lower = _next_header(known, lower)
        # Average bytes per member so far: the yardstick for every estimate.
        stride = after_lower / (lower + 1)

        if pos == lower + 1:
            # The header can only be here. If it already was read and is not
            # this member, the archive is not laid out the way we expect.
            if remote.cached(after_lower, after_lower + BLOCK) is not None:
                raise _Fallback(f"no header for member {pos} after member {lower}")
            start = after_lower
            end = after_lower + BLOCK + int(stride * NEXT_MEMBER_STRIDES)
        elif upper is not None:
            span = known[upper][0] - after_lower
            estimate = after_lower + span * (pos - lower - 1) / (upper - lower - 1)
            margin = stride * ESTIMATE_MARGIN_STRIDES * widen + BLOCK
            start, end = estimate - margin, estimate + margin + stride
        elif pos == count - 1 and remote.total is not None:
            # The last member ends just before the trailer.
            start = (
                remote.total - TRAILER_MAX - stride * NEXT_MEMBER_STRIDES * widen - BLOCK
            )
            end = remote.total
        else:
            estimate = after_lower + stride * (pos - lower - 1)
            margin = stride * ESTIMATE_MARGIN_STRIDES * widen + BLOCK
            start, end = estimate - margin, estimate + margin + stride

        start = max(int(start) // BLOCK * BLOCK, after_lower)
        if upper is not None:
            end = min(end, known[upper][0])
        data = await remote.read(start, int(end))
        if not _scan(start, data, prefix, positions, known):
            # The window fell inside one member's data: look wider next time.
            widen *= 2

    if pos not in known:
        raise _Fallback(f"member {pos} not found")


def members_from_archive(content: bytes, wanted: Sequence[str]) -> dict[str, bytes]:
    """Extract the wanted members from a whole archive; missing ones are left out.

    ``content`` is the complete tar, ``wanted`` the member names. Returns their
    bytes by name. Blocking (it walks the archive with tarfile), so callers on
    the event loop run it in an executor.

    """
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(content), mode="r") as tf:
        for name in wanted:
            try:
                f = tf.extractfile(name)
            except KeyError:
                continue
            if f is not None:
                out[name] = f.read()
    return out


async def fetch_tar_members(
    fetch: Fetch,
    url: str,
    names: Sequence[str],
    wanted: Sequence[str],
    extract: Extract | None = None,
) -> TarRead:
    """Return the ``wanted`` members of the remote archive at ``url``.

    ``names`` lists every member in archive order, ``wanted`` the ones needed.
    Reads them by HTTP range requests where it can: a head, then windows around
    estimated headers. Whenever that cannot go on, it downloads the whole
    archive and takes the members out with ``extract`` (in place if none is
    given). The result also counts the requests and bytes, and says whether the
    whole file was read. A member missing from the archive is absent from the
    result.

    """
    positions = {name: i for i, name in enumerate(names)}
    prefix = os.path.commonprefix(list(names)).encode()
    remote = _Remote(fetch, url)
    try:
        known: dict[int, tuple[int, int]] = {}
        _scan(0, await remote.read(0, HEAD_BYTES), prefix, positions, known)
        if known.get(0, (None,))[0] != 0:
            raise _Fallback(f"{names[0]} is not the first member")

        # The last wanted member first: the end of the file pins it down well,
        # and the rest are then interpolated between two known headers. Member
        # sizes shrink with forecast lead, so extrapolating from the head alone
        # misses the middle by up to a member.
        order = sorted(wanted, key=positions.__getitem__)
        for name in order[-1:] + order[:-1]:
            await _locate(remote, positions[name], len(names), prefix, positions, known)

        members: dict[str, bytes] = {}
        for name in wanted:
            offset, size = known[positions[name]]
            members[name] = await remote.slice(offset + BLOCK, offset + BLOCK + size)
        return TarRead(members, remote.requests, remote.bytes_read, whole=False)
    except _WholeArchive as whole:
        content = whole.content
    except _Fallback as why:
        _LOGGER.debug("Range read of %s fell back to the whole file: %s", url, why)
        content = (await fetch(url, {})).content
        remote.requests += 1
        remote.bytes_read += len(content)

    members = (
        await extract(content, wanted)
        if extract is not None
        else members_from_archive(content, wanted)
    )
    return TarRead(members, remote.requests, remote.bytes_read, whole=True)


def member_names(prefix: str, leads: Sequence[int]) -> list[str]:
    """Return RADVOR member names (``<prefix>_<lead>-hd5``) in archive order.

    ``prefix`` is the release's name stem (see radar/urls.py), ``leads`` the
    forecast minutes, e.g. [0, 60, 120] -> ``..._000-hd5``, ``..._060-hd5``,
    ``..._120-hd5``. The archive holds them in lead order, which the range
    reader relies on.

    """
    return [f"{prefix}_{lead:03d}-hd5" for lead in leads]


__all__ = ["TarRead", "fetch_tar_members", "member_names", "members_from_archive"]
