"""Cumulative "Precipitation total" sensors -- needs HA installed.

The entity logic is exercised against stub coordinators, as in test_sensor.py;
the last test runs a real entry setup to cover restore and backfill end to end.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest import approx
from pytest_homeassistant_custom_component.common import (
    mock_restore_cache_with_extra_data,
)

from custom_components.dwd_precipitation.const import DOMAIN
from custom_components.dwd_precipitation.coordinator import CoordinatorData
from custom_components.dwd_precipitation.precipitation_total import (
    PrecipitationTotalExtraData,
    counted_on_grid,
    countable,
    missed_releases,
    split_fetchable,
)
from custom_components.dwd_precipitation.products import (
    RadolanRW,
    RadolanSFLastYesterday,
)
from custom_components.dwd_precipitation.release_grid import ReleaseGrid
from custom_components.dwd_precipitation.sensor import (
    TOTAL_SENSORS,
    PrecipitationTotalSensor,
)

from .test_setup_entry import WORKING_PRODUCTS, _patched_products

UTC = timezone.utc
BERLIN = ZoneInfo("Europe/Berlin")

RW_DESC, SF_DESC = TOTAL_SENSORS


RW_GRID = ReleaseGrid(RadolanRW.RELEASE_INTERVAL, RadolanRW.RELEASE_OFFSET)
SF_2350_GRID = ReleaseGrid(
    RadolanSFLastYesterday.RELEASE_INTERVAL,
    RadolanSFLastYesterday.RELEASE_OFFSET,
    BERLIN,
)


@pytest.fixture
def make_total_sensor(make_coordinator):
    """Return a factory: the RW total sensor on an RW coordinator.

    ``release``/``value`` are the coordinator's current release and reading;
    ``total``/``last_release``/``pending`` a restored state, given to the
    sensor the way a restart does. The factory returns the sensor and the
    background tasks it starts, as coroutines a test awaits or closes.
    """

    def _make(*, release=None, value=None, total=None, last_release=None, pending=()):
        coordinator = make_coordinator(
            RadolanRW,
            curr_release=release,
            data=None if release is None else CoordinatorData({"amount": value}, {}),
        )
        coordinator.async_fetch_release = AsyncMock(
            return_value=CoordinatorData({"amount": 1.0}, {})
        )
        tasks: list = []
        coordinator.config_entry.async_create_background_task = (
            lambda _hass, coro, _name: tasks.append(coro)
        )
        sensor = PrecipitationTotalSensor(coordinator, RW_DESC)
        # Not added to hass: an id for the log lines, and no state to write.
        sensor.entity_id = "sensor.home_precipitation_total"
        sensor.async_write_ha_state = lambda: None
        if total is not None:
            sensor._restore(
                PrecipitationTotalExtraData(total, last_release, list(pending))
            )
        return sensor, tasks

    return _make


def _close(tasks: list) -> None:
    """Close coroutines a test inspected but did not run."""
    for coro in tasks:
        coro.close()


# --- pure helpers ----------------------------------------------------------


def test_countable_drops_unusable_readings():
    assert countable(1.5) == 1.5
    assert countable(0) == 0.0
    for value in (None, float("nan"), -0.1):
        assert countable(value) is None


def test_extra_data_roundtrip():
    stored = PrecipitationTotalExtraData(
        total=12.3, last_release=datetime(2026, 7, 3, 11, 0, tzinfo=UTC)
    )
    restored = PrecipitationTotalExtraData.from_dict(stored.as_dict())
    assert restored == stored

    empty = PrecipitationTotalExtraData.from_dict({})
    assert empty.total is None
    assert empty.last_release is None
    assert empty.pending == []

    pending = PrecipitationTotalExtraData(
        total=1.0,
        last_release=datetime(2026, 7, 3, 11, 0, tzinfo=UTC),
        pending=[datetime(2026, 7, 3, h, 0, tzinfo=UTC) for h in (8, 9)],
    )
    assert PrecipitationTotalExtraData.from_dict(pending.as_dict()) == pending


def test_split_fetchable_gives_up_beyond_the_backfill_window():
    """The 48 releases before the current one are kept, anything older dropped."""
    current = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    oldest_kept = current - timedelta(hours=48)
    too_old = current - timedelta(hours=49)
    recent = current - timedelta(hours=1)

    keep, drop = split_fetchable(
        RW_GRID, [recent, too_old, oldest_kept, recent], current, 48
    )
    assert keep == [oldest_kept, recent]
    assert drop == [too_old]


def test_split_fetchable_counts_local_days_across_dst():
    """sf_2350's window is one release even when that day has 25 hours."""
    current = dt_util.as_utc(datetime(2026, 10, 25, 23, 50, tzinfo=BERLIN))
    day_before = dt_util.as_utc(datetime(2026, 10, 24, 23, 50, tzinfo=BERLIN))
    two_days = dt_util.as_utc(datetime(2026, 10, 23, 23, 50, tzinfo=BERLIN))
    assert current - day_before == timedelta(hours=25)

    keep, drop = split_fetchable(
        SF_2350_GRID, [day_before, two_days], current, SF_DESC.max_backfill
    )
    assert keep == [day_before]
    assert drop == [two_days]


