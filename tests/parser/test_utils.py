"""Unit tests for utils.py timing math — no HA, no network."""

from datetime import datetime, timedelta, timezone

from utils import get_previous_multiple, mydatetime

UTC = timezone.utc


# ===========================================================================
# get_previous_multiple
# ===========================================================================

def test_hourly_with_offset():
    """RADOLAN-style grid at HH:50 — previous release before 12:32 is 11:50."""
    ts = datetime(2025, 6, 1, 12, 32, tzinfo=UTC)
    result = get_previous_multiple(ts, timedelta(hours=1), timedelta(minutes=50))
    assert result == datetime(2025, 6, 1, 11, 50, tzinfo=UTC)


def test_on_boundary_included():
    """A timestamp exactly on a release boundary returns itself when include=True."""
    ts = datetime(2025, 6, 1, 11, 50, tzinfo=UTC)
    result = get_previous_multiple(ts, timedelta(hours=1), timedelta(minutes=50))
    assert result == ts


def test_on_boundary_excluded():
    """include=False steps back one interval when exactly on a boundary."""
    ts = datetime(2025, 6, 1, 11, 50, tzinfo=UTC)
    result = get_previous_multiple(
        ts, timedelta(hours=1), timedelta(minutes=50), include=False
    )
    assert result == datetime(2025, 6, 1, 10, 50, tzinfo=UTC)


def test_five_minute_zero_offset():
    """RS-style 5-minute grid — 12:37:30 floors to 12:35."""
    ts = datetime(2025, 6, 1, 12, 37, 30, tzinfo=UTC)
    result = get_previous_multiple(ts, timedelta(minutes=5), timedelta())
    assert result == datetime(2025, 6, 1, 12, 35, tzinfo=UTC)


# ===========================================================================
# mydatetime operators
# ===========================================================================

def test_divmod_invariant():
    """divmod(dt, delta) → (quotient, remainder) with quotient + remainder == dt."""
    dt = mydatetime(2025, 6, 1, 12, 32, tzinfo=UTC)
    delta = timedelta(hours=1)
    quotient, remainder = divmod(dt, delta)
    assert timedelta() <= remainder < delta
    assert quotient + remainder == dt


def test_floordiv_and_mod_match_divmod():
    dt = mydatetime(2025, 6, 1, 12, 32, tzinfo=UTC)
    delta = timedelta(minutes=15)
    quotient, remainder = divmod(dt, delta)
    assert dt // delta == quotient
    assert dt % delta == remainder
