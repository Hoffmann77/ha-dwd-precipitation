"""Range reads of RADVOR tar members against a fake range-capable server."""

from __future__ import annotations

import asyncio
import random
import tarfile

import pytest

from radar.tar_range import (
    BLOCK,
    HEAD_BYTES,
    MAX_REQUESTS,
    fetch_tar_members,
    member_names,
)
from tests.factories.radvor import LEADS, HTTPError, RangeServer, radvor_archive

PREFIX = "composite_rv_20261012_0740"
NAMES = member_names(PREFIX, LEADS)


def _archive(sizes: list[int], seed: int = 1, names=NAMES) -> tuple[bytes, dict[str, bytes]]:
    """Build an archive like DWD's with random payloads of the given sizes."""
    rng = random.Random(seed)
    payloads = {name: rng.randbytes(size) for name, size in zip(names, sizes)}
    return radvor_archive(payloads), payloads


def _read(server: RangeServer, wanted):
    return asyncio.run(
        fetch_tar_members(server.fetch, "https://x/f.tar", NAMES, wanted)
    )


def _sizes(seed: int, low: int, high: int) -> list[int]:
    rng = random.Random(seed)
    return [rng.randint(low, high) for _ in NAMES]


@pytest.mark.parametrize(
    "sizes",
    [
        _sizes(1, 40_000, 90_000),       # dry day: several members in the head
        _sizes(2, 150_000, 350_000),     # wet day
        [300_000] + _sizes(3, 30_000, 400_000)[1:],  # very uneven members
    ],
)
def test_reads_the_three_rs_members_with_few_requests(sizes):
    content, payloads = _archive(sizes)
    server = RangeServer(content)
    wanted = [NAMES[0], NAMES[12], NAMES[24]]

    result = _read(server, wanted)

    assert not result.whole
    assert result.members == {name: payloads[name] for name in wanted}
    assert result.requests <= 6
    # The point of it all: far fewer bytes than the archive.
    assert result.bytes_read < len(content) * 0.6
    assert server.whole_downloads == 0


def test_analysis_only_is_one_request_when_it_fits_the_head():
    content, payloads = _archive(_sizes(4, 50_000, 300_000))
    server = RangeServer(content)
    result = _read(server, [NAMES[0]])

    assert result.members == {NAMES[0]: payloads[NAMES[0]]}
    assert result.requests == 1
    assert server.requests[0]["Range"] == f"bytes=0-{HEAD_BYTES - 1}"
    assert server.requests[0]["Accept-Encoding"] == "identity"


def test_analysis_larger_than_the_head_takes_a_second_request_with_if_range():
    content, payloads = _archive([HEAD_BYTES + 50_000] + _sizes(5, 50_000, 90_000)[1:])
    server = RangeServer(content)
    result = _read(server, [NAMES[0]])

    assert result.members[NAMES[0]] == payloads[NAMES[0]]
    assert result.requests == 2
    assert server.requests[1]["If-Range"] == '"v1"'


def test_server_ignoring_ranges_is_read_as_a_whole_archive():
    content, payloads = _archive(_sizes(6, 50_000, 90_000))
    server = RangeServer(content, ranges=False)
    result = _read(server, [NAMES[0], NAMES[12]])

    assert result.whole
    assert result.members == {n: payloads[n] for n in (NAMES[0], NAMES[12])}
    assert result.requests == 1  # the 200 already was the archive
    assert server.whole_downloads == 0


def test_unexpected_first_member_downloads_the_whole_archive():
    names = list(reversed(NAMES))
    content, payloads = _archive(_sizes(7, 50_000, 90_000), names=names)
    server = RangeServer(content)
    result = _read(server, [NAMES[0]])

    assert result.whole
    assert server.whole_downloads == 1
    assert result.members == {NAMES[0]: payloads[NAMES[0]]}


def test_file_replaced_between_requests_is_not_stitched_together():
    old, _ = _archive(_sizes(8, 150_000, 350_000), seed=8)
    new, new_payloads = _archive(_sizes(9, 150_000, 350_000), seed=9)
    server = RangeServer(old)
    server.replace_after = (1, new, '"v2"')
    wanted = [NAMES[0], NAMES[24]]

    result = _read(server, wanted)

    # If-Range made the server answer with the whole new file.
    assert result.whole
    assert result.members == {n: new_payloads[n] for n in wanted}


def test_header_lookalike_inside_member_data_is_ignored():
    """A block that starts with the name prefix but fails the checksum."""
    sizes = _sizes(10, 50_000, 90_000)
    content, payloads = _archive(sizes)
    blob = bytearray(content)
    # Plant a fake header for member 12 inside member 3's data, block-aligned.
    offset = 0
    for size in sizes[:3]:
        offset += BLOCK + -(-size // BLOCK) * BLOCK
    fake = tarfile.TarInfo(NAMES[12])
    fake.size = 5
    block = bytearray(fake.tobuf(tarfile.USTAR_FORMAT))
    block[148:156] = b"0000000\0"  # break the checksum
    lookalike = offset + BLOCK * 2
    blob[lookalike:lookalike + BLOCK] = block
    server = RangeServer(bytes(blob))

    result = _read(server, [NAMES[12]])

    assert result.members[NAMES[12]] == payloads[NAMES[12]]


def test_missing_member_is_absent_after_the_fallback():
    names = NAMES[:24]  # no _120 member
    content, _ = _archive(_sizes(11, 50_000, 90_000)[:24], names=names)
    server = RangeServer(content)
    result = _read(server, [NAMES[24]])

    assert result.members == {}
    assert result.requests <= MAX_REQUESTS + 1


def test_not_found_propagates():
    requests = []

    async def fetch(_url, headers):
        requests.append(headers)
        raise HTTPError(404)

    with pytest.raises(HTTPError):
        asyncio.run(fetch_tar_members(fetch, "https://x/f.tar", NAMES, [NAMES[0]]))
    # A missing release is not a fallback case: no whole-archive download.
    assert len(requests) == 1
