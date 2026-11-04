#!/usr/bin/env python3
"""Validate the integration's RELEASE_DELAY against DWD OpenData reality.

Each DWD product declares a ``RELEASE_DELAY`` — how long after the nominal
product time a file is expected to appear on OpenData. The coordinator waits
exactly that long before fetching (``_get_latest_release``), so if DWD's real
publication lag drifts away from the configured value the integration either
polls too early (repeated 404 + fast-poll churn) or too late (needlessly stale
sensors).

This script measures the *observed* availability delay for each probeable
product and checks it does not deviate too far from the configured constant.
The configured constants are the product classes' own, imported (so it runs in
the ``ha-test`` environment), and DWD is probed with ``requests``.

How the delay is measured
-------------------------
For a product with interval ``I`` and offset ``O`` the releases occur at
nominal timestamps ``k*I + O`` — the timestamp encoded in each filename. For
each of the most recent files we read its ``Last-Modified`` response header,
which is the moment DWD actually published the file (RFC 7231 mandates GMT, so
there is no timezone ambiguity). The observed delay of one file is

    Last-Modified − nominal_timestamp

and we average that over the most recent published files — DWD keeps a rolling
window of them, so this is a stable central estimate rather than a single
noisy probe. No polling or waiting: every sample is an exact, already
published fact.

The workflow now runs once every 24h, so the sample count per product is
sized to cover a fixed real-world window rather than a fixed file count
(``--samples``, when passed explicitly, overrides this per-product sizing for
every product): RS/RV/HymecNG (5 min interval) sample ``TARGET_WINDOW_HOURS``
worth of files (12h) so a slow drift is still visible within one run; RW/SF
(1h interval) sample 24h, unchanged from before — for those, catching a drift
now takes two consecutive daily runs (48h) instead of two runs 12h apart.

A product is flagged the instant the mean observed delay exceeds the configured
``RELEASE_DELAY`` (``--grace`` defaults to 0): that is the harmful direction —
DWD publishing later than the coordinator waits, so it fetches too early and
404s until the file appears. DWD being *faster* than configured is only a small
latency cost and is not flagged.

Exit status: ``0`` all products within tolerance, ``1`` at least one drifted,
``2`` a product could not be measured (too few files / network error).

Usage::

    uv run --group ha-test python scripts/check_release_delay.py
    uv run --group ha-test python scripts/check_release_delay.py --products rs
    uv run --group ha-test python scripts/check_release_delay.py --samples 36
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

UTC = timezone.utc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from custom_components.dwd_precipitation import products  # noqa: E402
from custom_components.dwd_precipitation.radar.urls import product_url  # noqa: E402
from custom_components.dwd_precipitation.release_grid import ReleaseGrid  # noqa: E402

RELEASE_KEYS = ("RELEASE_INTERVAL", "RELEASE_DELAY", "RELEASE_OFFSET")

# Stop scanning back once this many consecutive nominal slots are missing —
# either we are above the frontier (newest not published yet) with a wildly
# wrong delay, or we fell off the folder's retention window.
_MISS_CAP = 8


# ---------------------------------------------------------------------------
# Release schedule
# ---------------------------------------------------------------------------

def previous_release(now: datetime, interval: timedelta, offset: timedelta) -> datetime:
    """Most recent scheduled release timestamp at or before ``now`` (UTC grid).

    The integration's own arithmetic (release_grid.ReleaseGrid), so the probe
    and the coordinator cannot disagree about which files exist.
    """
    return ReleaseGrid(interval, offset).at_or_before(now)


# ---------------------------------------------------------------------------
# Product probe specs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProductSpec:
    """Everything needed to probe one product's availability."""

    key: str
    cls: type  # the product's coordinator class, whose RELEASE_* it checks
    url_for: Callable[[datetime], str]

    def timing(self) -> dict[str, timedelta]:
        """Return the class's configured RELEASE_* constants."""
        return {key: getattr(self.cls, key) for key in RELEASE_KEYS}


