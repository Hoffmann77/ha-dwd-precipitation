"""Tests for scripts/check_release_delay.py.

Network-free: DWD probing is stubbed with an in-memory availability function.
Lives in the integration tier because the drift guard imports the real product
classes to confirm the ``ast`` extractor agrees with the running integration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.dwd_precipitation.products import (
    RadolanRW,
    RadolanSF,
    RadvorRS,
)
from scripts.check_release_delay import (
    PRODUCTS,
    Measurement,
    extract_timing,
    find_frontier,
    measure,
    previous_release,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Drift guard: extractor must agree with the real integration constants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "cls",
    [RadvorRS, RadolanRW, RadolanSF],
)
def test_extract_timing_matches_integration(cls):
    """The ast extractor reproduces each class's resolved RELEASE_* constants."""
    timing = extract_timing(cls.__name__)
    assert timing["RELEASE_INTERVAL"] == cls.RELEASE_INTERVAL
    assert timing["RELEASE_DELAY"] == cls.RELEASE_DELAY
    assert timing["RELEASE_OFFSET"] == cls.RELEASE_OFFSET


def test_extract_timing_resolves_inheritance():
    """SF inherits its base's delay while overriding interval/offset upstream."""
    timing = extract_timing("RadolanSF")
    assert timing["RELEASE_INTERVAL"] == timedelta(hours=1)
    assert timing["RELEASE_OFFSET"] == timedelta(minutes=50)
    assert timing["RELEASE_DELAY"] == timedelta(minutes=28)


# ---------------------------------------------------------------------------
# Release schedule
# ---------------------------------------------------------------------------

def test_previous_release_hourly_offset():
    """RW/SF: releases at HH:50 → previous release before 13:20 is 12:50."""
    now = datetime(2025, 6, 1, 13, 20, tzinfo=UTC)
    prev = previous_release(now, timedelta(hours=1), timedelta(minutes=50))
    assert prev == datetime(2025, 6, 1, 12, 50, tzinfo=UTC)