def test_backfill_windows_are_what_opendata_keeps():
    """Counted on the 2026-10-19 listing: 288 RW runs (48 h, so 48 at :00)
    and 48 SF files (2 at 23:50 local). The window is the releases before the
    current one, so asking one further back is a 404 every round."""
    assert RW_DESC.max_backfill == 48 - 1
    assert SF_DESC.max_backfill == 2 - 1


def test_missed_releases_hourly():
    last = datetime(2026, 7, 3, 8, 0, tzinfo=UTC)
    current = datetime(2026, 7, 3, 11, 0, tzinfo=UTC)

    assert missed_releases(RW_GRID, last, current, limit=48) == (
        [datetime(2026, 7, 3, 9, 0, tzinfo=UTC), datetime(2026, 7, 3, 10, 0, tzinfo=UTC)],
        None,
    )
    # Consecutive releases leave nothing to backfill.
    assert missed_releases(RW_GRID, last, last + timedelta(hours=1), 48) == ([], None)


def test_missed_releases_keeps_only_the_newest():
    last = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    current = datetime(2026, 7, 3, 11, 0, tzinfo=UTC)

    missed, lost = missed_releases(RW_GRID, last, current, limit=3)
    assert missed == [current - timedelta(hours=h) for h in (3, 2, 1)]
    # The rest is reported, not walked: from 01:00 on the 1st to 07:00 on the 3rd.
    assert lost == (last + timedelta(hours=1), current - timedelta(hours=4))


def test_missed_releases_walks_only_the_fetchable_window():
    """A year down costs as many steps as the backfill window, not 8760."""
    steps = 0

    class Counting(ReleaseGrid):
        def next_after(self, release):
            nonlocal steps
            steps += 1
            return super().next_after(release)

    grid = Counting(RadolanRW.RELEASE_INTERVAL, RadolanRW.RELEASE_OFFSET)
    current = datetime(2026, 7, 3, 11, 0, tzinfo=UTC)
    missed, lost = missed_releases(grid, current - timedelta(days=365), current, 48)

    assert len(missed) == 48
    assert lost is not None
    assert steps < 100


def test_counted_on_grid_skips_the_overlap_after_the_grid_moved():
    """A total stored on RW's old HH:50 grid resumes without counting twice.

    After 08:50 (window 07:50-08:50) the HH:00 release 09:00 covers 08:00-09:00,
    50 minutes of it already counted; 10:00 (09:00-10:00) is the first window
    wholly after it, so 09:00 counts as counted. 08:50-09:00 is left out, once.
    """
    last = datetime(2026, 7, 3, 8, 50, tzinfo=UTC)
    counted = counted_on_grid(RW_GRID, last)

    assert counted == datetime(2026, 7, 3, 9, 0, tzinfo=UTC)
    assert missed_releases(RW_GRID, counted, datetime(2026, 7, 3, 12, 0, tzinfo=UTC), 48) == (
        [datetime(2026, 7, 3, 10, 0, tzinfo=UTC), datetime(2026, 7, 3, 11, 0, tzinfo=UTC)],
        None,
    )
    # On the grid it is itself.
    on_grid = datetime(2026, 7, 3, 9, 0, tzinfo=UTC)
    assert counted_on_grid(RW_GRID, on_grid) == on_grid


