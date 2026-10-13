"""Compare RW's sub-hourly runs with its HH:50 runs against radar-only RS.

DWD publishes RW (the gauge-adjusted hourly analysis) every 10 minutes: a
sliding hour ending at :00, :10, ... :50. The integration used only the HH:50
run up to 2026.10.0 (it reads HH:00 since). Before anything relies on the
others, this checks whether they are gauge-adjusted just as strongly, or
whether only HH:50 gets the full set of gauges.

RW and RS ``_000`` cover the same window (the hour ending at T), and RW's
HDF5 edition sits on RS's 1100x1200 grid, so the two compare cell for cell.
RS is radar only; how far RW departs from it is how much the gauges moved the
value. If the sub-hourly runs track RS more closely than HH:50 does, they use
fewer gauges.

Fetches every RW run still on OpenData (48 h) and, for each, only the ``_000``
member of the matching RS archive (by range read), then prints per-run-minute
statistics over wet cells.

Usage: python scripts/compare_rw_runs.py [--hours 48] [--wet 0.5]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components/dwd_precipitation"))

from radar.odim import read_odim_composite  # noqa: E402
from radar.tar_range import fetch_tar_members, member_names  # noqa: E402

RW_DIR = "https://opendata.dwd.de/weather/radar/radolan/rw/"
RS_DIR = "https://opendata.dwd.de/weather/radar/composite/rs/"
LEADS = list(range(0, 121, 5))


class _Response:
    def __init__(self, status, headers, content):
        self.status, self.headers, self.content = status, headers, content


async def _get(session, url, headers=None):
    async with session.get(url, headers=headers) as resp:
        resp.raise_for_status()
        return _Response(resp.status, resp.headers, await resp.read())


async def _pair(session, t: datetime, wet: float):
    """Return per-run statistics for the hour ending at t, or None."""
    rw_url = f"{RW_DIR}raa01-rw_10000-{t:%y%m%d%H%M}-dwd---bin.hdf5"
    rs_name = f"composite_rs_{t:%Y%m%d_%H%M}"
    rs_url = f"{RS_DIR}{rs_name}.tar"
    try:
        rw_bytes = (await _get(session, rw_url)).content
        read = await fetch_tar_members(
            lambda url, headers: _get(session, url, headers),
            rs_url,
            member_names(rs_name, LEADS),
            [f"{rs_name}_000-hd5"],
            lambda: _whole(session, rs_url),
        )
    except aiohttp.ClientResponseError:
        return None
    rs_member = read.members.get(f"{rs_name}_000-hd5")
    if rs_member is None:
        return None

    rw = read_odim_composite(io.BytesIO(rw_bytes))[0]
    rs = read_odim_composite(io.BytesIO(rs_member))[0]
    both = ~np.isnan(rw) & ~np.isnan(rs)
    wet_cells = both & ((rw >= wet) | (rs >= wet))
    n = int(wet_cells.sum())
    if n < 200:
        return None
    diff = np.abs(rw[wet_cells] - rs[wet_cells])
    ratio_cells = both & (rs >= wet)
    ratio = rw[ratio_cells] / rs[ratio_cells]
    return {
        "t": t,
        "wet_cells": n,
        "mean_abs_diff": float(diff.mean()),
        "rel_diff": float(diff.sum() / max(rs[wet_cells].sum(), 1e-9)),
        "adjusted_share": float((diff > 0.15).mean()),  # beyond RW's 0.1 mm step
        "median_ratio": float(np.median(ratio)) if ratio.size else float("nan"),
    }


async def _whole(session, url):
    return (await _get(session, url)).content


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--hours", type=int, default=48)
    parser.add_argument("--wet", type=float, default=0.5, help="mm/h that counts as wet")
    args = parser.parse_args()

    async with aiohttp.ClientSession() as session:
        listing = (await _get(session, RW_DIR)).content.decode()
        stamps = sorted(set(re.findall(r"raa01-rw_10000-(\d{10})-dwd---bin\.hdf5", listing)))
        times = [
            datetime.strptime(s, "%y%m%d%H%M").replace(tzinfo=timezone.utc) for s in stamps
        ]
        cutoff = times[-1] - timedelta(hours=args.hours)
        times = [t for t in times if t > cutoff]

        sem = asyncio.Semaphore(4)

        async def bounded(t):
            async with sem:
                return await _pair(session, t, args.wet)

        results = [r for r in await asyncio.gather(*(bounded(t) for t in times)) if r]

    by_minute = defaultdict(list)
    for r in results:
        by_minute[r["t"].minute].append(r)

    print(f"{len(results)} of {len(times)} runs had enough wet cells (>= {args.wet} mm)")
    print(f"{'run':>5} {'n':>4} {'wet cells':>10} {'mean |RW-RS|':>13} "
          f"{'rel. diff':>10} {'adjusted':>9} {'median RW/RS':>13}")
    for minute in sorted(by_minute):
        rows = by_minute[minute]

        def med(key):
            return statistics.median(r[key] for r in rows)

        print(f"  :{minute:02d} {len(rows):>4} {med('wet_cells'):>10.0f} "
              f"{med('mean_abs_diff'):>12.3f}  {med('rel_diff'):>9.1%} "
              f"{med('adjusted_share'):>8.1%} {med('median_ratio'):>13.3f}")
    print("Columns are medians over the runs at that minute.")


if __name__ == "__main__":
    asyncio.run(main())
