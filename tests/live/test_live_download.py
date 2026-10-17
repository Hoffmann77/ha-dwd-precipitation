"""Live source-liveness smoke tests — download & parse real DWD OpenData files.

Network-dependent and scheduled (never gates PRs). Marked @live; run with:
  uv run --group unit-test pytest tests/live -m live -v

HA-free by design: the URLs come from radar/urls.py, the same patterns the
integration fetches. If DWD changes a URL scheme, archive layout, range
support or binary format, these tests fail on the schedule and open a
tracking issue — before users hit it.

Which releases to try, and the walk back to one that is up, live in
tests/live_common.py, shared with the live_wradlib tier.
"""

from __future__ import annotations

import asyncio
import io
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import aiohttp
import numpy as np
import pytest

from radar.nowcast import LEADS
from radar.odim import read_odim_composite
from radar.tar_range import fetch_tar_members, member_names, members_from_archive
from radar.urls import product_url, radvor_prefix
from tests.live_common import download_newest, release_candidates


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
        "parse": _parse_rs,
        "shape": (1200, 1100),
    },
    "rw": {
        "parse": _parse_radolan,
        "shape": (1200, 1100),
    },
    "sf": {
        "parse": _parse_radolan,
        "shape": (1200, 1100),
    },
}


@pytest.mark.live
@pytest.mark.parametrize("product_id", list(_PRODUCTS))
def test_live_download_and_parse(product_id: str) -> None:
    """Download the most recent available release and parse it with the real parser."""
    product = _PRODUCTS[product_id]
    content, ts, url = download_newest(product_id)

    data = product["parse"](content, ts)
    assert data.shape == product["shape"], (
        f"{product_id}: unexpected grid shape {data.shape} from {url}"
    )
    assert np.issubdtype(data.dtype, np.floating), (
        f"{product_id}: expected floating data, got {data.dtype}"
    )
    assert data.size > 0


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
    for ts in release_candidates("rs"):
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


# ---------------------------------------------------------------------------
# RS is summed RV: what the hourly forecast series is built on
# ---------------------------------------------------------------------------

_STEP = timedelta(minutes=5)


def _odim_time(what: dict, which: str) -> datetime:
    return datetime.strptime(
        what[f"{which}date"] + what[f"{which}time"], "%Y%m%d%H%M%S"
    ).replace(tzinfo=UTC)


def _decode(payload: bytes) -> tuple[np.ndarray, datetime, datetime]:
    """Return a member's grid (mm) and the window it covers."""
    data, what = read_odim_composite(io.BytesIO(payload))
    return data.astype(np.float64), _odim_time(what, "start"), _odim_time(what, "end")


def _hour_sum(steps: list[np.ndarray]) -> np.ndarray:
    """Add twelve 5-minute grids the way radar.nowcast.rolling_hour_sums does.

    A step without data counts as 0, and a cell no step has data for has no
    hour either. Rounded to the ODIM 0.001 mm resolution, like RS.
    """
    stack = np.stack(steps)
    total = np.nansum(stack, axis=0)
    total[np.isnan(stack).all(axis=0)] = np.nan
    return np.round(total, 3)


async def _rs_and_rv(ts: datetime):
    """Return RS and RV of release ``ts``, and the RV analyses of the 11 before it.

    The analyses are read by range, as the integration's own fills read them.
    """
    async with aiohttp.ClientSession() as session:
        async def fetch(url, headers):
            async with session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                return _Response(resp.status, resp.headers, await resp.read())

        async def whole_release(product: str):
            names = member_names(radvor_prefix(product, ts), LEADS)
            members = members_from_archive((await fetch(product_url(product, ts), {})).content, names)
            return {lead: _decode(members[name]) for lead, name in zip(LEADS, names)}

        async def analysis(release: datetime):
            names = member_names(radvor_prefix("rv", release), LEADS)
            result = await fetch_tar_members(fetch, product_url("rv", release), names, names[:1])
            return _decode(result.members[names[0]])

        rs = await whole_release("rs")
        rv = await whole_release("rv")
        past = [await analysis(ts - k * _STEP) for k in range(11, 0, -1)]
    return rs, rv, past


@pytest.mark.live
def test_live_rs_is_summed_rv() -> None:
    """Every RS member is the sum of the twelve RV 5-minute steps in its hour.

    The hour ending at T+L is made of the RV analyses of the releases up to T,
    then RV T's forecast steps. The peak hour and its hourly series are built
    from RV that way, while "Precipitation last 60 min" and the fixed forecast
    hours still come from RS: if this stops holding, the two disagree. Checked
    cell for cell on the whole grid, for every lead.
    """
    tried: list[str] = []
    for ts in release_candidates("rs"):
        tried.append(f"{ts:%Y-%m-%d %H:%M}")
        try:
            rs, rv, past = asyncio.run(_rs_and_rv(ts))
        except aiohttp.ClientResponseError:
            continue  # not published (yet), or rotated away
        break
    else:
        pytest.fail("No release had RS, RV and the past hour of RV. Tried: " + ", ".join(tried))

    # Five-minute steps by end time: the analyses up to T, then RV T's forecast.
    steps: dict[datetime, np.ndarray] = {}
    for grid, start, end in [*past, *rv.values()]:
        assert end - start == _STEP, f"an RV step covers {start} to {end}"
        steps[end] = grid
    assert sorted(steps) == [ts + (k - 11) * _STEP for k in range(36)]

    for lead in LEADS:
        grid, start, end = rs[lead]
        assert (start, end) == (ts + timedelta(minutes=lead - 60), ts + timedelta(minutes=lead))
        rs_mm = np.round(grid, 3)
        built = _hour_sum([steps[end - k * _STEP] for k in range(12)])
        differ = ~((rs_mm == built) | (np.isnan(rs_mm) & np.isnan(built)))
        assert not differ.any(), (
            f"RS _{lead:03d} of {ts:%Y-%m-%d %H:%M} UTC is not the summed RV steps "
            f"in {int(differ.sum())} of {differ.size} cells"
        )
