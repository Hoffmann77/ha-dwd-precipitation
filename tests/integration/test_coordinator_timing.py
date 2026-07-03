"""Coordinator timing-logic tests — needs HA installed to import.

Instances are built via __new__ to exercise the pure timing helpers without
standing up a full HomeAssistant / DataUpdateCoordinator.
"""

from __future__ import annotations

from datetime import datetime, timezone

from custom_components.dwd_precipitation.products import RadolanRW, RadvorRS

UTC = timezone.utc


def test_rs_track_time_change_args():
    """RS: 5-min cadence, +4m10s availability → all hours, minutes {4,9,…,59}, sec 10."""
    coord = RadvorRS.__new__(RadvorRS)
    args = coord.track_time_change_args
    assert len(args) == 1
    entry = args[0]
    assert entry["second"] == 10
    assert entry["hour"] == list(range(24))
    assert entry["minute"] == [4, 9, 14, 19, 24, 29, 34, 39, 44, 49, 54, 59]


def test_rw_track_time_change_args():
    """RW: hourly at :50 + 28m delay → all hours at minute 18, second 0."""
    coord = RadolanRW.__new__(RadolanRW)
    args = coord.track_time_change_args
    assert len(args) == 1
    entry = args[0]
    assert entry["second"] == 0
    assert entry["minute"] == [18]
    assert entry["hour"] == list(range(24))


def test_rw_get_latest_release():
    """13:00 − 28m delay = 12:32 → previous :50 release is 11:50."""
    coord = RadolanRW.__new__(RadolanRW)
    now = datetime(2025, 6, 1, 13, 0, tzinfo=UTC)
    assert coord._get_latest_release(now) == datetime(2025, 6, 1, 11, 50, tzinfo=UTC)


def test_data_is_stale_transitions():
    coord = RadolanRW.__new__(RadolanRW)

    coord.curr_release = None
    assert coord._data_is_stale(datetime(2025, 6, 1, 13, 0, tzinfo=UTC)) is True

    # threshold = release 11:50 + 28m delay + 1h interval tolerance = 13:18
    coord.curr_release = datetime(2025, 6, 1, 11, 50, tzinfo=UTC)
    assert coord._data_is_stale(datetime(2025, 6, 1, 13, 0, tzinfo=UTC)) is False
    assert coord._data_is_stale(datetime(2025, 6, 1, 13, 20, tzinfo=UTC)) is True