def test_previous_release_five_minute():
    now = datetime(2025, 6, 1, 13, 22, tzinfo=UTC)
    prev = previous_release(now, timedelta(minutes=5), timedelta())
    assert prev == datetime(2025, 6, 1, 13, 20, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Frontier detection
# ---------------------------------------------------------------------------

def _availability(published_upto: datetime, url_for, interval, anchor):
    """Return an ``available(url)`` that maps a URL back to a timestamp.

    Any release at or before ``published_upto`` is available. URLs are matched
    by regenerating each candidate timestamp's URL and comparing.
    """
    known = {}
    ts = anchor - 50 * interval
    while ts <= anchor + 50 * interval:
        known[url_for(ts)] = ts
        ts += interval

    def available(url: str) -> bool:
        return known[url] <= published_upto

    return available


def test_find_frontier_walks_back_when_dwd_is_slow():
    spec = PRODUCTS["rw"]
    interval = timedelta(hours=1)
    anchor = datetime(2025, 6, 1, 12, 50, tzinfo=UTC)
    published = datetime(2025, 6, 1, 10, 50, tzinfo=UTC)
    available = _availability(published, spec.url_for, interval, anchor)

    # Start optimistically at 12:50 (DWD only up to 10:50) → walk back.
    frontier = find_frontier(spec.url_for, anchor, interval, available)
    assert frontier == published


def test_find_frontier_walks_forward_when_dwd_is_fast():
    spec = PRODUCTS["rw"]
    interval = timedelta(hours=1)
    anchor = datetime(2025, 6, 1, 12, 50, tzinfo=UTC)
    published = datetime(2025, 6, 1, 14, 50, tzinfo=UTC)
    available = _availability(published, spec.url_for, interval, anchor)

    frontier = find_frontier(spec.url_for, anchor, interval, available)
    assert frontier == published


# ---------------------------------------------------------------------------
# Measurement + classification (window fallback, no polling)
# ---------------------------------------------------------------------------

def _configured(interval, delay, offset):
    return {
        "RELEASE_INTERVAL": interval,
        "RELEASE_DELAY": delay,
        "RELEASE_OFFSET": offset,
    }


def test_measure_window_ok_when_delay_matches():
    spec = PRODUCTS["rw"]
    interval = timedelta(hours=1)
    delay = timedelta(minutes=28)
    offset = timedelta(minutes=50)

    # now = 13:18 → frontier 12:50 was published, 13:50 not yet.
    now = datetime(2025, 6, 1, 13, 18, tzinfo=UTC)
    published = datetime(2025, 6, 1, 12, 50, tzinfo=UTC)
    available = _availability(published, spec.url_for, interval, now.replace(minute=50))

    m = measure(spec, _configured(interval, delay, offset), now, available=available, poll=False)

    assert m.error is None
    assert m.frontier == published
    # window: (now-13:50, now-12:50) = (-32m, 28m); midpoint = -2m.
    assert m.observed == timedelta(minutes=-2)
    assert m.uncertainty == interval / 2
    # 28m configured vs -2m observed → deviation 30m ≤ tol (30m + grace).
    assert m.status(timedelta(minutes=5)) == "OK"


def test_measure_flags_drift_beyond_tolerance():
    """A frontier far older than configured delay → deviation exceeds tolerance."""
    spec = PRODUCTS["rw"]
    interval = timedelta(hours=1)
    offset = timedelta(minutes=50)
    delay = timedelta(minutes=28)

    # DWD is badly behind: newest published release is 3h before configured.
    now = datetime(2025, 6, 1, 13, 18, tzinfo=UTC)
    published = datetime(2025, 6, 1, 9, 50, tzinfo=UTC)
    available = _availability(published, spec.url_for, interval, now.replace(minute=50))

    m = measure(spec, _configured(interval, delay, offset), now, available=available, poll=False)

    # frontier 9:50 → window (now-10:50, now-9:50) = (2h28m, 3h28m), midpoint 2h58m.
    assert m.observed == timedelta(hours=2, minutes=58)
    # deviation |28m - 2h58m| = 2h30m ≫ tol (30m + 5m) → DRIFT.
    assert m.status(timedelta(minutes=5)) == "DRIFT"


class _FakeClock:
    """Monotonic clock that only advances when sleep() is called."""

    def __init__(self):
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def test_measure_exact_samples_average():
    """With polling, consecutive appearances are averaged and uncertainty is 0."""
    spec = PRODUCTS["rs"]
    interval = timedelta(minutes=5)
    delay = timedelta(minutes=4, seconds=10)
    offset = timedelta()

    now = datetime(2025, 6, 1, 13, 4, 10, tzinfo=UTC)
    ts_of = {}
    base = previous_release(now, interval, offset)  # align grid to the :00/:05… schedule
    ts = base - 30 * interval
    while ts <= base + 30 * interval:
        ts_of[spec.url_for(ts)] = ts
        ts += interval

    # Frontier 13:00 already up; 13:05 appears exactly at 13:09:10 (delay 4m10s).
    published = {"upto": datetime(2025, 6, 1, 13, 0, tzinfo=UTC)}
    wall = {"t": now}
    clock = _FakeClock()

    ts_1305 = datetime(2025, 6, 1, 13, 5, tzinfo=UTC)

    def available(url: str) -> bool:
        # Model 13:05 landing at 13:09:10 by keying its arrival to the fake clock:
        # after ~5 minutes of polling it becomes available and wall-time is 13:09:10.
        if ts_of[url] == ts_1305 and clock.t >= 5 * 60 and published["upto"] < ts_1305:
            published["upto"] = ts_1305
            wall["t"] = datetime(2025, 6, 1, 13, 9, 10, tzinfo=UTC)
        return ts_of[url] <= published["upto"]

    m = measure(
        spec, _configured(interval, delay, offset), now,
        available=available, poll=True,
        max_poll_wait=timedelta(minutes=11),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        wall_now=lambda: wall["t"],
    )

    assert m.error is None
    assert m.exact_samples  # captured at least one appearance
    assert m.uncertainty == timedelta()
    assert m.observed == timedelta(minutes=4, seconds=10)
    assert m.status(timedelta(minutes=5)) == "OK"


def test_measurement_status_error():
    m = Measurement("rw", "RadolanRW", timedelta(minutes=28), timedelta(hours=1))
    m.error = "boom"
    assert m.status(timedelta(minutes=5)) == "ERROR"
    assert m.deviation is None
