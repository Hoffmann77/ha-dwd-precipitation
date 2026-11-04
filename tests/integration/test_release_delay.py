"""Tests for scripts/check_release_delay.py.

Network-free: DWD is stubbed with an in-memory ``last_modified`` function that
maps each release URL to a publication time. Lives in the integration tier
because the script imports the product classes, whose constants it checks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.dwd_precipitation import PRODUCT_CLASSES
from custom_components.dwd_precipitation.products import (
    RadolanSF,
    RadolanSFLastYesterday,
)
from scripts.check_release_delay import (
    PRODUCTS,
    Measurement,
    measure,
    previous_release,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# What is probed
# ---------------------------------------------------------------------------

def test_every_utc_product_is_probed():
    """A product the probe skips would let its RELEASE_DELAY drift unnoticed."""
    probed = {spec.cls for spec in PRODUCTS.values()}
    assert probed == {cls for cls in PRODUCT_CLASSES if not cls.USE_LOCAL_TIME}


def test_the_probe_checks_the_class_constants():
    timing = PRODUCTS["sf"].timing()
    assert timing == {
        "RELEASE_INTERVAL": RadolanSF.RELEASE_INTERVAL,
        "RELEASE_DELAY": RadolanSF.RELEASE_DELAY,
        "RELEASE_OFFSET": RadolanSF.RELEASE_OFFSET,
    }


async def test_sf_2350_waits_like_the_sf_it_reads(make_coordinator):
    """sf_2350 is not probed on its own: it reads SF's files, so SF's lag is its."""
    assert RadolanSFLastYesterday.RELEASE_DELAY == RadolanSF.RELEASE_DELAY
    ts = datetime(2026, 7, 3, 21, 50, tzinfo=UTC)
    sf_2350 = make_coordinator(RadolanSFLastYesterday)
    assert PRODUCTS["sf"].url_for(ts) == sf_2350._get_url(ts)


# ---------------------------------------------------------------------------
# Release schedule
# ---------------------------------------------------------------------------

def test_previous_release_hourly_offset():
    """SF: releases at HH:50 → previous release before 13:20 is 12:50."""
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


def test_measure_strict_flags_any_overrun():
    """With grace=0 (the default), a mean even seconds past configured flags."""
    spec = PRODUCTS["rw"]
    interval = timedelta(hours=1)
    offset = timedelta(minutes=50)
    configured_delay = timedelta(minutes=28)
    now = datetime(2025, 6, 1, 14, 0, tzinfo=UTC)

    # 30 s over configured → flagged; exactly equal → OK (strictly "exceeds").
    over = _publisher(spec, interval, offset, configured_delay + timedelta(seconds=30), now)
    m_over = measure(spec, _configured(interval, configured_delay, offset), now, last_modified=over, samples=6)
    assert m_over.overrun == timedelta(seconds=30)
    assert m_over.status(timedelta()) == "DRIFT"

    equal = _publisher(spec, interval, offset, configured_delay, now)
    m_equal = measure(spec, _configured(interval, configured_delay, offset), now, last_modified=equal, samples=6)
    assert m_equal.overrun == timedelta()
    assert m_equal.status(timedelta()) == "OK"


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
