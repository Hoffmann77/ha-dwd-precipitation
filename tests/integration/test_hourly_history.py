"""The hourly precipitation history: recording, pruning, restore, fill, reuse."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest import approx
from pytest_homeassistant.common import mock_restore_cache_with_extra_data

from custom_components.dwd_precipitation.const import DOMAIN, RW_KEPT
from custom_components.dwd_precipitation.coordinator import ProductMetadata
from custom_components.dwd_precipitation.entity import unique_id_for
from custom_components.dwd_precipitation.hourly_history import (
    HOURLY_HISTORY_STORE_VERSION,
    HourlyHistoryState,
    hour_window,
    hours_to_fetch,
    missing_hours,
)
from custom_components.dwd_precipitation.precipitation_total import (
    PrecipitationTotalExtraData,
)
from custom_components.dwd_precipitation.products import RadolanRW, RadolanRW10
from custom_components.dwd_precipitation.release_grid import ReleaseGrid
from custom_components.dwd_precipitation.sensor import HourlyHistorySensor

from tests.entity_ids import OPT_IN_SINCE_2026_10_0, RELEASED_2026_10_0_IDS

from .test_setup_entry import _patched_products

UTC = timezone.utc
HOUR = timedelta(hours=1)
T = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
GRID = ReleaseGrid(RadolanRW.RELEASE_INTERVAL, RadolanRW.RELEASE_OFFSET)
ON = {"hourly_history": True}


def _store_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}.hourly_history"


def _stored(hass_storage, entry, hours: dict[datetime, float | None]) -> None:
    key = _store_key(entry.entry_id)
    hass_storage[key] = {
        "version": HOURLY_HISTORY_STORE_VERSION,
        "minor_version": 1,
        "key": key,
        "data": HourlyHistoryState(dict(hours)).as_dict(),
    }


def _rw_file(rain=lambda _t: 0.5, missing=()):
    """A fake RW _fetch_and_parse: ``rain(hour)`` mm, 404 for ``missing``."""

    async def fetch(ts: datetime):
        if ts in missing:
            raise aiohttp.ClientError("404")
        meta = ProductMetadata("RW", ts, data_start=ts - HOUR, data_end=ts)
        return {"amount": rain(ts)}, {"amount": meta}

    return AsyncMock(side_effect=fetch)


async def _adopt(rw: RadolanRW, release: datetime, mm: float | None = 0.5) -> None:
    """What the coordinator does for one adopted release, and the fill it starts."""
    await rw._async_on_new_release(release, {"amount": mm}, {})
    history = rw.history
    assert history is not None
    if history.fill_task is not None:
        await history.fill_task


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


def test_the_window_ends_at_the_latest_hour() -> None:
    window = hour_window(GRID, T, 3)
    assert window == [T - 2 * HOUR, T - HOUR, T]


def test_missing_hours_are_the_window_minus_the_held() -> None:
    state = HourlyHistoryState({T: 0.1, T - 2 * HOUR: None})
    assert missing_hours(state, GRID, T, 3) == [T - HOUR]


def test_only_hours_opendata_keeps_are_fetched_newest_first() -> None:
    fetchable = hours_to_fetch(HourlyHistoryState(), GRID, T, 72)
    assert fetchable[0] == T and len(fetchable) == RW_KEPT + 1
    assert fetchable[-1] == T - RW_KEPT * HOUR


def test_the_state_round_trips_and_rejects_damage() -> None:
    state = HourlyHistoryState({T: 0.4, T - HOUR: None})
    assert HourlyHistoryState.from_dict(state.as_dict()) == state
    for raw in ({"hours": []}, {"hours": {"x": 1.0}}, {"hours": {T.isoformat(): "1"}}):
        with pytest.raises(ValueError):
            HourlyHistoryState.from_dict(raw)


# ---------------------------------------------------------------------------
# The RW coordinator keeps it
# ---------------------------------------------------------------------------


def test_only_the_hourly_product_has_a_history(make_coordinator) -> None:
    assert make_coordinator(RadolanRW, ON).history is not None
    assert make_coordinator(RadolanRW10, ON).history is None
    assert make_coordinator(RadolanRW).history is None


@pytest.mark.asyncio
async def test_an_adopted_release_is_kept_and_old_hours_dropped(make_coordinator) -> None:
    rw = make_coordinator(RadolanRW, {**ON, "hourly_history_hours": 3, "hourly_history_fetch": False})
    for k in range(5):
        await _adopt(rw, T + k * HOUR, mm=float(k))

    assert rw.history.state.hours == {T + 2 * HOUR: 2.0, T + 3 * HOUR: 3.0, T + 4 * HOUR: 4.0}


@pytest.mark.asyncio
async def test_missing_hours_are_fetched_newest_first(make_coordinator) -> None:
    rw = make_coordinator(RadolanRW, {**ON, "hourly_history_hours": 4})
    fetch = _rw_file(rain=lambda t: t.hour / 10)
    with patch.object(RadolanRW, "_fetch_and_parse", new=fetch):
        await _adopt(rw, T)

    assert [c.args[0] for c in fetch.call_args_list] == [T - HOUR, T - 2 * HOUR, T - 3 * HOUR]
    assert rw.history.state.hours[T - 3 * HOUR] == approx(0.9)


@pytest.mark.asyncio
async def test_a_failed_fetch_ends_the_round_and_is_retried(make_coordinator, caplog) -> None:
    rw = make_coordinator(RadolanRW, {**ON, "hourly_history_hours": 4})
    fetch = _rw_file(missing={T - 2 * HOUR})
    with patch.object(RadolanRW, "_fetch_and_parse", new=fetch):
        await _adopt(rw, T)
        assert set(rw.history.state.hours) == {T, T - HOUR}
        await _adopt(rw, T + HOUR)

    tried = [c.args[0] for c in fetch.call_args_list]
    assert tried == [T - HOUR, T - 2 * HOUR, T - 2 * HOUR]  # retried with the next release
    infos = [r for r in caplog.records if "hourly precipitation history" in r.message]
    assert len(infos) == 1


@pytest.mark.asyncio
async def test_without_the_fetch_option_nothing_is_downloaded(make_coordinator) -> None:
    rw = make_coordinator(RadolanRW, {**ON, "hourly_history_fetch": False})
    fetch = _rw_file()
    with patch.object(RadolanRW, "_fetch_and_parse", new=fetch):
        await _adopt(rw, T)
        # Hours another sensor fetches are kept all the same.
        await rw.async_fetch_release(T - 5 * HOUR)

    assert [c.args[0] for c in fetch.call_args_list] == [T - 5 * HOUR]
    assert set(rw.history.state.hours) == {T, T - 5 * HOUR}


@pytest.mark.asyncio
async def test_a_held_hour_is_not_downloaded_again(make_coordinator) -> None:
    rw = make_coordinator(RadolanRW, {**ON, "hourly_history_fetch": False})
    await _adopt(rw, T, mm=1.2)
    fetch = _rw_file()
    with patch.object(RadolanRW, "_fetch_and_parse", new=fetch):
        held = await rw.async_fetch_release(T)

    fetch.assert_not_called()
    assert held.data["amount"] == 1.2
    meta = held.metadata["amount"]
    assert (meta.data_start, meta.data_end) == (T - HOUR, T)


@pytest.mark.asyncio
async def test_no_data_for_the_cell_is_held_as_null(make_coordinator) -> None:
    rw = make_coordinator(RadolanRW, {**ON, "hourly_history_fetch": False})
    await _adopt(rw, T, mm=None)
    assert rw.history.state.hours == {T: None}
    assert rw.history.view(T)["hours"] == {T.isoformat(): None}


@pytest.mark.asyncio
async def test_the_history_survives_a_restart(make_coordinator, make_entry) -> None:
    entry = make_entry(ON)
    before = make_coordinator(RadolanRW, entry=entry)
    with patch.object(RadolanRW, "_fetch_and_parse", new=_rw_file()):
        await _adopt(before, T, mm=0.7)
    await before.history.async_save()  # what unloading the entry does

    after = make_coordinator(RadolanRW, entry=entry)
    fetch = _rw_file()
    with patch.object(RadolanRW, "_fetch_and_parse", new=fetch):
        await _adopt(after, T + HOUR)

    assert after.history.state.hours[T] == 0.7
    # The fill fetches the hours it lacks, but not the one it restored.
    assert T not in [c.args[0] for c in fetch.call_args_list]


@pytest.mark.asyncio
async def test_an_unreadable_store_is_discarded(make_coordinator, make_entry, hass_storage, caplog) -> None:
    entry = make_entry({**ON, "hourly_history_fetch": False})
    key = _store_key(entry.entry_id)
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {"hours": [1]}}
    rw = make_coordinator(RadolanRW, entry=entry)
    await _adopt(rw, T)

    assert rw.history.state.hours == {T: 0.5}
    assert any("Discarding the saved hourly" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_the_view_lists_the_held_and_the_missing(make_coordinator) -> None:
    rw = make_coordinator(RadolanRW, {**ON, "hourly_history_hours": 3, "hourly_history_fetch": False})
    await _adopt(rw, T - HOUR, mm=0.3)

    # DWD is late with T: it shows as missing, the newest held stays the state.
    view = rw.history.view(T)
    assert view == {
        "hours": {(T - HOUR).isoformat(): 0.3},
        "missing": [(T - 2 * HOUR).isoformat(), T.isoformat()],
        "hours_kept": 3,
    }
    assert rw.history.newest(T) == T - HOUR


# ---------------------------------------------------------------------------
# The entry
# ---------------------------------------------------------------------------


def _history_state(hass: HomeAssistant, entry):
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, unique_id_for(entry.entry_id, "radolan_rw_history")
    )
    return entity_id, (hass.states.get(entity_id) if entity_id else None)


@pytest.mark.asyncio
async def test_the_sensor_shows_the_hours(make_entry, hass: HomeAssistant, freezer, hass_storage) -> None:
    freezer.move_to("2026-11-17 12:30:00+00:00")
    entry = make_entry({**ON, "hourly_history_hours": 3, "hourly_history_fetch": False})
    _stored(hass_storage, entry, {T - HOUR: 0.4})
    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entity_id, state = _history_state(hass, entry)
    slug = OPT_IN_SINCE_2026_10_0["radolan_rw_history"]
    assert entity_id == f"sensor.home_{slug}"
    assert slug not in RELEASED_2026_10_0_IDS.values()
    assert state.state == T.isoformat()
    assert state.attributes["hours"] == {(T - HOUR).isoformat(): 0.4, T.isoformat(): 3.2}
    assert state.attributes["missing"] == [(T - 2 * HOUR).isoformat()]
    assert state.attributes["hours_kept"] == 3
    entity = er.async_get(hass).async_get(entity_id)
    assert entity.entity_category is not None  # diagnostic
    # A few KB that change every hour: none is recorded.
    assert {"hours", "missing", "hours_kept"} <= HourlyHistorySensor._unrecorded_attributes

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_the_entry_stores_share_one_deadline(make_entry, hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-11-17 12:30:00+00:00")
    entry = make_entry({**ON, "rain_events": True, "hourly_history_fetch": False})
    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinators = entry.runtime_data.coordinators
    assert coordinators["rw"].history.save_deadline is coordinators["rv"].rain_tracker.save_deadline

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_turning_it_off_removes_the_sensor_and_the_store(make_entry, hass: HomeAssistant, freezer, hass_storage) -> None:
    freezer.move_to("2026-11-17 12:30:00+00:00")
    entry = make_entry({**ON, "hourly_history_fetch": False})
    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert _history_state(hass, entry)[0] is not None

    with _patched_products():
        hass.config_entries.async_update_entry(entry, options={"hourly_history": False})
        await hass.async_block_till_done()

    assert _history_state(hass, entry)[0] is None
    assert _store_key(entry.entry_id) not in hass_storage

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_removing_the_entry_deletes_the_store(make_entry, hass: HomeAssistant, freezer, hass_storage) -> None:
    freezer.move_to("2026-11-17 12:30:00+00:00")
    entry = make_entry({**ON, "hourly_history_fetch": False})
    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert _store_key(entry.entry_id) not in hass_storage


@pytest.mark.asyncio
async def test_the_totals_backfill_reads_held_hours(make_entry, hass: HomeAssistant, freezer, hass_storage) -> None:
    """A restart three hours late: the history holds two of the missed hours,
    so only the third is downloaded, for the total and the history alike."""
    freezer.move_to("2026-11-17 12:30:00+00:00")
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State("sensor.home_precipitation_total", "10.0"),
                PrecipitationTotalExtraData(total=10.0, last_release=T - 4 * HOUR).as_dict(),
            )
        ],
    )
    entry = make_entry({**ON, "hourly_history_hours": 6})
    _stored(hass_storage, entry, {T - 3 * HOUR: 1.0, T - 2 * HOUR: 2.0})
    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        fetched = sorted(c.args[0] for c in RadolanRW._fetch_and_parse.call_args_list)

    # T itself, then each missing hour once: T-1 for the total and the
    # history, T-4 and T-5 for the history only.
    assert fetched == [T - 5 * HOUR, T - 4 * HOUR, T - HOUR, T]
    total = hass.states.get("sensor.home_precipitation_total")
    assert float(total.state) == approx(10.0 + 1.0 + 2.0 + 3.2 + 3.2)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
