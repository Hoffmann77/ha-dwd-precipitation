"""RV's rain-events glue: fill, track, publish and persist through the tracker."""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import numpy as np
import pytest

from custom_components.dwd_precipitation import products, rain_events_tracker
from custom_components.dwd_precipitation.coordinator import CoordinatorData
from custom_components.dwd_precipitation.products import RadvorRV
from custom_components.dwd_precipitation.rain_events_tracker import RainEventsTracker

from tests.factories.radvor import RangeServer, make_radvor_tar
from tests.integration.product_helpers import rv_what


class _FakeStore:
    """Stands in for homeassistant.helpers.storage.Store."""

    def __init__(self, data=None) -> None:
        self.data = data
        self.delays: list[float] = []

    async def async_load(self):
        return self.data

    def async_delay_save(self, data_func, delay):
        self.data = data_func()
        self.delays.append(delay)

    async def async_save(self, data):
        self.data = data


def _rv_release_tar(ts: datetime) -> bytes:
    """An RV tar whose member payloads name their release and lead."""
    return make_radvor_tar("rv", ts, lambda lead: f"{ts:%H%M}:{lead:03d}".encode())


class _RVWorld:
    """Serves RV releases (whole or by range) for a rain function."""

    def __init__(self, rain, missing=(), garbled=(), delay=0.0) -> None:
        self.rain = rain  # step end -> mm
        self.missing = set(missing)  # releases DWD does not serve
        self.garbled = set(garbled)  # releases served with the wrong window
        self.delay = delay  # seconds each range read takes
        self.requests: list[tuple[datetime, dict | None]] = []

    async def get(self, url, _client, headers=None, **_kw):
        stamp = url.rsplit("_", 2)[-2] + url.rsplit("_", 1)[-1][:4]
        ts = datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
        self.requests.append((ts, headers))
        if headers and self.delay:
            await asyncio.sleep(self.delay)
        if ts in self.missing:
            import aiohttp
            from yarl import URL

            info = aiohttp.RequestInfo(URL(url), "GET", {}, URL(url))
            raise aiohttp.ClientResponseError(info, (), status=404, message="Not Found")
        return await RangeServer(_rv_release_tar(ts)).fetch(url, headers)

    def read(self, fileobj, _row, _col, **_kw):
        stamp, lead = fileobj.getvalue().decode().split(":")
        base = DAY_RV.replace(hour=int(stamp[:2]), minute=int(stamp[2:]))
        step_end = base + timedelta(minutes=int(lead))
        if base in self.garbled:
            base -= timedelta(minutes=5)
        return np.float32(self.rain(step_end)), rv_what(base, int(lead))


DAY_RV = datetime(2026, 10, 12, tzinfo=timezone.utc)


def _rv_tracked(make_coordinator, store=None, options=None):
    coord = make_coordinator(RadvorRV, options)
    coord.published: list[dict | None] = []
    coord.async_update_listeners = lambda: coord.published.append(
        coord.data.data["rain_events"]
    )
    coord._rain_tracker = RainEventsTracker(
        coord.hass,
        coord.config_entry,
        coord.options.rain_event_threshold,
        coord._async_fetch_analysis,
        coord._publish_rain_view,
        store=store if store is not None else _FakeStore(),
    )
    return coord


@contextmanager
def _serving(world):
    with (
        patch.object(products, "async_get", side_effect=world.get),
        patch.object(products, "read_odim_composite_cell", side_effect=world.read),
    ):
        yield


async def _rv_refresh(coord, world, hhmm):
    """What the coordinator does for one release: fetch, then store the data."""
    ts = DAY_RV.replace(hour=int(hhmm[:2]), minute=int(hhmm[3:]))
    with _serving(world):
        data, metadata = await coord._fetch_and_parse(ts)
        await coord._async_on_new_release(ts, data, metadata)
    coord.data = CoordinatorData(data, metadata)
    return data, metadata


async def _rv_release(coord, world, hhmm):
    """One release, including the background fill it may start."""
    _, metadata = await _rv_refresh(coord, world, hhmm)
    if coord._rain_tracker.fill_task is not None:
        with _serving(world):
            await coord._rain_tracker.fill_task
    return coord.data.data, metadata


def _rain_between(lo, hi, mm=1.0):
    lo_t = DAY_RV.replace(hour=int(lo[:2]), minute=int(lo[3:]))
    hi_t = DAY_RV.replace(hour=int(hi[:2]), minute=int(hi[3:]))
    return lambda t: mm if lo_t < t <= hi_t else 0.0


@pytest.mark.asyncio
async def test_rv_first_release_fills_the_hour_by_range_reads(make_coordinator) -> None:
    world = _RVWorld(_rain_between("13:30", "14:10"))
    coord = _rv_tracked(make_coordinator)

    data, _ = await _rv_release(coord, world, "14:00")

    events = data["rain_events"]
    assert events["history_complete"] is True
    assert events["steps"][:12] == [0.0] * 6 + [1.0] * 6
    event = events["events"][0]
    assert (event["status"], event["start"]) == ("ongoing", "2026-10-12T13:30:00+00:00")
    # One whole archive for the release itself, then 11 analyses by range.
    fills = [h for _, h in world.requests if h]
    assert len(fills) == 11 and all(h["Range"].startswith("bytes=0-") for h in fills)


