#!/usr/bin/env python3
"""Check how DWD builds RADVOR RS from RV, on live OpenData files.

RS members are rolling 60-minute sums, RV members 5-minute amounts. For an RS
release at time T this compares, grid-wide:

* ``RS _000`` (T-60 -> T) with the sum of lead 0 from the twelve RV releases
  T-55 .. T -- i.e. whether the past hour is built from the radar *analyses*
  rather than from a forecast shifted back in time;
* ``RS _060`` (T -> T+60) and ``RS _120`` (T+60 -> T+120) with the sums of
  RV leads 5..60 and 65..120 of release T;
* ``RS _030`` (T-30 -> T+30) with the past half hour of lead-0 analyses plus
  RV leads 5..30 of release T -- a window straddling now.

It also prints each member's ``how/simulated`` flag, DWD's own marker for
observation (False) vs. forecast (True).

Usage::

    uv run python scripts/verify_rs_rv.py 20261011_1610 [20261011_1205 ...]

DWD keeps about two days of RS/RV files, so pick recent timestamps. Each RS
release needs 13 downloads (~60 MB); they are cached in ``--cache``.
The README section "How DWD data is interpreted" quotes the results.
"""

from __future__ import annotations

import argparse
import io
import sys
import tarfile
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import h5py
import numpy as np

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components/dwd_precipitation/radar")
)
from odim import read_odim_composite

BASE = "https://opendata.dwd.de/weather/radar/composite"
# ODIM ACRR resolution: two values that agree to within one step are equal.
TOLERANCE_MM = 0.0015


def _member(cache: Path, product: str, ts: datetime, lead: int):
    """Return (mm grid, dataset what, simulated flag) for one member."""
    name = f"composite_{product}_{ts:%Y%m%d_%H%M}.tar"
    path = cache / name
    if not path.exists():
        urllib.request.urlretrieve(f"{BASE}/{product}/{name}", path)
    with tarfile.open(path) as tar:
        info = next(m for m in tar.getmembers() if m.name.endswith(f"_{lead:03d}-hd5"))
        content = tar.extractfile(info).read()
    data, what = read_odim_composite(io.BytesIO(content))
    with h5py.File(io.BytesIO(content), "r") as hf:
        simulated = hf["how"].attrs.get("simulated", b"?")
    if isinstance(simulated, bytes):
        simulated = simulated.decode()
    return data.astype(np.float64), what, simulated


def _compare(label: str, rs: np.ndarray, summed: np.ndarray) -> None:
    both = ~np.isnan(rs) & ~np.isnan(summed)
    diff = np.abs(rs[both] - summed[both])
    wet = both & ((rs > 0) | (summed > 0))
    off = int((diff > TOLERANCE_MM).sum())
    print(f"  {label}")
    print(
        f"    {both.sum()} cells with data, {wet.sum()} wet; "
        f"{off} differ by more than {TOLERANCE_MM} mm "
        f"({100 * off / max(both.sum(), 1):.3f} %), max {diff.max():.3f} mm"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("releases", nargs="+", help="RS release times, YYYYMMDD_HHMM (UTC)")
    parser.add_argument("--cache", type=Path, default=Path(".dwd_cache"))
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)

    def member(product, ts, lead):
        return _member(args.cache, product, ts, lead)

    for release in args.releases:
        t = datetime.strptime(release, "%Y%m%d_%H%M").replace(tzinfo=UTC)
        print(f"== RS {t:%Y-%m-%d %H:%M} UTC")

        rv0 = {k: member("rv", t - timedelta(minutes=5 * k), 0)[0] for k in range(12)}
        rv_t = {lead: member("rv", t, lead)[0] for lead in range(5, 121, 5)}

        _compare(
            "RS _000 vs sum of RV lead 0, releases T-55..T",
            member("rs", t, 0)[0], sum(rv0.values()),
        )
        _compare(
            "RS _060 vs sum of RV leads 5..60, release T",
            member("rs", t, 60)[0], sum(rv_t[lead] for lead in range(5, 61, 5)),
        )
        _compare(
            "RS _120 vs sum of RV leads 65..120, release T",
            member("rs", t, 120)[0], sum(rv_t[lead] for lead in range(65, 121, 5)),
        )
        _compare(
            "RS _030 vs RV lead 0 of T-25..T + RV leads 5..30 of T",
            member("rs", t, 30)[0],
            sum(rv0[k] for k in range(6)) + sum(rv_t[lead] for lead in range(5, 31, 5)),
        )

        for product, leads in (("rv", (0, 5)), ("rs", (0, 5, 60))):
            for lead in leads:
                _, what, simulated = member(product, t, lead)
                print(
                    f"  {product.upper()} _{lead:03d}: {what.get('starttime')}"
                    f"-{what.get('endtime')} UTC, simulated={simulated}"
                )


if __name__ == "__main__":
    main()
