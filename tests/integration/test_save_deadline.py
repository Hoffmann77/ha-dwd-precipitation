"""SaveDeadline: one fixed idle-save moment for an entry's stores."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import async_fire_time_changed

from custom_components.dwd_precipitation.save_deadline import IDLE_SAVE_DELAY, SaveDeadline

T0 = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def test_later_saves_keep_the_due_time() -> None:
    deadline = SaveDeadline()
    assert deadline.seconds_left(T0) == IDLE_SAVE_DELAY.total_seconds()
    assert deadline.seconds_left(T0 + HOUR) == (IDLE_SAVE_DELAY - HOUR).total_seconds()


def test_a_passed_due_time_starts_a_new_period() -> None:
    deadline = SaveDeadline()
    deadline.seconds_left(T0)
    later = T0 + IDLE_SAVE_DELAY
    assert deadline.seconds_left(later) == IDLE_SAVE_DELAY.total_seconds()


def test_six_hours_means_four_idle_writes_a_day() -> None:
    deadline = SaveDeadline()
    due = set()
    t = T0
    while t < T0 + timedelta(days=1):  # one save request every 5 minutes
        due.add(t + timedelta(seconds=deadline.seconds_left(t)))
        t += timedelta(minutes=5)
    assert len(due) == 4


@pytest.mark.asyncio
async def test_two_stores_write_together_at_the_deadline(
    hass: HomeAssistant, hass_storage, freezer
) -> None:
    freezer.move_to(T0)
    deadline = SaveDeadline()
    first = Store(hass, 1, "dwd_precipitation.test.first")
    second = Store(hass, 1, "dwd_precipitation.test.second")

    deadline.delay_save(first, lambda: {"n": 1})
    freezer.tick(HOUR)
    async_fire_time_changed(hass)
    deadline.delay_save(second, lambda: {"n": 2})
    deadline.delay_save(first, lambda: {"n": 3})  # does not move the write
    await hass.async_block_till_done()
    assert "dwd_precipitation.test.first" not in hass_storage

    freezer.move_to(T0 + IDLE_SAVE_DELAY)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass_storage["dwd_precipitation.test.first"]["data"] == {"n": 3}
    assert hass_storage["dwd_precipitation.test.second"]["data"] == {"n": 2}