def _spec(cls: type) -> ProductSpec:
    """Probe the files the integration fetches for this product."""
    key = cls.PRODUCT_KEY
    return ProductSpec(key, cls, lambda ts: product_url(key, ts))


# Every product with its own release grid in UTC. sf_2350 is not probed on its
# own: it reads SF's files on a local-time grid, with SF's RELEASE_DELAY (a
# test pins that), so "sf" measures its lag too.
PRODUCTS: dict[str, ProductSpec] = {
    spec.key: spec
    for spec in map(
        _spec,
        (
            products.RadvorRS,
            products.RadvorRV,
            products.HymecNG,
            products.RadolanRW,
            products.RadolanRW10,  # RW's 10-minute runs: RW's files, every 10 minutes
            products.RadolanSF,
        ),
    )
}

# Real-world span the rolling window should cover, per product — sized so a
# slow drift is visible within a single (now once-daily) run rather than
# needing several days to accumulate enough samples. Converted to a sample
# count via each product's actual RELEASE_INTERVAL in main().
TARGET_WINDOW_HOURS: dict[str, float] = {
    "rs": 12,
    "rv": 12,
    "hymecng": 12,
    "rw": 24,
    "rw_10min": 24,
    "sf": 24,
}


def http_last_modified(url: str, timeout: float = 60.0, attempts: int = 3) -> datetime | None:
    """Return the file's ``Last-Modified`` time (UTC), or None if it is absent.

    Uses HEAD (no body) and falls back to a streamed GET if HEAD is rejected.
    Raises on network errors after retries so a flaky run is not read as "no
    drift".
    """
    import requests  # imported lazily so the module loads without the dep
    from email.utils import parsedate_to_datetime

    last_err: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = requests.head(url, timeout=timeout, allow_redirects=True)
            if resp.status_code == 405:  # some servers disallow HEAD
                resp = requests.get(url, stream=True, timeout=timeout)
                resp.close()
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            raw = resp.headers.get("Last-Modified")
            if not raw:
                return None
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except requests.HTTPError:
            raise
        except requests.RequestException as err:
            last_err = err
            time.sleep((attempt + 1) * 0.5)
    raise RuntimeError(f"network error probing {url}: {last_err}")


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

@dataclass
class Measurement:
    """Outcome of measuring one product's availability delay."""

    key: str
    class_name: str
    configured: timedelta
    interval: timedelta
    deltas: list[timedelta] = field(default_factory=list)
    error: str | None = None

    @property
    def observed(self) -> timedelta | None:
        """Mean observed delay across the sampled files."""
        if not self.deltas:
            return None
        return sum(self.deltas, timedelta()) / len(self.deltas)

    @property
    def spread(self) -> tuple[timedelta, timedelta] | None:
        if not self.deltas:
            return None
        return (min(self.deltas), max(self.deltas))

    @property
    def stdev(self) -> timedelta | None:
        if len(self.deltas) < 2:
            return timedelta()
        return timedelta(seconds=statistics.stdev(d.total_seconds() for d in self.deltas))

    @property
    def overrun(self) -> timedelta | None:
        """Signed amount the mean delay runs past the configured delay.

        Positive = DWD slower than the coordinator waits (the harmful case);
        negative = DWD publishes earlier than configured.
        """
        if self.observed is None:
            return None
        return self.observed - self.configured

    def status(self, grace: timedelta) -> str:
        if self.error is not None or self.observed is None:
            return "ERROR"
        return "DRIFT" if self.overrun > grace else "OK"


