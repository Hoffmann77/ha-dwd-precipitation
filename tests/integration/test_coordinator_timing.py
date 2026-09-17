"""Coordinator timing-logic tests — needs HA installed to import.

Instances are built via __new__ to exercise the pure timing helpers without
standing up a full HomeAssistant / DataUpdateCoordinator.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from custom_components.dwd_precipitation import coordinator as coordinator_mod
from custom_components.dwd_precipitation.coordinator import CoordinatorData
from custom_components.dwd_precipitation.products import (
    HymecNG,
    RadolanRW,
    RadolanSF,
    RadolanSFLastYesterday,
    RadvorRS,
    RadvorRV,
)

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


def test_stale_deadline_runs_from_the_overdue_release():
    """The clock starts when the *next* release should have been published."""
    coord = RadolanRW.__new__(RadolanRW)

    coord.curr_release = None
    assert coord._stale_deadline() is None
    assert coord._data_is_stale(datetime(2025, 6, 1, 13, 0, tzinfo=UTC)) is True

    # cached 11:50; the 12:50 release is due at 13:18, and we give it 6 more min
    coord.curr_release = datetime(2025, 6, 1, 11, 50, tzinfo=UTC)
    assert coord._stale_deadline() == datetime(2025, 6, 1, 13, 24, tzinfo=UTC)
    assert coord._data_is_stale(datetime(2025, 6, 1, 13, 18, tzinfo=UTC)) is False
    assert coord._data_is_stale(datetime(2025, 6, 1, 13, 24, tzinfo=UTC)) is False
    assert coord._data_is_stale(datetime(2025, 6, 1, 13, 25, tzinfo=UTC)) is True


def test_rs_rides_out_one_late_release():
    """The reported scenario: a late 06:40 file must not blank the sensors."""
    coord = RadvorRS.__new__(RadvorRS)
    coord.curr_release = datetime(2026, 9, 17, 6, 35, tzinfo=UTC)

    # 06:40 is due at 06:44:10; RS keeps trying for it until 06:50:10.
    assert coord._stale_deadline() == datetime(2026, 9, 17, 6, 50, 10, tzinfo=UTC)

    for moment in ("06:44:10", "06:45:10", "06:46:20", "06:49:10"):
        now = datetime.strptime(f"2026-09-17 {moment}", "%Y-%m-%d %H:%M:%S")
        assert coord._data_is_stale(now.replace(tzinfo=UTC)) is False, moment

    assert coord._data_is_stale(datetime(2026, 9, 17, 6, 54, 10, tzinfo=UTC)) is True


@pytest.mark.parametrize(
    "cls", [RadvorRS, RadvorRV, HymecNG, RadolanRW, RadolanSF, RadolanSFLastYesterday]
)
def test_stale_deadline_never_lands_on_a_fetch(cls):
    """The deadline must not coincide with a scheduled fetch.

    If it does, the value is written off at the very instant of the attempt
    that might have restored it, and which happens first comes down to
    event-loop latency. That is only avoided while OVERDUE_GRACE is not a
    whole multiple of RELEASE_INTERVAL, so assert it directly and then check
    the consequence against the actual fetch grid.
    """
    assert cls.OVERDUE_GRACE % cls.RELEASE_INTERVAL != timedelta()

    coord = cls.__new__(cls)
    release = datetime(2025, 6, 1, 0, 0, tzinfo=UTC)
    coord.curr_release = release
    deadline = coord._stale_deadline()

    fetches = {
        release + n * cls.RELEASE_INTERVAL + cls.RELEASE_DELAY for n in range(-2, 50)
    }
    assert deadline not in fetches

    # Monotone: once past the deadline it never reads fresh again.
    assert coord._data_is_stale(deadline) is False
    for minutes in (1, 5, 60, 60 * 48):
        assert coord._data_is_stale(deadline + timedelta(minutes=minutes)) is True


def test_stale_check_is_armed_on_success():
    """A successful fetch arms a callback on the new deadline.

    Availability is derived from the clock, so something has to make the
    entities look again when nothing else is happening.
    """
    coord = _make_coordinator(RadolanRW)
    coord.curr_release = datetime(2025, 6, 1, 11, 50, tzinfo=UTC)
    fired_at = []

    def _fake_track(_hass, _action, point_in_time):
        fired_at.append(point_in_time)
        return Mock(name="unsub")

    with patch.object(coordinator_mod, "async_track_point_in_time", _fake_track):
        coord._schedule_stale_check()

    assert fired_at == [datetime(2025, 6, 1, 13, 24, tzinfo=UTC)]

    unsub = coord._stale_unsub
    coord._cancel_stale_check()
    unsub.assert_called_once_with()
    assert coord._stale_unsub is None


# ----------------------------------------------------------------------
# Fast-poll retry backoff
# ----------------------------------------------------------------------


def _make_coordinator(cls, *, data=None, curr_release=None):
    """Build a bare coordinator with just the fast-poll/update state populated."""
    coord = cls.__new__(cls)
    coord.hass = object()
    coord.config_entry = SimpleNamespace(options={})
    coord.async_client = None
    coord.coords = (51.05, 13.73)
    coord.curr_release = curr_release
    coord.data = data
    coord._fast_poll_unsub = None
    coord._fast_poll_failures = 0
    coord._stale_unsub = None

    return coord


@contextmanager
def _capture_scheduled_delays():
    """Patch the timers, yielding the retry delays they were asked for.

    The deadline callback is stubbed out too, so a success inside the block does
    not try to arm a real timer on the fake hass.
    """
    delays: list[float] = []

    def _fake_call_later(_hass, delay, _action):
        delays.append(delay.total_seconds())
        return Mock(name="unsub")

    with (
        patch.object(coordinator_mod, "async_call_later", _fake_call_later),
        patch.object(
            coordinator_mod,
            "async_track_point_in_time",
            Mock(return_value=Mock(name="unsub")),
        ),
    ):
        yield delays


class _TolerantRW(RadolanRW):
    """RW that keeps trying for much longer, so cached data outlives a release."""

    OVERDUE_GRACE = timedelta(hours=1, minutes=30)


def test_fast_poll_ramps_by_ten_seconds_then_pins_at_cap():
    """RW: 60, 70, 80, … capped at MAX_FAST_POLL_INTERVAL (5 min)."""
    coord = _make_coordinator(RadolanRW)

    with _capture_scheduled_delays() as delays:
        for _ in range(30):
            coord._schedule_fast_poll()

    assert delays[:5] == [60, 70, 80, 90, 100]
    assert delays[24] == 300
    assert delays[25:] == [300] * 5


def test_fast_poll_cap_is_per_product():
    """The daily product backs off to 15 min instead of 5."""
    coord = _make_coordinator(RadolanSFLastYesterday)

    with _capture_scheduled_delays() as delays:
        for _ in range(120):
            coord._schedule_fast_poll()

    assert max(delays) == 900
    assert delays[-1] == 900


@pytest.mark.asyncio
async def test_fast_poll_ramp_spans_release_boundaries():
    """Only success resets the ramp — a newly-due release does not."""
    coord = _make_coordinator(
        _TolerantRW,
        data=CoordinatorData(3.2, {}),
        curr_release=datetime(2025, 6, 1, 11, 50, tzinfo=UTC),
    )
    coord._fetch_and_parse = AsyncMock(side_effect=OSError("boom"))

    # 12:50 release due at the first two times, 13:50 at the third.
    with _capture_scheduled_delays() as delays:
        for now in (
            datetime(2025, 6, 1, 13, 20, tzinfo=UTC),
            datetime(2025, 6, 1, 13, 22, tzinfo=UTC),
            datetime(2025, 6, 1, 14, 20, tzinfo=UTC),
        ):
            with patch.object(coordinator_mod.dt_util, "utcnow", return_value=now):
                assert await coord._async_update_data() is coord.data

    assert delays == [60, 70, 80]


def test_stop_fast_polling_cancels_and_resets():
    """Stopping cancels the pending timer and clears the ramp state."""
    coord = _make_coordinator(RadolanRW)

    with _capture_scheduled_delays():
        coord._schedule_fast_poll()
        coord._schedule_fast_poll()

    unsub = coord._fast_poll_unsub
    coord._stop_fast_polling()

    unsub.assert_called_once_with()
    assert coord._fast_poll_unsub is None
    assert coord._fast_poll_failures == 0


def test_timers_are_registered_for_entry_unload():
    """Both timers are hooked to unload once, at construction."""
    entry = SimpleNamespace(
        data={"name": "Home"},
        options={},
        unload_callbacks=[],
    )
    entry.async_on_unload = entry.unload_callbacks.append

    with patch.object(DataUpdateCoordinator, "__init__", return_value=None):
        coord = RadolanRW(object(), entry, None, 51.05, 13.73)

    assert entry.unload_callbacks == [
        coord._stop_fast_polling,
        coord._cancel_stale_check,
    ]


@pytest.mark.asyncio
async def test_successful_update_stops_fast_polling():
    """A successful fetch cancels the retry timer and resets the ramp."""
    now = datetime(2025, 6, 1, 13, 0, tzinfo=UTC)
    coord = _make_coordinator(RadolanRW)
    coord._fetch_and_parse = AsyncMock(side_effect=OSError("boom"))

    with (
        patch.object(coordinator_mod.dt_util, "utcnow", return_value=now),
        _capture_scheduled_delays() as delays,
    ):
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

        assert delays == [60]
        unsub = coord._fast_poll_unsub

        coord._fetch_and_parse = AsyncMock(return_value=(3.2, {}))
        result = await coord._async_update_data()

    assert result.data == 3.2
    assert coord.curr_release == datetime(2025, 6, 1, 11, 50, tzinfo=UTC)
    unsub.assert_called_once_with()
    assert coord._fast_poll_unsub is None
    assert coord._fast_poll_failures == 0


@pytest.mark.asyncio
async def test_fast_poll_survives_the_transition_to_stale():
    """Fast-poll keeps running across the fresh → stale → UpdateFailed boundary."""
    coord = _make_coordinator(
        _TolerantRW,
        data=CoordinatorData(3.2, {}),
        curr_release=datetime(2025, 6, 1, 11, 50, tzinfo=UTC),
    )
    coord._fetch_and_parse = AsyncMock(side_effect=OSError("boom"))

    # Stale threshold is 11:50 + 28m delay + 3h tolerance = 15:18.
    fresh = [
        datetime(2025, 6, 1, 13, 20, tzinfo=UTC),  # 12:50 release due, still fresh
        datetime(2025, 6, 1, 13, 22, tzinfo=UTC),
    ]
    stale = datetime(2025, 6, 1, 15, 20, tzinfo=UTC)  # 14:50 release due, now stale

    with _capture_scheduled_delays() as delays:
        for now in fresh:
            with patch.object(coordinator_mod.dt_util, "utcnow", return_value=now):
                assert await coord._async_update_data() is coord.data

        with patch.object(coordinator_mod.dt_util, "utcnow", return_value=stale):
            with pytest.raises(UpdateFailed):
                await coord._async_update_data()

    # The ramp keeps climbing across the 14:50 release boundary, and the timer
    # stays armed even though HA is now being told the entity is unavailable.
    assert delays == [60, 70, 80]
    assert coord._fast_poll_unsub is not None


@pytest.mark.asyncio
async def test_first_ever_failure_starts_fast_polling():
    """With no cached data at all, the retry timer is armed before UpdateFailed."""
    now = datetime(2025, 6, 1, 13, 0, tzinfo=UTC)
    coord = _make_coordinator(RadolanRW)
    coord._fetch_and_parse = AsyncMock(side_effect=OSError("boom"))

    with (
        patch.object(coordinator_mod.dt_util, "utcnow", return_value=now),
        _capture_scheduled_delays() as delays,
    ):
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    assert delays == [60]
    assert coord._fast_poll_unsub is not None



def test_daily_deadline_follows_the_local_release_grid():
    """sf_2350's releases are 23 or 25 h apart across a DST changeover.

    Adding RELEASE_INTERVAL to the UTC timestamp would put the deadline an hour
    out on those two days — in autumn, before the file it waits for can exist.
    """
    berlin = ZoneInfo("Europe/Berlin")
    coord = RadolanSFLastYesterday.__new__(RadolanSFLastYesterday)
    # Last success: the 23:50 release on the day the clocks go back.
    coord.curr_release = datetime(2025, 10, 25, 23, 50, tzinfo=berlin).astimezone(UTC)

    with patch.object(
        coordinator_mod.dt_util, "as_local", lambda d: d.astimezone(berlin)
    ):
        deadline = coord._stale_deadline()

    next_release = datetime(2025, 10, 26, 23, 50, tzinfo=berlin).astimezone(UTC)
    assert deadline == next_release + timedelta(minutes=28) + timedelta(minutes=30)
    # 25 h later in absolute terms, not 24.
    assert next_release - coord.curr_release == timedelta(hours=25)


def test_every_product_states_its_own_grace():
    """Each product declares OVERDUE_GRACE rather than inheriting it.

    How long a product is willing to wait for a late file is a judgement about
    that product, so it belongs next to its other timing constants where it can
    be read and argued with.
    """
    for cls in (RadvorRS, RadvorRV, HymecNG, RadolanRW, RadolanSF, RadolanSFLastYesterday):
        assert "OVERDUE_GRACE" in vars(cls), f"{cls.__name__} inherits its grace"
