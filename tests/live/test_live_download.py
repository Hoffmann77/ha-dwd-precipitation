"""Live source-liveness smoke tests — download & parse real DWD OpenData files.

Network-dependent and scheduled (never gates PRs). Marked @live; run with:
  uv run --group unit-test pytest tests/live -m live -v

HA-free by design: const.py imports homeassistant, so the DWD base URLs are
hardcoded here. If DWD changes a URL scheme, archive layout, or binary format,
these tests fail on the schedule and open a tracking issue — before users hit it.

Robustness: OpenData publishes with a delay and rotates files, so the freshest
slot is often not up yet. Each product walks back several releases until one
downloads; only "nothing downloadable at all" is treated as failure.
"""

from __future__ import annotations

import bz2
import io
import tarfile
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
import requests

from radar import read_odim_composite, read_radolan_composite

_OPENDATA = "https://opendata.dwd.de/weather/radar"


# ---------------------------------------------------------------------------
# Release-candidate generators (walk back from the most recent likely slot)
# ---------------------------------------------------------------------------

def _rs_candidates(now: datetime) -> list[datetime]:
    """RS: 5-minute cadence; start ~10 min back for availability, cover ~1.5 h."""
    ts = now.replace(second=0, microsecond=0)
    ts -= timedelta(minutes=ts.minute % 5 + 10)
    return [ts - timedelta(minutes=5 * i) for i in range(18)]


def _radolan_candidates(now: datetime) -> list[datetime]:
    """RADOLAN RW/SF: hourly at HH:50, available ~28 min later; cover ~6 h."""
    ts = now.replace(minute=50, second=0, microsecond=0)
    if ts > now - timedelta(minutes=35):
        ts -= timedelta(hours=1)
    return [ts - timedelta(hours=i) for i in range(6)]


# ---------------------------------------------------------------------------
# Per-product download/parse
# ---------------------------------------------------------------------------

def _parse_rs(content: bytes, ts: datetime) -> np.ndarray:
    fname = f"composite_rs_{ts.strftime('%Y%m%d_%H%M')}"
    with tarfile.open(fileobj=io.BytesIO(content)) as tf:
        hd5 = tf.extractfile(f"{fname}_000-hd5").read()
    data, _ = read_odim_composite(io.BytesIO(hd5))
    return data


def _parse_radolan(content: bytes, _ts: datetime) -> np.ndarray:
    data, _ = read_radolan_composite(bz2.open(io.BytesIO(content)))
    return data


_PRODUCTS = {
    "rs": {
        "candidates": _rs_candidates,
        "url": lambda ts: (
            f"{_OPENDATA}/composite/rs/composite_rs_{ts.strftime('%Y%m%d_%H%M')}.tar"
        ),
        "parse": _parse_rs,
        "shape": (1200, 1100),
    },
    "rw": {
        "candidates": _radolan_candidates,
        "url": lambda ts: (
            f"{_OPENDATA}/radolan/rw/raa01-rw_10000-"
            f"{ts.strftime('%y%m%d%H%M')}-dwd---bin.bz2"
        ),
        "parse": _parse_radolan,
        "shape": (900, 900),
    },
    "sf": {
        "candidates": _radolan_candidates,
        "url": lambda ts: (
            f"{_OPENDATA}/radolan/sf/raa01-sf_10000-"
            f"{ts.strftime('%y%m%d%H%M')}-dwd---bin.bz2"
        ),
        "parse": _parse_radolan,
        "shape": (900, 900),
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
