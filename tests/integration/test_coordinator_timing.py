"""Coordinator timing-logic tests.

Coordinators come from the make_coordinator factory (tests/integration/
conftest.py): the real constructor on the real hass, with the fetch jitter
pinned to 0 unless a test is about the jitter.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import aiohttp
import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.dwd_precipitation import (
    PRODUCT_CLASSES,
    coordinator as coordinator_mod,
)
from custom_components.dwd_precipitation.coordinator import CoordinatorData
from custom_components.dwd_precipitation.radar import OutsideGrid, UnsupportedGrid
from custom_components.dwd_precipitation.release_grid import ReleaseGrid
from custom_components.dwd_precipitation.products import (
    RadolanRW,
    RadolanSFLastYesterday,
    RadvorRS,
)

UTC = timezone.utc


async def test_overlapping_refreshes_fetch_once(make_coordinator, hass) -> None:
    """The release timer and a fast-poll retry can both start a refresh.

    Both go through async_refresh, whose lock makes the second wait and then
    find the release already fetched. Calling the unlocked _async_refresh
    instead would fetch twice.
    """
    coordinator = make_coordinator(RadolanRW)
    gate = asyncio.Event()
    fetches = 0

    async def fetch(ts):
        nonlocal fetches
        fetches += 1
        await gate.wait()
        return {"amount": 1.0}, {
            "amount": coordinator_mod.ProductMetadata(
                source_product="RW", source_timestamp=ts
            )
        }

    with patch.object(coordinator, "_fetch_and_parse", side_effect=fetch):
        first = hass.async_create_task(coordinator.async_refresh())
        second = hass.async_create_task(coordinator.async_refresh())
        await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(first, second)

    assert fetches == 1
    assert coordinator.data.data == {"amount": 1.0}
    coordinator._cancel_stale_check()

    # Every trigger of ours must take that lock.
    import inspect

    import custom_components.dwd_precipitation as integration

    for module in (coordinator_mod, integration):
        assert "._async_refresh(" not in inspect.getsource(module)


async def test_rs_track_time_change_args(make_coordinator):
    """RS: 5-min cadence, +4m10s availability → all hours, minutes {4,9,…,59}, sec 10."""
    coord = make_coordinator(RadvorRS)
    args = coord.track_time_change_args
    assert len(args) == 1
    entry = args[0]
    assert entry["second"] == 10
    assert entry["hour"] == list(range(24))
    assert entry["minute"] == [4, 9, 14, 19, 24, 29, 34, 39, 44, 49, 54, 59]


async def test_rw_track_time_change_args(make_coordinator):
    """RW: hourly at :00 + 28m delay → all hours at minute 28, second 0."""
    coord = make_coordinator(RadolanRW)
    args = coord.track_time_change_args
    assert len(args) == 1
    entry = args[0]
    assert entry["second"] == 0
    assert entry["minute"] == [28]
    assert entry["hour"] == list(range(24))


async def test_rw_get_latest_release(make_coordinator):
    """13:00 − 28m delay = 12:32 → previous :00 release is 12:00."""
    coord = make_coordinator(RadolanRW)
    now = datetime(2025, 6, 1, 13, 0, tzinfo=UTC)
    assert coord._get_latest_release(now) == datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    # 12:27 − 28m = 11:59 → still 11:00.
    now = datetime(2025, 6, 1, 12, 27, tzinfo=UTC)
    assert coord._get_latest_release(now) == datetime(2025, 6, 1, 11, 0, tzinfo=UTC)


async def test_release_at_or_before_maps_the_grid(make_coordinator):
    """A release maps to itself; anything off the grid to the release before it."""
    grid = make_coordinator(RadolanRW).grid
    release = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    assert grid.at_or_before(release) == release
    # A timestamp from RW's old HH:50 grid is off it.
    old = datetime(2025, 6, 1, 12, 50, tzinfo=UTC)
    assert grid.at_or_before(old) == release


async def test_stale_deadline_runs_from_the_overdue_release(make_coordinator):
    """The clock starts when the *next* release should have been published."""
    coord = make_coordinator(RadolanRW)

    coord.curr_release = None
    assert coord._stale_deadline() is None
    assert coord._data_is_stale(datetime(2025, 6, 1, 13, 0, tzinfo=UTC)) is True

    # cached 11:00; the 12:00 release is due at 12:28, and we give it 6 more min
    coord.curr_release = datetime(2025, 6, 1, 11, 0, tzinfo=UTC)
    assert coord._stale_deadline() == datetime(2025, 6, 1, 12, 34, tzinfo=UTC)
    assert coord._data_is_stale(datetime(2025, 6, 1, 12, 28, tzinfo=UTC)) is False
    assert coord._data_is_stale(datetime(2025, 6, 1, 12, 34, tzinfo=UTC)) is False
    assert coord._data_is_stale(datetime(2025, 6, 1, 12, 35, tzinfo=UTC)) is True


async def test_rs_rides_out_one_late_release(make_coordinator):
    """The reported scenario: a late 06:40 file must not blank the sensors."""
    coord = make_coordinator(RadvorRS)
    coord.curr_release = datetime(2026, 9, 17, 6, 35, tzinfo=UTC)

    # 06:40 is due at 06:44:10; RS keeps trying for it until 06:50:10.
    assert coord._stale_deadline() == datetime(2026, 9, 17, 6, 50, 10, tzinfo=UTC)

    for moment in ("06:44:10", "06:45:10", "06:46:20", "06:49:10"):
        now = datetime.strptime(f"2026-09-17 {moment}", "%Y-%m-%d %H:%M:%S")
        assert coord._data_is_stale(now.replace(tzinfo=UTC)) is False, moment

    assert coord._data_is_stale(datetime(2026, 9, 17, 6, 54, 10, tzinfo=UTC)) is True


@pytest.mark.parametrize("cls", PRODUCT_CLASSES)
async def test_stale_deadline_never_lands_on_a_fetch(make_coordinator, cls):
    """The deadline must not coincide with a scheduled fetch.

    If it does, the value is written off at the very instant of the attempt
    that might have restored it, and which happens first comes down to
    event-loop latency. That is only avoided while OVERDUE_GRACE is not a
    whole multiple of RELEASE_INTERVAL, so assert it directly and then check
    the consequence against the actual fetch grid.
    """
    assert cls.OVERDUE_GRACE % cls.RELEASE_INTERVAL != timedelta()

    release = datetime(2025, 6, 1, 0, 0, tzinfo=UTC)
    coord = make_coordinator(cls, curr_release=release)
    deadline = coord._stale_deadline()

    fetches = {
        release + n * cls.RELEASE_INTERVAL + cls.RELEASE_DELAY for n in range(-2, 50)
    }
    assert deadline not in fetches

    # Monotone: once past the deadline it never reads fresh again.
    assert coord._data_is_stale(deadline) is False
    for minutes in (1, 5, 60, 60 * 48):
        assert coord._data_is_stale(deadline + timedelta(minutes=minutes)) is True


async def test_stale_check_is_armed_on_success(make_coordinator):
    """A successful fetch arms a callback on the new deadline.

    Availability is derived from the clock, so something has to make the
    entities look again when nothing else is happening.
    """
    coord = make_coordinator(RadolanRW)
    coord.curr_release = datetime(2025, 6, 1, 11, 0, tzinfo=UTC)
    fired_at = []

    def _fake_track(_hass, _action, point_in_time):
        fired_at.append(point_in_time)
        return Mock(name="unsub")

    with patch.object(coordinator_mod, "async_track_point_in_time", _fake_track):
        coord._schedule_stale_check()

    assert fired_at == [datetime(2025, 6, 1, 12, 34, tzinfo=UTC)]

    unsub = coord._stale_unsub
    coord._cancel_stale_check()
    unsub.assert_called_once_with()
    assert coord._stale_unsub is None


# ----------------------------------------------------------------------
# Fast-poll retry backoff
# ----------------------------------------------------------------------


@contextmanager
def _capture_scheduled_delays():
    """Patch the timers, yielding the retry delays they were asked for.

    The deadline callback is stubbed out too, so a success inside the block
    leaves no timer behind.
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


