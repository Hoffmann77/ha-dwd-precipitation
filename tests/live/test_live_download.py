"""Live source-liveness smoke tests — download & parse real DWD OpenData files.

Network-dependent and scheduled (never gates PRs). Marked @live; run with:
  uv run --group unit-test pytest tests/live -m live -v

HA-free by design: the URLs come from radar/urls.py, the same patterns the
integration fetches. If DWD changes a URL scheme, archive layout, range
support or binary format, these tests fail on the schedule and open a
tracking issue — before users hit it.

Robustness: OpenData publishes with a delay and rotates files, so the freshest
slot is often not up yet. Each product walks back several releases until one
downloads; only "nothing downloadable at all" is treated as failure.
"""

from __future__ import annotations

import asyncio
import io
import tarfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiohttp
import numpy as np
import pytest
import requests

from radar.nowcast import LEADS
from radar.odim import read_odim_composite
from radar.tar_range import fetch_tar_members, member_names
from radar.urls import product_url, radvor_prefix


# ---------------------------------------------------------------------------
# Release-candidate generators (walk back from the most recent likely slot)
# ---------------------------------------------------------------------------

def _rs_candidates(now: datetime) -> list[datetime]:
    """RS: 5-minute cadence; start ~10 min back for availability, cover ~1.5 h."""
    ts = now.replace(second=0, microsecond=0)
    ts -= timedelta(minutes=ts.minute % 5 + 10)
    return [ts - timedelta(minutes=5 * i) for i in range(18)]


def _radolan_candidates(minute: int):
    """RADOLAN as the integration reads it: hourly at HH:<minute> (RW :00, SF
    :50), available ~26-30 min later; cover ~6 h."""
    def candidates(now: datetime) -> list[datetime]:
        ts = now.replace(minute=minute, second=0, microsecond=0)
        if ts > now - timedelta(minutes=35):
            ts -= timedelta(hours=1)
        return [ts - timedelta(hours=i) for i in range(6)]
    return candidates


# ---------------------------------------------------------------------------
# Per-product download/parse
# ---------------------------------------------------------------------------

def _parse_rs(content: bytes, ts: datetime) -> np.ndarray:
    fname = radvor_prefix("rs", ts)
    with tarfile.open(fileobj=io.BytesIO(content)) as tf:
        hd5 = tf.extractfile(f"{fname}_000-hd5").read()
    data, _ = read_odim_composite(io.BytesIO(hd5))
    return data


def _parse_radolan(content: bytes, _ts: datetime) -> np.ndarray:
    """RADOLAN in its HDF5 edition: ODIM_H5 on the DE1200 grid."""
    data, _ = read_odim_composite(io.BytesIO(content))
    return data


_PRODUCTS = {
    "rs": {
        "candidates": _rs_candidates,
        "url": lambda ts: product_url("rs", ts),
        "parse": _parse_rs,
        "shape": (1200, 1100),
    },
    "rw": {
        "candidates": _radolan_candidates(0),
        "url": lambda ts: product_url("rw", ts),
        "parse": _parse_radolan,
        "shape": (1200, 1100),
    },
    "sf": {
        "candidates": _radolan_candidates(50),
        "url": lambda ts: product_url("sf", ts),
        "parse": _parse_radolan,
        "shape": (1200, 1100),
    },
}


@pytest.mark.live
@pytest.mark.parametrize("product_id", list(_PRODUCTS))
def test_live_download_and_parse(product_id: str) -> None:
    """Download the most recent available release and parse it with the real parser."""
    product = _PRODUCTS[product_id]
    now = datetime.now(timezone.utc)
    tried: list[str] = []

    for ts in product["candidates"](now):
        url = product["url"](ts)
        tried.append(url)
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
        except requests.RequestException:
            continue

        data = product["parse"](resp.content, ts)
        assert data.shape == product["shape"], (
            f"{product_id}: unexpected grid shape {data.shape} from {url}"
        )
        assert np.issubdtype(data.dtype, np.floating), (
            f"{product_id}: expected floating data, got {data.dtype}"
        )
        assert data.size > 0
        return

    pytest.fail(
        f"No downloadable {product_id} release found in the last window. Tried:\n"
        + "\n".join(tried)
    )


# ---------------------------------------------------------------------------
# Range reads: what RS does every 5 minutes
# ---------------------------------------------------------------------------

@dataclass
class _Response:
    status: int
    headers: object
    content: bytes


async def _read_rs_hours(ts: datetime):
    """Read RS's three hours of release ``ts`` by range, as the integration does."""
    async with aiohttp.ClientSession() as session:
        async def fetch(url, headers):
            async with session.get(url, headers=headers) as resp:
                resp.raise_for_status()  # tar_range turns a 416 into a fallback
                return _Response(resp.status, resp.headers, await resp.read())

        prefix = radvor_prefix("rs", ts)
        return await fetch_tar_members(
            fetch,
            product_url("rs", ts),
            member_names(prefix, LEADS),
            member_names(prefix, (0, 60, 120)),
        )


@pytest.mark.live
def test_live_rs_range_read_needs_no_whole_archive() -> None:
    """DWD still serves ranges and the tar layout the reader expects.

    Otherwise every RS update silently downloads the whole archive (a
    WARNING in the log, values unaffected). Measured: 4 requests, ~20 % of
    the bytes; MAX_REQUESTS is 10.
    """
    tried: list[str] = []
    for ts in _rs_candidates(datetime.now(timezone.utc)):
        tried.append(product_url("rs", ts))
        try:
            result = asyncio.run(_read_rs_hours(ts))
        except aiohttp.ClientResponseError:
            continue  # not published (yet), or rotated away

        assert not result.whole, f"fell back to the whole archive for {tried[-1]}"
        assert len(result.members) == 3
        assert result.requests <= 6, f"{result.requests} requests for {tried[-1]}"
        return

    pytest.fail("No RS release could be range-read. Tried:\n" + "\n".join(tried))