def measure(
    spec: ProductSpec,
    configured: dict[str, timedelta],
    now: datetime,
    *,
    last_modified: Callable[[str], datetime | None] = http_last_modified,
    samples: int = 24,
    min_samples: int = 3,
) -> Measurement:
    """Average the observed availability delay over recent published files.

    Walks the release schedule backward from ``now``, reading each file's
    publication time, until ``samples`` files have been measured or the folder's
    recent window is exhausted.
    """
    interval = configured["RELEASE_INTERVAL"]
    offset = configured["RELEASE_OFFSET"]
    delay = configured["RELEASE_DELAY"]
    m = Measurement(spec.key, spec.cls.__name__, delay, interval)

    try:
        ts = previous_release(now, interval, offset)
        max_scan = samples * 3 + _MISS_CAP
        consecutive_misses = 0
        scanned = 0

        while len(m.deltas) < samples and scanned < max_scan:
            scanned += 1
            published = last_modified(spec.url_for(ts))
            if published is None:
                consecutive_misses += 1
                if consecutive_misses > _MISS_CAP:
                    break
            else:
                consecutive_misses = 0
                m.deltas.append(published - ts)
            ts -= interval

        if len(m.deltas) < min_samples:
            m.error = (
                f"only {len(m.deltas)} published file(s) found in the last "
                f"{scanned} slots (need {min_samples})"
            )
    except Exception as err:  # network / logic — reported, never crashes the run
        m.error = str(err)

    return m


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _fmt(td: timedelta | None) -> str:
    if td is None:
        return "—"
    total = int(td.total_seconds())
    sign = "-" if total < 0 else ""
    total = abs(total)
    return f"{sign}{total // 60}m{total % 60:02d}s"


def _report_lines(measurements: list[Measurement], grace: timedelta) -> list[str]:
    header = f"{'product':<10}{'status':<8}{'configured':>12}{'observed':>12}{'overrun':>12}{'grace':>10}"
    lines = [header, "-" * len(header)]
    for m in measurements:
        lines.append(
            f"{m.key:<10}{m.status(grace):<8}"
            f"{_fmt(m.configured):>12}{_fmt(m.observed):>12}"
            f"{_fmt(m.overrun):>12}{_fmt(grace):>10}"
        )
        if m.error:
            lines.append(f"         └ error: {m.error}")
        elif m.spread:
            lines.append(
                f"         └ {len(m.deltas)} files | "
                f"min {_fmt(m.spread[0])}, max {_fmt(m.spread[1])}, "
                f"σ {_fmt(m.stdev)}"
            )
    return lines


def _write_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("## DWD release-delay check\n\n```\n" + text + "\n```\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--products", nargs="+", choices=list(PRODUCTS), default=list(PRODUCTS),
        help="products to check (default: all probeable products)",
    )
    parser.add_argument(
        "--grace", type=float, default=0.0,
        help="minutes the mean delay may exceed the configured RELEASE_DELAY "
             "before flagging (default: 0 — flag the instant it is exceeded)",
    )
    parser.add_argument(
        "--samples", type=int, default=None,
        help="number of recent files to average per product (default: sized "
             "per product from TARGET_WINDOW_HOURS via its RELEASE_INTERVAL)",
    )
    parser.add_argument(
        "--min-samples", type=int, default=3,
        help="minimum files required to report a measurement (default: 3)",
    )
    args = parser.parse_args(argv)

    grace = timedelta(minutes=args.grace)
    now = datetime.now(UTC)

    measurements: list[Measurement] = []
    for key in args.products:
        spec = PRODUCTS[key]
        configured = spec.timing()
        if args.samples is not None:
            samples = args.samples
        else:
            window = timedelta(hours=TARGET_WINDOW_HOURS[key])
            samples = max(1, int(window / configured["RELEASE_INTERVAL"]))
        measurements.append(
            measure(spec, configured, now, samples=samples, min_samples=args.min_samples)
        )

    report = "\n".join(_report_lines(measurements, grace))
    print(report)
    _write_summary(report)

    statuses = [m.status(grace) for m in measurements]
    if "ERROR" in statuses:
        return 2
    if "DRIFT" in statuses:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
