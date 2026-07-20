"""Tests for scripts/check_release_delay.py.

Network-free: DWD is stubbed with an in-memory ``last_modified`` function that
maps each release URL to a publication time. Lives in the integration tier
because the drift guard imports the real product classes to confirm the ``ast``
extractor agrees with the running integration.
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
    measure,
    previous_release,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Drift guard: extractor must agree with the real integration constants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [RadvorRS, RadolanRW, RadolanSF])
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
# Measurement helpers
# ---------------------------------------------------------------------------

def _configured(interval, delay, offset):
    return {
        "RELEASE_INTERVAL": interval,
        "RELEASE_DELAY": delay,
        "RELEASE_OFFSET": offset,
    }


def _publisher(spec, interval, offset, real_delay, published_before, extra=None):
    """Return a ``last_modified(url)`` mapping each release URL to a publish time.

    A file exists (has a Last-Modified) only if its publish time is at or before
    ``published_before``. ``extra`` overrides the per-timestamp delay to inject
    jitter. The schedule grid is precomputed so URLs resolve exactly.
    """
    extra = extra or {}
    ts_of: dict[str, datetime] = {}
    base = previous_release(published_before, interval, offset)
    for i in range(-2, 200):  # a couple ahead of now, plenty behind
        cand = base - i * interval
        ts_of[spec.url_for(cand)] = cand

    def last_modified(url: str) -> datetime | None:
        ts = ts_of[url]
        publish = ts + extra.get(ts, real_delay)
        return publish if publish <= published_before else None

    return last_modified


# ---------------------------------------------------------------------------
# Measurement + classification
# ---------------------------------------------------------------------------

def test_measure_averages_observed_delay():
    """Mean of the per-file (Last-Modified − nominal) deltas is the observed delay."""
    spec = PRODUCTS["rs"]
    interval = timedelta(minutes=5)
    delay = timedelta(minutes=4, seconds=10)
    offset = timedelta()
    now = datetime(2025, 6, 1, 13, 7, tzinfo=UTC)

    lm = _publisher(spec, interval, offset, real_delay=delay, published_before=now)
    m = measure(spec, _configured(interval, delay, offset), now, last_modified=lm, samples=5)

    assert m.error is None
    assert len(m.deltas) == 5
    assert m.observed == delay
    assert m.status(timedelta(minutes=5)) == "OK"


def test_measure_averages_jittered_delay():
    """Averaging smooths per-file jitter around the true delay."""
    spec = PRODUCTS["rs"]
    interval = timedelta(minutes=5)
    delay = timedelta(minutes=4, seconds=10)
    offset = timedelta()
    now = datetime(2025, 6, 1, 13, 7, tzinfo=UTC)

    # Two files late by 10s, two early by 10s → mean unchanged.
    r0 = previous_release(now, interval, offset) - interval  # first published slot
    jitter = {
        r0: delay + timedelta(seconds=10),
        r0 - interval: delay - timedelta(seconds=10),
        r0 - 2 * interval: delay + timedelta(seconds=10),
        r0 - 3 * interval: delay - timedelta(seconds=10),
    }
    lm = _publisher(spec, interval, offset, real_delay=delay, published_before=now, extra=jitter)
    m = measure(spec, _configured(interval, delay, offset), now, last_modified=lm, samples=4)

    assert len(m.deltas) == 4
    assert m.observed == delay
    assert m.stdev > timedelta()  # jitter is visible in the spread


def test_measure_flags_drift_when_dwd_is_slower():
    """A real delay far above configured is caught as DRIFT."""
    spec = PRODUCTS["rw"]
    interval = timedelta(hours=1)
    offset = timedelta(minutes=50)
    configured_delay = timedelta(minutes=28)
    real_delay = timedelta(minutes=45)  # DWD 17 min slower than configured
    now = datetime(2025, 6, 1, 14, 0, tzinfo=UTC)

    lm = _publisher(spec, interval, offset, real_delay=real_delay, published_before=now)
    m = measure(spec, _configured(interval, configured_delay, offset), now, last_modified=lm, samples=6)

    assert m.observed == real_delay
    assert m.overrun == timedelta(minutes=17)
    assert m.status(timedelta(minutes=5)) == "DRIFT"


def test_measure_faster_dwd_not_flagged():
    """DWD publishing earlier than configured is a negative overrun → OK."""
    spec = PRODUCTS["rw"]
    interval = timedelta(hours=1)
    offset = timedelta(minutes=50)
    configured_delay = timedelta(minutes=28)
    real_delay = timedelta(minutes=20)  # 8 min faster than configured
    now = datetime(2025, 6, 1, 14, 0, tzinfo=UTC)

    lm = _publisher(spec, interval, offset, real_delay=real_delay, published_before=now)
    m = measure(spec, _configured(interval, configured_delay, offset), now, last_modified=lm, samples=6)

    assert m.observed == real_delay
    assert m.overrun == timedelta(minutes=-8)
    assert m.status(timedelta(minutes=5)) == "OK"


def test_measure_small_overrun_within_grace_not_flagged():
    """A mean delay a little past configured, but within grace, is not flagged."""
    spec = PRODUCTS["rw"]
    interval = timedelta(hours=1)
    offset = timedelta(minutes=50)
    configured_delay = timedelta(minutes=28)
    real_delay = timedelta(minutes=31)  # 3 min over, grace is 5
    now = datetime(2025, 6, 1, 14, 0, tzinfo=UTC)

    lm = _publisher(spec, interval, offset, real_delay=real_delay, published_before=now)
    m = measure(spec, _configured(interval, configured_delay, offset), now, last_modified=lm, samples=6)

    assert m.overrun == timedelta(minutes=3)
    assert m.status(timedelta(minutes=5)) == "OK"


def test_measure_skips_unpublished_newest_slots():
    """Newest slots not yet published are skipped; the average uses real files."""
    spec = PRODUCTS["rs"]
    interval = timedelta(minutes=5)
    delay = timedelta(minutes=4, seconds=10)
    offset = timedelta()
    now = datetime(2025, 6, 1, 13, 7, tzinfo=UTC)

    # previous_release(now) = 13:05, which would publish at 13:09:10 > now → 404.
    lm = _publisher(spec, interval, offset, real_delay=delay, published_before=now)
    newest = previous_release(now, interval, offset)
    assert lm(spec.url_for(newest)) is None  # 13:05 not up yet

    m = measure(spec, _configured(interval, delay, offset), now, last_modified=lm, samples=3)
    assert m.error is None
    assert all(d == delay for d in m.deltas)


def test_measure_insufficient_samples_errors():
    spec = PRODUCTS["rs"]
    interval = timedelta(minutes=5)
    delay = timedelta(minutes=4, seconds=10)
    now = datetime(2025, 6, 1, 13, 7, tzinfo=UTC)

    m = measure(
        spec, _configured(interval, delay, timedelta()), now,
        last_modified=lambda _url: None, samples=5, min_samples=3,
    )
    assert m.observed is None
    assert m.status(timedelta(minutes=5)) == "ERROR"
    assert "need 3" in m.error


def test_measurement_status_error():
    m = Measurement("rw", "RadolanRW", timedelta(minutes=28), timedelta(hours=1))
    m.error = "boom"
    assert m.status(timedelta(minutes=5)) == "ERROR"
    assert m.overrun is None