@pytest.mark.asyncio
async def test_rv_next_release_fills_nothing_and_keeps_the_id(make_coordinator) -> None:
    world = _RVWorld(_rain_between("13:30", "15:00"))
    coord = _rv_tracked(make_coordinator)
    first, _ = await _rv_release(coord, world, "14:00")
    world.requests.clear()

    second, _ = await _rv_release(coord, world, "14:05")

    assert [h for _, h in world.requests] == [None]  # just the release itself
    assert second["rain_events"]["events"][0]["id"] == first["rain_events"]["events"][0]["id"]


@pytest.mark.asyncio
async def test_rv_failed_fill_stops_the_round_and_warns_once(make_coordinator, caplog) -> None:
    rain = _rain_between("13:30", "15:00")
    missing = {DAY_RV.replace(hour=13, minute=55)}
    world = _RVWorld(rain, missing=missing)
    coord = _rv_tracked(make_coordinator)

    data, _ = await _rv_release(coord, world, "14:00")
    # Newest first: 13:55 fails, and the older steps wait for the next round.
    assert data["rain_events"]["steps"][:11] == [None] * 11
    await _rv_release(coord, world, "14:05")

    warnings = [r for r in caplog.records if "to fill the rain_events history" in r.message]
    assert len(warnings) == 1
    assert "nothing is wrong with your setup" in warnings[0].message
    # The RV sensors themselves are unaffected.
    assert data["max_060"] == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_rv_unreadable_fill_asks_for_a_report(make_coordinator, caplog) -> None:
    """A file that arrived but does not hold the expected window is not DWD
    being late, so the warning must not say so."""
    world = _RVWorld(
        _rain_between("13:30", "15:00"), garbled={DAY_RV.replace(hour=13, minute=55)}
    )
    await _rv_release(_rv_tracked(make_coordinator), world, "14:00")

    warnings = [r for r in caplog.records if "to fill the rain_events history" in r.message]
    assert len(warnings) == 1
    assert "Could not read" in warnings[0].message
    assert "please report it" in warnings[0].message
    assert "nothing is wrong with your setup" not in warnings[0].message


@pytest.mark.asyncio
async def test_rv_fill_budget_running_out_is_not_a_failure(make_coordinator, caplog) -> None:
    world = _RVWorld(_rain_between("13:30", "15:00"), delay=0.05)
    coord = _rv_tracked(make_coordinator)
    with patch.object(rain_events_tracker, "RAIN_FILL_BUDGET", timedelta(seconds=0.12)):
        data, _ = await _rv_release(coord, world, "14:00")

    steps = data["rain_events"]["steps"][:11]
    assert 0 < steps.count(None) < 11  # filled some, newest first, then stopped
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not coord._rain_tracker.fill_latch.failing


@pytest.mark.asyncio
async def test_rv_fill_runs_after_the_refresh(make_coordinator) -> None:
    """Setup waits for the RV refresh; the fill must not hold it."""
    world = _RVWorld(_rain_between("13:30", "14:10"))
    coord = _rv_tracked(make_coordinator)

    data, _ = await _rv_refresh(coord, world, "14:00")

    assert data["rain_events"] is None  # nothing shown yet in this run
    assert data["max_060"] == pytest.approx(12.0)
    assert world.requests[0][1] is None  # the release itself came first
    # HA starts the background task eagerly, so its first range read may
    # already be out; but the refresh returned without waiting for it.
    assert not coord._rain_tracker.fill_task.done()

    with _serving(world):
        await coord._rain_tracker.fill_task
    assert coord.published == [coord.data.data["rain_events"]]
    assert coord.published[0]["history_complete"] is True


@pytest.mark.asyncio
async def test_rv_missed_release_keeps_the_previous_view_until_filled(make_coordinator) -> None:
    world = _RVWorld(_rain_between("13:30", "15:00"))
    coord = _rv_tracked(make_coordinator)
    await _rv_release(coord, world, "14:00")
    shown, _ = await _rv_release(coord, world, "14:05")
    assert coord._rain_tracker.fill_task.done()  # 14:05 needed no fill

    # 14:10 never arrived; 14:15 has a step to fill.
    data, _ = await _rv_refresh(coord, world, "14:15")
    assert data["rain_events"] is shown["rain_events"]

    with _serving(world):
        await coord._rain_tracker.fill_task
    assert coord.data.data["rain_events"]["base"] == "2026-10-12T14:15:00+00:00"
    assert coord.data.data["rain_events"]["history_complete"] is True