async def test_fast_poll_ramps_by_ten_seconds_then_pins_at_cap(make_coordinator):
    """RW: 60, 70, 80, … capped at MAX_FAST_POLL_INTERVAL (5 min)."""
    coord = make_coordinator(RadolanRW)

    with _capture_scheduled_delays() as delays:
        for _ in range(30):
            coord._schedule_fast_poll()

    assert delays[:5] == [60, 70, 80, 90, 100]
    assert delays[24] == 300
    assert delays[25:] == [300] * 5


async def test_fast_poll_cap_is_per_product(make_coordinator):
    """The daily product backs off to 15 min instead of 5."""
    coord = make_coordinator(RadolanSFLastYesterday)

    with _capture_scheduled_delays() as delays:
        for _ in range(120):
            coord._schedule_fast_poll()

    assert max(delays) == 900
    assert delays[-1] == 900


@pytest.mark.asyncio
async def test_fast_poll_ramp_spans_release_boundaries(make_coordinator):
    """Only success resets the ramp — a newly-due release does not."""
    coord = make_coordinator(
        _TolerantRW,
        data=CoordinatorData({"amount": 3.2}, {}),
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


async def test_stop_fast_polling_cancels_and_resets(make_coordinator):
    """Stopping cancels the pending timer and clears the ramp state."""
    coord = make_coordinator(RadolanRW)

    with _capture_scheduled_delays():
        coord._schedule_fast_poll()
        coord._schedule_fast_poll()

    unsub = coord._fast_poll_unsub
    coord._stop_fast_polling()

    unsub.assert_called_once_with()
    assert coord._fast_poll_unsub is None
    assert coord._fast_poll_failures == 0


async def test_timers_are_registered_for_entry_unload(make_coordinator, make_entry):
    """Both timers are hooked to unload once, at construction."""
    entry = make_entry()
    with patch.object(entry, "async_on_unload") as on_unload:
        coord = make_coordinator(RadolanRW, entry=entry)

    assert [c.args[0] for c in on_unload.call_args_list] == [
        coord._stop_fast_polling,
        coord._cancel_stale_check,
    ]


@pytest.mark.asyncio
async def test_a_release_already_fetched_is_not_fetched_again(make_coordinator):
    """Nothing new is due: the cached payload comes back untouched, no fetch.

    A pending retry ends too: whatever it was for has been fetched since.
    """
    now = datetime(2025, 6, 1, 13, 0, tzinfo=UTC)  # 12:00 is the latest RW release
    cached = CoordinatorData({"amount": 3.2}, {})
    coord = make_coordinator(
        RadolanRW, data=cached, curr_release=datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    )
    coord._fetch_and_parse = AsyncMock(side_effect=AssertionError("fetched again"))

    with (
        patch.object(coordinator_mod.dt_util, "utcnow", return_value=now),
        _capture_scheduled_delays(),
    ):
        coord._schedule_fast_poll()
        unsub = coord._fast_poll_unsub
        assert await coord._async_update_data() is cached

    coord._fetch_and_parse.assert_not_awaited()
    unsub.assert_called_once_with()
    assert coord._fast_poll_failures == 0


@pytest.mark.asyncio
async def test_fast_poll_retry_fetches_when_it_fires(hass, make_coordinator, freezer):
    """End to end on real timers: a failure arms the retry, and it refreshes."""
    freezer.move_to("2025-06-01 13:00:00+00:00")
    coord = make_coordinator(RadolanRW)
    coord._fetch_and_parse = AsyncMock(
        side_effect=[OSError("not there yet"), ({"amount": 3.2}, {})]
    )

    with patch.object(coordinator_mod, "_apply_retry_jitter", lambda delay: delay):
        await coord.async_refresh()
    assert not coord.last_update_success
    assert coord._fast_poll_unsub is not None

    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert coord._fetch_and_parse.await_count == 2
    assert coord.last_update_success
    assert coord.data.data == {"amount": 3.2}
    assert coord.curr_release == datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    assert coord._fast_poll_unsub is None
    coord._cancel_stale_check()


@pytest.mark.asyncio
async def test_successful_update_stops_fast_polling(make_coordinator):
    """A successful fetch cancels the retry timer and resets the ramp."""
    now = datetime(2025, 6, 1, 13, 0, tzinfo=UTC)
    coord = make_coordinator(RadolanRW)
    coord._fetch_and_parse = AsyncMock(side_effect=OSError("boom"))

    with (
        patch.object(coordinator_mod.dt_util, "utcnow", return_value=now),
        _capture_scheduled_delays() as delays,
    ):
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

        assert delays == [60]
        unsub = coord._fast_poll_unsub

        coord._fetch_and_parse = AsyncMock(return_value=({"amount": 3.2}, {}))
        result = await coord._async_update_data()

    assert result.data == {"amount": 3.2}
    assert coord.curr_release == datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    unsub.assert_called_once_with()
    assert coord._fast_poll_unsub is None
    assert coord._fast_poll_failures == 0


@pytest.mark.asyncio
async def test_fast_poll_survives_the_transition_to_stale(make_coordinator):
    """Fast-poll keeps running across the fresh → stale → UpdateFailed boundary."""
    coord = make_coordinator(
        _TolerantRW,
        data=CoordinatorData({"amount": 3.2}, {}),
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
async def test_first_ever_failure_starts_fast_polling(make_coordinator):
    """With no cached data at all, the retry timer is armed before UpdateFailed."""
    now = datetime(2025, 6, 1, 13, 0, tzinfo=UTC)
    coord = make_coordinator(RadolanRW)
    coord._fetch_and_parse = AsyncMock(side_effect=OSError("boom"))

    with (
        patch.object(coordinator_mod.dt_util, "utcnow", return_value=now),
        _capture_scheduled_delays() as delays,
    ):
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    assert delays == [60]
    assert coord._fast_poll_unsub is not None


@pytest.mark.asyncio
async def test_a_file_that_cannot_be_read_leaves_its_traceback_once(make_coordinator, caplog):
    """Debug traceback on the first failure of a run; none for a late file."""
    now = datetime(2025, 6, 1, 13, 0, tzinfo=UTC)
    coord = make_coordinator(RadolanRW)
    caplog.set_level("DEBUG", logger=coordinator_mod.__name__)

    with (
        patch.object(coordinator_mod.dt_util, "utcnow", return_value=now),
        _capture_scheduled_delays(),
    ):
        coord._fetch_and_parse = AsyncMock(side_effect=ValueError("bad grid"))
        for _ in range(3):
            with pytest.raises(UpdateFailed):
                await coord._async_update_data()
        traces = [r for r in caplog.records if r.exc_info]
        assert len(traces) == 1
        assert "ValueError: bad grid" in caplog.text

        coord._stop_fast_polling()  # a new run of failures
        caplog.clear()
        coord._fetch_and_parse = AsyncMock(side_effect=_response_error(404, "Not Found"))
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        assert not [r for r in caplog.records if r.exc_info]



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
        (ValueError("Unexpected RADOLAN grid shape"), "please report it"),
        (UnsupportedGrid("PROJ parameters ['k_0']"), "please report it"),
        (OutsideGrid("(60.0, 25.0) is outside the 1200 x 1100 grid"), "location inside Germany"),
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


async def test_daily_deadline_follows_the_local_release_grid(make_coordinator):
    """sf_2350's releases are 23 or 25 h apart across a DST changeover.

    Adding RELEASE_INTERVAL to the UTC timestamp would put the deadline an hour
    out on those two days — in autumn, before the file it waits for can exist.
    """
    berlin = ZoneInfo("Europe/Berlin")
    coord = make_coordinator(RadolanSFLastYesterday)
    # Last success: the 23:50 release on the day the clocks go back.
    coord.curr_release = datetime(2025, 10, 25, 23, 50, tzinfo=berlin).astimezone(UTC)

    with patch.object(
        coordinator_mod.dt_util, "get_default_time_zone", lambda: berlin
    ):
        deadline = coord._stale_deadline()

    next_release = datetime(2025, 10, 26, 23, 50, tzinfo=berlin).astimezone(UTC)
    # RELEASE_DELAY (31 min, the HDF5 edition) + OVERDUE_GRACE (30 min).
    assert deadline == next_release + timedelta(minutes=31) + timedelta(minutes=30)
    # 25 h later in absolute terms, not 24.
    assert next_release - coord.curr_release == timedelta(hours=25)


def test_local_grid_steps_over_both_changeovers():
    """A 23:50-local grid: 23 h across spring, 25 h across autumn, both ways."""
    berlin = ZoneInfo("Europe/Berlin")
    grid = ReleaseGrid(timedelta(hours=24), timedelta(hours=23, minutes=50), berlin)

    def local(day: str) -> datetime:
        y, m, d = (int(x) for x in day.split("-"))
        return datetime(y, m, d, 23, 50, tzinfo=berlin).astimezone(UTC)

    for before, after, hours in (
        ("2026-03-28", "2026-03-29", 23),
        ("2026-10-24", "2026-10-25", 25),
    ):
        assert grid.next_after(local(before)) == local(after)
        assert local(after) - local(before) == timedelta(hours=hours)
        assert grid.previous(local(after)) == local(before)
        assert grid.at_or_before(local(after) + timedelta(hours=3)) == local(after)
    assert grid.back(local("2026-10-26"), 3) == local("2026-10-23")


def test_a_wall_time_that_occurs_twice_means_its_first_occurrence():
    """As before ReleaseGrid: the autumn hour 02:00-03:00 floors onto its first pass."""
    berlin = ZoneInfo("Europe/Berlin")
    grid = ReleaseGrid(timedelta(hours=24), timedelta(hours=2, minutes=30), berlin)
    second_pass = datetime(2026, 10, 25, 1, 55, tzinfo=UTC)  # 02:55 CET
    assert grid.at_or_before(second_pass) == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)


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
async def test_fetch_jitter_shifts_the_schedule_and_the_deadline_together(make_coordinator, cls):
    """Jitter lives in the delay, so it must not eat into the deadline margin.

    Everything that decides when a release is ours to fetch derives from
    release_delay, so adding the offset there moves the fetch grid and the
    staleness deadline by the same amount. Delaying the fetch on its own
    instead would close the gap between them.
    """
    release = datetime(2025, 6, 1, 0, 0, tzinfo=UTC)
    margins = set()

    for seconds in (0, 7, 15, 23, 30):
        coord = make_coordinator(
            cls, jitter=timedelta(seconds=seconds), curr_release=release
        )

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


async def test_fetch_jitter_keeps_the_schedule_on_whole_seconds(make_coordinator):
    """track_time_change_args is built from whole seconds; jitter must be too."""
    for seconds in (0, 17, 30):
        coord = make_coordinator(RadvorRS, jitter=timedelta(seconds=seconds))
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
