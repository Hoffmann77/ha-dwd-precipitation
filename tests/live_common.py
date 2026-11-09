"""What the live tiers share: which releases to try, and the download walk.

OpenData publishes with a delay and rotates files, so the newest release is
often not up yet. Both live tiers start at the newest release that should be
up and walk back on the product's own release grid until one downloads; only
"nothing downloadable at all" is a failure. HA-free.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import requests

from radar.urls import product_url
from release_grid import ReleaseGrid

_FIVE_MINUTES = timedelta(minutes=5)
_HOUR = timedelta(hours=1)

# The files as the integration reads them: the release grid (interval,
# offset), how long after its nominal time a file is reliably up, and how
# many releases to try (~1.5 h of 5-minute ones, 6 hourly ones).
_WALKS = {
    "rs": (_FIVE_MINUTES, timedelta(), timedelta(minutes=10), 18),
    "rv": (_FIVE_MINUTES, timedelta(), timedelta(minutes=10), 18),
    "hymecng": (_FIVE_MINUTES, timedelta(), timedelta(minutes=10), 18),
    "rw": (_HOUR, timedelta(), timedelta(minutes=35), 6),  # the :00 run
    "sf": (_HOUR, timedelta(minutes=50), timedelta(minutes=35), 6),  # :50 only
}


def release_candidates(product: str, now: datetime | None = None) -> list[datetime]:
    """Return the releases of ``product`` worth trying, newest first."""
    interval, offset, lag, count = _WALKS[product]
    grid = ReleaseGrid(interval, offset)
    newest = grid.at_or_before((now or datetime.now(UTC)) - lag)
    return [grid.back(newest, steps) for steps in range(count)]


def download_newest(product: str, timeout: float = 60) -> tuple[bytes, datetime, str]:
    """Return (content, release, url) of the newest downloadable release."""
    tried: list[str] = []
    for ts in release_candidates(product):
        url = product_url(product, ts)
        tried.append(url)
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
        except requests.RequestException:
            continue
        return resp.content, ts, url
    pytest.fail(f"No downloadable {product} release found. Tried:\n" + "\n".join(tried))