def test_counted_on_grid_keeps_local_days_across_dst():
    """sf_2350's 23- and 25-hour days are on its grid, not a grid move."""
    for day in (datetime(2026, 3, 28, 23, 50, tzinfo=BERLIN),
                datetime(2026, 10, 24, 23, 50, tzinfo=BERLIN),
                datetime(2026, 10, 25, 23, 50, tzinfo=BERLIN)):
        release = day.astimezone(UTC)
        assert counted_on_grid(SF_2350_GRID, release) == release


def test_missed_daily_releases_follow_local_time_across_dst():
    """sf_2350 sits at 23:50 local, so its UTC releases shift on DST days."""
    last = datetime(2026, 10, 23, 23, 50, tzinfo=BERLIN)  # CEST, UTC+2
    current = datetime(2026, 10, 27, 23, 50, tzinfo=BERLIN)  # CET, UTC+1

    missed, lost = missed_releases(
        SF_2350_GRID, last.astimezone(UTC), current.astimezone(UTC), 7
    )

    assert lost is None
    assert [r.astimezone(BERLIN).strftime("%m-%d %H:%M") for r in missed] == [
        "10-24 23:50",
        "10-25 23:50",
        "10-26 23:50",
    ]


# --- entity logic -----------------------------------------------------------

RELEASE = datetime(2026, 7, 3, 11, 0, tzinfo=UTC)


async def test_first_release_sets_starting_point_only(make_total_sensor):
    sensor, tasks = make_total_sensor(release=RELEASE, value=2.5)

    sensor._count_new_release()

    assert sensor.native_value == 0.0
    assert sensor.available
    assert sensor.extra_state_attributes == {"counted_until": RELEASE.isoformat()}
    assert tasks == []


async def test_no_data_yet_is_unavailable(make_total_sensor):
    sensor, _ = make_total_sensor()
    sensor._count_new_release()

    assert sensor.native_value is None
    assert not sensor.available


async def test_next_release_is_added(make_total_sensor):
    sensor, tasks = make_total_sensor(
        release=RELEASE, value=2.5, total=10.0, last_release=RELEASE - timedelta(hours=1)
    )

    sensor._count_new_release()

    assert sensor.native_value == approx(12.5)
    assert sensor._last_release == RELEASE
    assert tasks == []


async def test_same_release_is_counted_once(make_total_sensor):
    sensor, _ = make_total_sensor(
        release=RELEASE, value=2.5, total=10.0, last_release=RELEASE - timedelta(hours=1)
    )

    for _ in range(3):
        sensor._count_new_release()

    assert sensor.native_value == approx(12.5)


async def test_equal_consecutive_values_are_both_counted(make_total_sensor):
    """Keyed on the release, not on the value changing."""
    sensor, _ = make_total_sensor(
        release=RELEASE, value=0.4, total=0.0, last_release=RELEASE - timedelta(hours=1)
    )
    sensor._count_new_release()

    sensor.coordinator.curr_release = RELEASE + timedelta(hours=1)
    sensor._count_new_release()

    assert sensor.native_value == approx(0.8)


async def test_unusable_reading_is_skipped_but_marked_counted(make_total_sensor):
    sensor, _ = make_total_sensor(
        release=RELEASE,
        value=float("nan"),
        total=10.0,
        last_release=RELEASE - timedelta(hours=1),
    )

    sensor._count_new_release()

    assert sensor.native_value == approx(10.0)
    assert sensor._last_release == RELEASE


async def test_gap_starts_a_backfill_of_the_missed_releases(make_total_sensor):
    sensor, tasks = make_total_sensor(
        release=RELEASE, value=2.5, total=10.0, last_release=RELEASE - timedelta(hours=3)
    )

    sensor._count_new_release()

    # The current release is counted at once; the two missed ones go to the task.
    assert sensor.native_value == approx(12.5)
    assert sensor._pending == [RELEASE - timedelta(hours=h) for h in (2, 1)]
    assert len(tasks) == 1
    _close(tasks)


