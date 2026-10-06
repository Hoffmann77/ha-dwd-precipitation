"""Cumulative "Precipitation total" sensors -- needs HA installed.

The entity logic is exercised against stub coordinators, as in test_sensor.py;
the last test runs a real entry setup to cover restore and backfill end to end.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from pytest import approx
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from custom_components.dwd_precipitation.const import DOMAIN
from custom_components.dwd_precipitation.coordinator import CoordinatorData
from custom_components.dwd_precipitation.precipitation_total import (
    PrecipitationTotalExtraData,
    countable,
    missed_releases,
)
from custom_components.dwd_precipitation.products import (
    RadolanRW,
    RadolanSFLastYesterday,
)
from custom_components.dwd_precipitation.sensor import (
    TOTAL_SENSORS,
    PrecipitationTotalSensor,
)

from .test_setup_entry import WORKING_PRODUCTS, _patched_products

UTC = timezone.utc
BERLIN = ZoneInfo("Europe/Berlin")

RW_DESC, SF_DESC = TOTAL_SENSORS


class _Grid:
    """Just enough coordinator to walk a product's release grid."""

    def __init__(self, product: type) -> None:
        self.USE_LOCAL_TIME = product.USE_LOCAL_TIME
        self.RELEASE_INTERVAL = product.RELEASE_INTERVAL

    _next_release_after = RadolanRW._next_release_after


@pytest.fixture
def berlin_time_zone():
    """Run with Home Assistant's local time zone set to Germany's."""
    previous = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(BERLIN)
    yield
    dt_util.set_default_time_zone(previous)


def _make_total_sensor(
    *, release=None, value=None, total=None, last_release=None, desc=RW_DESC
) -> tuple[PrecipitationTotalSensor, list]:
    """Return a total sensor on a stub RW coordinator, and its started tasks."""
    tasks: list = []
    grid = _Grid(RadolanRW)

    def _create_task(_hass, coro, _name):
        tasks.append(coro)

    sensor = PrecipitationTotalSensor.__new__(PrecipitationTotalSensor)
    sensor.entity_description = desc
    sensor.entity_id = "sensor.home_precipitation_total_hourly"
    sensor.hass = None
    sensor._total = total
    sensor._last_release = last_release
    sensor.async_write_ha_state = lambda: None
    sensor.coordinator = SimpleNamespace(
        curr_release=release,
        data=None if release is None else CoordinatorData(data=value, metadata={}),
        _next_release_after=lambda r: grid._next_release_after(r),
        _fetch_and_parse=AsyncMock(return_value=(1.0, {})),
        config_entry=SimpleNamespace(async_create_background_task=_create_task),
    )

    return sensor, tasks


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
        total=12.3, last_release=datetime(2026, 7, 3, 11, 50, tzinfo=UTC)
    )
    restored = PrecipitationTotalExtraData.from_dict(stored.as_dict())
    assert restored == stored

    empty = PrecipitationTotalExtraData.from_dict({})
    assert empty.total is None
    assert empty.last_release is None


def test_missed_releases_hourly():
    last = datetime(2026, 7, 3, 8, 50, tzinfo=UTC)
    current = datetime(2026, 7, 3, 11, 50, tzinfo=UTC)

    assert missed_releases(_Grid(RadolanRW), last, current, limit=48) == [
        datetime(2026, 7, 3, 9, 50, tzinfo=UTC),
        datetime(2026, 7, 3, 10, 50, tzinfo=UTC),
    ]
    # Consecutive releases leave nothing to backfill.
    assert missed_releases(_Grid(RadolanRW), last, last + timedelta(hours=1), 48) == []


def test_missed_releases_keeps_only_the_newest():
    last = datetime(2026, 7, 1, 0, 50, tzinfo=UTC)
    current = datetime(2026, 7, 3, 11, 50, tzinfo=UTC)

    missed = missed_releases(_Grid(RadolanRW), last, current, limit=3)
    assert missed == [current - timedelta(hours=h) for h in (3, 2, 1)]


def test_missed_daily_releases_follow_local_time_across_dst(berlin_time_zone):
    """sf_2350 sits at 23:50 local, so its UTC releases shift on DST days."""
    last = datetime(2026, 10, 23, 23, 50, tzinfo=BERLIN)  # CEST, UTC+2
    current = datetime(2026, 10, 27, 23, 50, tzinfo=BERLIN)  # CET, UTC+1

    missed = missed_releases(
        _Grid(RadolanSFLastYesterday), dt_util.as_utc(last), dt_util.as_utc(current), 7
    )

    assert [dt_util.as_local(r).strftime("%m-%d %H:%M") for r in missed] == [
        "10-24 23:50",
        "10-25 23:50",
        "10-26 23:50",
    ]