@pytest.mark.asyncio
async def test_rv_releases_queue_behind_a_running_fill(make_coordinator) -> None:
    """A release must never reach the tracker before an older one."""
    world = _RVWorld(_rain_between("13:30", "15:00"))
    coord = _rv_tracked(make_coordinator)
    await _rv_refresh(coord, world, "14:00")
    first = coord._rain_tracker.fill_task
    await _rv_refresh(coord, world, "14:05")
    assert coord._rain_tracker.fill_task is not first

    with _serving(world):
        await coord._rain_tracker.fill_task
    assert first.done()
    # Only the newest release published; the tracker saw both, in order.
    assert [v["base"] for v in coord.published] == ["2026-10-12T14:05:00+00:00"]
    assert coord._rain_tracker.state.base == DAY_RV.replace(hour=14, minute=5)
    assert coord.published[0]["events"][0]["id"] == "20261012t1400-0"


@pytest.mark.asyncio
async def test_rv_state_survives_a_restart_through_the_store(make_coordinator) -> None:
    world = _RVWorld(_rain_between("13:30", "15:00"))
    store = _FakeStore()
    first, _ = await _rv_release(_rv_tracked(make_coordinator, store), world, "14:00")

    restarted = _rv_tracked(make_coordinator, _FakeStore(store.data))
    world.requests.clear()
    after, _ = await _rv_release(restarted, world, "14:20")

    assert after["rain_events"]["events"][0]["id"] == first["rain_events"]["events"][0]["id"]
    # Only the 20 minutes of downtime are filled.
    assert len([h for _, h in world.requests if h]) == 3


@pytest.mark.asyncio
async def test_rv_saves_promptly_only_while_something_is_at_stake(make_coordinator) -> None:
    from custom_components.dwd_precipitation.rain_events_tracker import (
        RAIN_IDLE_SAVE_DELAY,
        RAIN_SAVE_DELAY,
    )

    store = _FakeStore()
    coord = _rv_tracked(make_coordinator, store)
    await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
    assert store.delays[-1] == RAIN_IDLE_SAVE_DELAY.total_seconds()

    await _rv_release(coord, _RVWorld(_rain_between("15:00", "15:10")), "14:05")
    assert store.delays[-1] == RAIN_SAVE_DELAY.total_seconds()


@pytest.mark.asyncio
async def test_rv_unreadable_store_starts_over(make_coordinator, caplog) -> None:
    coord = _rv_tracked(make_coordinator, _FakeStore({"measured_start": "not a time", "measured": [1.0]}))
    data, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
    assert data["rain_events"]["schema"] == 1
    assert any("Discarding the saved rain_events state" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_rv_store_that_cannot_be_loaded_starts_over(make_coordinator, caplog) -> None:
    """A store HA cannot load (another version, say) is discarded, not retried."""

    class _Unloadable(_FakeStore):
        async def async_load(self):
            raise NotImplementedError("stored version 2, expected 1")

    coord = _rv_tracked(make_coordinator, _Unloadable())
    data, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
    second, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:05")

    assert data["rain_events"]["schema"] == 1
    assert second["rain_events"]["schema"] == 1
    discarded = [r for r in caplog.records if "Discarding the saved" in r.message]
    assert len(discarded) == 1


@pytest.mark.asyncio
async def test_rv_tracker_failure_leaves_the_sensors_alone(make_coordinator, caplog) -> None:
    coord = _rv_tracked(make_coordinator)
    with patch.object(rain_events_tracker, "update_rain_events", side_effect=RuntimeError("bug")):
        data, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
    assert data["rain_events"] is None
    assert data["max_060"] == 0.0
    assert any("Could not update the Rain events sensor" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_rv_new_release_hook_does_not_raise(make_coordinator, caplog) -> None:
    """Metadata without the series fails the tracker, not the RV update."""
    coord = _rv_tracked(make_coordinator)
    data: dict = {}
    await coord._async_on_new_release(
        DAY_RV, data, {"rain_within_2h": products.ProductMetadata("RV", DAY_RV)}
    )
    assert data["rain_events"] is None
    assert any("Could not update the Rain events sensor" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_rv_fetching_a_past_release_leaves_the_tracker_alone(make_coordinator) -> None:
    """async_fetch_release (the totals' backfill path) has no side effects."""
    world = _RVWorld(_rain_between("13:30", "15:00"))
    coord = _rv_tracked(make_coordinator)
    with _serving(world):
        cdata = await coord.async_fetch_release(DAY_RV.replace(hour=14))

    assert cdata.data["max_060"] == pytest.approx(12.0)
    assert "rain_events" not in cdata.data
    assert coord._rain_tracker.state is None
    assert coord._rain_tracker.fill_task is None


@pytest.mark.asyncio
async def test_rv_threshold_option_sets_the_wet_step(make_coordinator) -> None:
    coord = _rv_tracked(make_coordinator, options={"rain_event_threshold": 0.6})
    data, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
    assert data["rain_events"]["wet_step_mm"] == 0.05
