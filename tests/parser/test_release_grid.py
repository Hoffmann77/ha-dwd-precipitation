"""Unit tests for release_grid.py on UTC grids — no HA, no network.

The local-time (DST) cases need a time-zone database, so they live in the
integration tier (tests/integration/test_coordinator_timing.py).
"""

from datetime import UTC, datetime, timedelta, timezone

from release_grid import ReleaseGrid

HOURLY_AT_50 = ReleaseGrid(timedelta(hours=1), timedelta(minutes=50))
FIVE_MIN = ReleaseGrid(timedelta(minutes=5))


def at(hour: int, minute: int, second: int = 0, micro: int = 0) -> datetime:
    return datetime(2025, 6, 1, hour, minute, second, micro, tzinfo=UTC)


def test_at_or_before_floors_onto_the_grid():
    assert HOURLY_AT_50.at_or_before(at(12, 32)) == at(11, 50)
    assert FIVE_MIN.at_or_before(at(12, 37, 30)) == at(12, 35)
    assert FIVE_MIN.at_or_before(at(12, 39, 59, 999_999)) == at(12, 35)


def test_a_release_maps_to_itself():
    assert HOURLY_AT_50.at_or_before(at(11, 50)) == at(11, 50)


def test_an_off_grid_release_does_not():
    # RW's old HH:50 run on today's HH:00 grid.
    assert ReleaseGrid(timedelta(hours=1)).at_or_before(at(9, 50)) == at(9, 0)


def test_next_and_previous_step_one_release():
    assert HOURLY_AT_50.next_after(at(11, 50)) == at(12, 50)
    assert HOURLY_AT_50.previous(at(11, 50)) == at(10, 50)


def test_back_and_walk():
    assert FIVE_MIN.back(at(12, 0), 3) == at(11, 45)
    assert FIVE_MIN.back(at(12, 0), 0) == at(12, 0)
    assert FIVE_MIN.walk(at(11, 45), at(12, 0)) == [at(11, 45), at(11, 50), at(11, 55)]
    assert FIVE_MIN.walk(at(12, 0), at(12, 0)) == []


def test_results_are_utc_whatever_comes_in():
    cest = datetime(2025, 6, 1, 14, 32, tzinfo=timezone(timedelta(hours=2)))
    result = HOURLY_AT_50.at_or_before(cest)
    assert result == at(11, 50)
    assert result.tzinfo is UTC