async def test_release_overlapping_an_old_grid_total_is_not_counted(make_total_sensor):
    """Upgraded from RW's HH:50 grid: 11:00 overlaps 10:50, 12:00 does not."""
    old = datetime(2026, 7, 3, 10, 50, tzinfo=UTC)
    sensor, tasks = make_total_sensor(release=RELEASE, value=2.5)
    sensor._restore(PrecipitationTotalExtraData(total=10.0, last_release=old))

    # Restored onto the new grid: 11:00 stands for it, so it is not counted.
    assert sensor._last_release == RELEASE
    sensor._count_new_release()

    assert sensor.native_value == approx(10.0)
    assert sensor._last_release == RELEASE

    sensor.coordinator.curr_release = RELEASE + timedelta(hours=1)
    sensor._count_new_release()

    assert sensor.native_value == approx(12.5)
    assert sensor._last_release == RELEASE + timedelta(hours=1)
    assert tasks == []


@pytest.mark.asyncio
async def test_backfill_keeps_a_failed_release_pending(make_total_sensor):
    """A failed fetch is not lost: it stays on the list for the next round."""
    missed = [RELEASE - timedelta(hours=2), RELEASE - timedelta(hours=1)]
    sensor, tasks = make_total_sensor(total=10.0, last_release=RELEASE, pending=missed)
    sensor.coordinator.async_fetch_release = AsyncMock(
        side_effect=[OSError("not there yet"), CoordinatorData({"amount": 1.5}, {})]
    )

    sensor._start_backfill()  # what a restart does
    assert len(tasks) == 1
    await tasks[0]

    assert sensor.native_value == approx(11.5)
    fetched = sensor.coordinator.async_fetch_release.call_args_list
    assert [c.args[0] for c in fetched] == missed
    assert sensor._pending == [missed[0]]
    assert sensor._backfilling is False
    # Stored with the total, so a restart keeps it too.
    assert sensor.extra_restore_state_data.pending == [missed[0]]


@pytest.mark.asyncio
async def test_failed_release_is_retried_with_the_next_release(make_total_sensor):
    sensor, tasks = make_total_sensor(
        release=RELEASE,
        value=2.5,
        total=10.0,
        last_release=RELEASE - timedelta(hours=1),
        pending=[RELEASE - timedelta(hours=3)],
    )

    sensor._count_new_release()

    assert sensor._pending == [RELEASE - timedelta(hours=3)]
    assert len(tasks) == 1
    await tasks[0]
    assert sensor.native_value == approx(12.5 + 1.0)
    assert sensor._pending == []


@pytest.mark.asyncio
async def test_release_without_data_leaves_the_list_and_adds_nothing(make_total_sensor):
    """A file DWD serves without data for the cell is done, not retried."""
    sensor, tasks = make_total_sensor(
        total=10.0, last_release=RELEASE, pending=[RELEASE - timedelta(hours=1)]
    )
    sensor.coordinator.async_fetch_release = AsyncMock(
        return_value=CoordinatorData({"amount": None}, {})
    )

    sensor._start_backfill()
    await tasks[0]

    assert sensor.native_value == approx(10.0)
    assert sensor._pending == []


async def test_only_one_backfill_runs_at_a_time(make_total_sensor):
    sensor, tasks = make_total_sensor(
        release=RELEASE, value=0.0, total=0.0, last_release=RELEASE - timedelta(hours=3)
    )
    sensor._count_new_release()
    sensor.coordinator.curr_release = RELEASE + timedelta(hours=2)
    sensor._count_new_release()

    # The second gap joins the list the running round works through.
    assert len(tasks) == 1
    assert sensor._pending == [
        RELEASE - timedelta(hours=2),
        RELEASE - timedelta(hours=1),
        RELEASE + timedelta(hours=1),
    ]
    _close(tasks)


async def test_pending_too_old_to_fetch_is_given_up(make_total_sensor, caplog):
    sensor, tasks = make_total_sensor(
        release=RELEASE,
        value=0.0,
        total=0.0,
        last_release=RELEASE - timedelta(hours=1),
        pending=[RELEASE - timedelta(hours=49), RELEASE - timedelta(hours=2)],
    )

    sensor._count_new_release()

    assert sensor._pending == [RELEASE - timedelta(hours=2)]
    assert "1 missed DWD release(s)" in caplog.text
    _close(tasks)