# --- entity logic -----------------------------------------------------------

RELEASE = datetime(2026, 7, 3, 11, 50, tzinfo=UTC)


def test_first_release_sets_starting_point_only():
    sensor, tasks = _make_total_sensor(release=RELEASE, value=2.5)

    sensor._count_new_release()

    assert sensor.native_value == 0.0
    assert sensor.available
    assert sensor.extra_state_attributes == {"counted_until": RELEASE.isoformat()}
    assert tasks == []


def test_no_data_yet_is_unavailable():
    sensor, _ = _make_total_sensor()
    sensor._count_new_release()

    assert sensor.native_value is None
    assert not sensor.available


def test_next_release_is_added():
    sensor, tasks = _make_total_sensor(
        release=RELEASE, value=2.5, total=10.0, last_release=RELEASE - timedelta(hours=1)
    )

    sensor._count_new_release()

    assert sensor.native_value == approx(12.5)
    assert sensor._last_release == RELEASE
    assert tasks == []


def test_same_release_is_counted_once():
    sensor, _ = _make_total_sensor(
        release=RELEASE, value=2.5, total=10.0, last_release=RELEASE - timedelta(hours=1)
    )

    for _ in range(3):
        sensor._count_new_release()

    assert sensor.native_value == approx(12.5)


def test_equal_consecutive_values_are_both_counted():
    """Keyed on the release, not on the value changing."""
    sensor, _ = _make_total_sensor(
        release=RELEASE, value=0.4, total=0.0, last_release=RELEASE - timedelta(hours=1)
    )
    sensor._count_new_release()

    sensor.coordinator.curr_release = RELEASE + timedelta(hours=1)
    sensor._count_new_release()

    assert sensor.native_value == approx(0.8)


def test_unusable_reading_is_skipped_but_marked_counted():
    sensor, _ = _make_total_sensor(
        release=RELEASE,
        value=float("nan"),
        total=10.0,
        last_release=RELEASE - timedelta(hours=1),
    )

    sensor._count_new_release()

    assert sensor.native_value == approx(10.0)
    assert sensor._last_release == RELEASE


def test_gap_starts_a_backfill_of_the_missed_releases():
    sensor, tasks = _make_total_sensor(
        release=RELEASE, value=2.5, total=10.0, last_release=RELEASE - timedelta(hours=3)
    )

    sensor._count_new_release()

    # The current release is counted at once; the two missed ones go to the task.
    assert sensor.native_value == approx(12.5)
    assert len(tasks) == 1
    _close(tasks)


@pytest.mark.asyncio
async def test_backfill_adds_fetched_releases_and_skips_failures():
    sensor, _ = _make_total_sensor(total=10.0)
    missed = [RELEASE - timedelta(hours=2), RELEASE - timedelta(hours=1)]
    sensor.coordinator._fetch_and_parse = AsyncMock(
        side_effect=[OSError("gone from OpenData"), (1.5, {})]
    )

    await sensor._async_backfill(missed)

    assert sensor.native_value == approx(11.5)
    assert [c.args[0] for c in sensor.coordinator._fetch_and_parse.call_args_list] == missed


# --- end to end ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_restores_total_and_backfills_the_gap(
    hass: HomeAssistant, freezer
) -> None:
    """Restored at 08:50, back up when 11:50 is the latest: 09:50/10:50 are fetched."""
    freezer.move_to("2026-07-03 12:30:00+00:00")
    entity_id = "sensor.home_precipitation_total_hourly"
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(entity_id, "10.0"),
                PrecipitationTotalExtraData(
                    total=10.0,
                    last_release=datetime(2026, 7, 3, 8, 50, tzinfo=UTC),
                ).as_dict(),
            )
        ],
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        data={"name": "Home", "latitude": 51.05, "longitude": 13.73},
        options={},
    )
    entry.add_to_hass(hass)

    rw_value, _ = WORKING_PRODUCTS[RadolanRW]
    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        fetched = RadolanRW._fetch_and_parse.call_args_list

    # The live release plus the two missed ones.
    assert [c.args[0] for c in fetched] == [
        datetime(2026, 7, 3, h, 50, tzinfo=UTC) for h in (11, 9, 10)
    ]

    state = hass.states.get(entity_id)
    assert float(state.state) == approx(10.0 + 3 * rw_value)
    assert state.attributes["counted_until"] == "2026-07-03T11:50:00+00:00"
    assert state.attributes["state_class"] == "total_increasing"

    # A fresh install starts the daily total at zero.
    assert float(hass.states.get("sensor.home_precipitation_total_daily").state) == 0.0

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
