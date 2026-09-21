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

import aiohttp
import pytest
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from custom_components.dwd_precipitation import (
    PRODUCT_CLASSES,
    coordinator as coordinator_mod,
)
from custom_components.dwd_precipitation.coordinator import CoordinatorData
from custom_components.dwd_precipitation.products import (
    RadolanRW,
    RadolanSFLastYesterday,
    RadvorRS,
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


@pytest.mark.parametrize("cls", PRODUCT_CLASSES)
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
        # Retry jitter is asserted on its own below; switching it off here keeps
        # the ramp assertions exact.
        patch.object(coordinator_mod, "_apply_retry_jitter", lambda delay: delay),
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
        entry_id="01JABCDEF0123456789XYZ",
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



# ----------------------------------------------------------------------
# Fetch-error messages
# ----------------------------------------------------------------------


def _response_error(status: int, message: str) -> aiohttp.ClientResponseError:
    """Build a ClientResponseError without needing a real request context."""
    err = aiohttp.ClientResponseError.__new__(aiohttp.ClientResponseError)
    err.status = status
    err.message = message

    return err


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=45), "45 s"),
        (timedelta(seconds=60), "1 min"),
        (timedelta(minutes=5), "5 min"),
        (timedelta(minutes=70), "1 h 10 min"),
        (timedelta(hours=2), "2 h"),
        (timedelta(seconds=-5), "0 s"),
    ],
)
def test_format_duration(delta, expected):
    assert coordinator_mod._format_duration(delta) == expected


def test_not_found_message_does_not_blame_the_user():
    """The common case is DWD being late; the message must say so."""
    message = coordinator_mod._describe_fetch_error(
        _response_error(404, "Not Found"),
        datetime(2026, 9, 17, 6, 40, tzinfo=UTC),
        timedelta(seconds=60),
    )

    assert "HTTP 404" in message
    assert "2026-09-17 06:40 UTC" in message
    assert "nothing is wrong with your setup" in message
    assert message.endswith("Retrying in 1 min.")


@pytest.mark.parametrize(
    ("err", "expected"),
    [
        (_response_error(503, "Service Unavailable"), "HTTP 503"),
        (aiohttp.ClientConnectionError("DNS failure"), "internet access"),
        (ValueError("Unexpected RADOLAN grid shape"), "Could not read"),
    ],
)
def test_every_message_states_the_retry(err, expected):
    """Whatever went wrong, the reader is told retries continue on their own."""
    message = coordinator_mod._describe_fetch_error(
        err, datetime(2026, 9, 17, 6, 40, tzinfo=UTC), timedelta(minutes=5)
    )

    assert expected in message
    assert message.endswith("Retrying in 5 min.")
    # Log viewers mangle typographic punctuation.
    assert message.isascii()


def test_every_product_has_a_readable_log_label():
    """HA logs "Error fetching <entry> <label> data", so <label> must read well."""
    for cls in PRODUCT_CLASSES:
        label = cls.PRODUCT_LABEL
        assert label, f"{cls.__name__} has no PRODUCT_LABEL"
        assert label.isascii()
        assert not label.endswith("data")  # HA appends " data" itself

    labels = [cls.PRODUCT_LABEL for cls in PRODUCT_CLASSES]
    assert len(set(labels)) == len(labels), "labels must identify the product"


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
    for cls in PRODUCT_CLASSES:
        assert "OVERDUE_GRACE" in vars(cls), f"{cls.__name__} inherits its grace"


# ----------------------------------------------------------------------
# Jitter
# ----------------------------------------------------------------------


@pytest.mark.parametrize("cls", PRODUCT_CLASSES)
def test_fetch_jitter_shifts_the_schedule_and_the_deadline_together(cls):
    """Jitter lives in the delay, so it must not eat into the deadline margin.

    Everything that decides when a release is ours to fetch derives from
    release_delay, so adding the offset there moves the fetch grid and the
    staleness deadline by the same amount. Delaying the fetch on its own
    instead would close the gap between them.
    """
    release = datetime(2025, 6, 1, 0, 0, tzinfo=UTC)
    margins = set()

    for seconds in (0, 7, 15, 23, 30):
        coord = cls.__new__(cls)
        coord._fetch_jitter = timedelta(seconds=seconds)
        coord.curr_release = release

        assert coord.release_delay == cls.RELEASE_DELAY + timedelta(seconds=seconds)

        deadline = coord._stale_deadline()
        fetches = [
            release + n * cls.RELEASE_INTERVAL + coord.release_delay for n in range(60)
        ]
        margins.add(deadline - max(f for f in fetches if f < deadline))

    assert len(margins) == 1, f"jitter changed the margin: {margins}"


def test_fetch_jitter_is_stable_for_an_entry():
    """The same entry must get the same offset after a restart or a reload.

    Derived from the entry id, not drawn at random, so a user's fetch times are
    the ones they saw last week and an unrelated options change does not move
    them. hashlib rather than hash(), whose str salt changes per process.
    """
    entry_id = "01JABCDEF0123456789XYZ"

    first = coordinator_mod.fetch_jitter_for(entry_id, "rs")
    assert coordinator_mod.fetch_jitter_for(entry_id, "rs") == first
    # Pinned: a change here silently reschedules every existing install.
    assert first == timedelta(seconds=6)

    # Different products of one entry do not all sit on the same second.
    per_product = {
        coordinator_mod.fetch_jitter_for(entry_id, key)
        for key in ("rs", "rv", "hymecng", "rw", "sf", "sf_2350")
    }
    assert len(per_product) > 1

    # Different entries land differently.
    assert coordinator_mod.fetch_jitter_for("a-different-entry", "rs") != first


def test_fetch_jitter_covers_the_whole_range():
    """Offsets must spread across the population, not cluster."""
    seen = {
        coordinator_mod.fetch_jitter_for(f"entry-{n}", "rs").total_seconds()
        for n in range(3000)
    }

    assert seen == set(range(31))


def test_fetch_jitter_stays_well_inside_one_release():
    """A whole-second offset that could skip a release would be a bug."""
    assert coordinator_mod.MAX_FETCH_JITTER == timedelta(seconds=30)
    assert coordinator_mod.MAX_FETCH_JITTER.total_seconds() % 1 == 0

    for cls in PRODUCT_CLASSES:
        assert coordinator_mod.MAX_FETCH_JITTER < cls.RELEASE_INTERVAL


def test_fetch_jitter_keeps_the_schedule_on_whole_seconds():
    """track_time_change_args is built from whole seconds; jitter must be too."""
    for seconds in (0, 17, 30):
        coord = RadvorRS.__new__(RadvorRS)
        coord._fetch_jitter = timedelta(seconds=seconds)
        args = coord.track_time_change_args

        assert len(args) == 1
        assert args[0]["second"] == 10 + seconds


def test_retry_jitter_stays_within_bounds():
    """Each retry is spread, but never far enough to distort the ramp."""
    delays = [
        coordinator_mod._apply_retry_jitter(timedelta(seconds=n)).total_seconds()
        for n in (60, 70, 300, 900)
        for _ in range(50)
    ]

    for nominal, got in zip(
        [n for n in (60, 70, 300, 900) for _ in range(50)], delays
    ):
        assert (
            nominal * (1 - coordinator_mod.RETRY_JITTER)
            <= got
            <= nominal * (1 + coordinator_mod.RETRY_JITTER)
        )

    # It really varies — a constant would defeat the point.
    assert len(set(delays)) > 1