# --- end to end ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_resumes_a_pending_backfill(make_entry, hass: HomeAssistant, freezer) -> None:
    """A backfill a restart interrupted resumes at startup, with no new release."""
    freezer.move_to("2026-07-03 11:30:00+00:00")
    entity_id = "sensor.home_precipitation_total"
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(entity_id, "10.0"),
                PrecipitationTotalExtraData(
                    total=10.0,
                    last_release=datetime(2026, 7, 3, 11, 0, tzinfo=UTC),
                    pending=[datetime(2026, 7, 3, 9, 0, tzinfo=UTC)],
                ).as_dict(),
            )
        ],
    )
    entry = make_entry()

    rw_value = WORKING_PRODUCTS[RadolanRW][0]["amount"]
    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        fetched = RadolanRW._fetch_and_parse.call_args_list

    assert [c.args[0] for c in fetched] == [
        datetime(2026, 7, 3, h, 0, tzinfo=UTC) for h in (11, 9)
    ]
    assert float(hass.states.get(entity_id).state) == approx(10.0 + rw_value)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()



@pytest.mark.asyncio
async def test_restore_without_a_total_starts_over(make_entry, hass: HomeAssistant, freezer) -> None:
    """A payload with releases but no total counted nothing: start from 0."""
    freezer.move_to("2026-07-03 11:30:00+00:00")
    entity_id = "sensor.home_precipitation_total"
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(entity_id, "unknown"),
                {
                    "total": None,
                    "last_release": "2026-07-03T08:00:00+00:00",
                    "pending": ["2026-07-03T07:00:00+00:00"],
                },
            )
        ],
    )
    entry = make_entry()

    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        fetched = RadolanRW._fetch_and_parse.call_args_list

    # Only the live release: it sets the starting point, nothing is backfilled.
    assert [c.args[0] for c in fetched] == [datetime(2026, 7, 3, 11, 0, tzinfo=UTC)]
    state = hass.states.get(entity_id)
    assert float(state.state) == 0.0
    assert state.attributes["counted_until"] == "2026-07-03T11:00:00+00:00"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("restored_release", "backfilled"),
    [
        # Restored at 08:00, back up when 11:00 is the latest.
        (datetime(2026, 7, 3, 8, 0, tzinfo=UTC), (9, 10)),
        # Restored from the old HH:50 grid: 08:00 overlaps 07:50 and is skipped.
        (datetime(2026, 7, 3, 7, 50, tzinfo=UTC), (9, 10)),
    ],
    ids=["on_grid", "from_hh50_grid"],
)
async def test_restart_restores_total_and_backfills_the_gap(
    make_entry,
    hass: HomeAssistant, freezer, restored_release, backfilled
) -> None:
    """The missed releases between the restored one and 11:00 are fetched."""
    freezer.move_to("2026-07-03 11:30:00+00:00")
    entity_id = "sensor.home_precipitation_total"
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(entity_id, "10.0"),
                PrecipitationTotalExtraData(
                    total=10.0,
                    last_release=restored_release,
                ).as_dict(),
            )
        ],
    )
    entry = make_entry()

    rw_value = WORKING_PRODUCTS[RadolanRW][0]["amount"]
    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        fetched = RadolanRW._fetch_and_parse.call_args_list

    # The live release plus the missed ones.
    assert [c.args[0] for c in fetched] == [
        datetime(2026, 7, 3, h, 0, tzinfo=UTC) for h in (11, *backfilled)
    ]

    state = hass.states.get(entity_id)
    assert float(state.state) == approx(10.0 + (1 + len(backfilled)) * rw_value)
    assert state.attributes["counted_until"] == "2026-07-03T11:00:00+00:00"
    assert state.attributes["state_class"] == "total_increasing"

    # A new install gets the daily total disabled: registered, but not running.
    daily = er.async_get(hass).async_get("sensor.home_precipitation_total_daily")
    assert daily.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get("sensor.home_precipitation_total_daily") is None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_existing_daily_total_stays_enabled(make_entry, hass: HomeAssistant, freezer) -> None:
    """Disabled by default only applies when the entity is first registered."""
    freezer.move_to("2026-07-03 11:30:00+00:00")
    entry = make_entry()
    # As 2026.10.0 registered it.
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_radolan_sf_yesterday_total",
        config_entry=entry,
        suggested_object_id="home_precipitation_total_daily",
    )

    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    daily = er.async_get(hass).async_get("sensor.home_precipitation_total_daily")
    assert daily.disabled_by is None
    assert float(hass.states.get("sensor.home_precipitation_total_daily").state) == 0.0

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
