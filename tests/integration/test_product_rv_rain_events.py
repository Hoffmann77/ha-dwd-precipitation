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
from custom_components.dwd_precipitation.rain_events_tracker import (
    RAIN_EVENTS_STORE_VERSION,
    rain_events_store_key,
)

from tests.factories.radvor import RangeServer, make_radvor_tar
from tests.integration.product_helpers import rv_what


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

    def read(self, fileobj, _lat, _lon, **_kw):
        stamp, lead = fileobj.getvalue().decode().split(":")
        base = DAY_RV.replace(hour=int(stamp[:2]), minute=int(stamp[2:]))
        step_end = base + timedelta(minutes=int(lead))
        if base in self.garbled:
            base -= timedelta(minutes=5)
        return np.float32(self.rain(step_end)), rv_what(base, int(lead))


DAY_RV = datetime(2026, 10, 12, tzinfo=timezone.utc)


@pytest.fixture
async def rv_tracked(make_coordinator):
    """Return a factory: an RV coordinator with the rain-events option on.

    Its constructor builds the tracker, which keeps its state in the entry's
    real Store (hass_storage). Every view it publishes lands in
    ``coord.published``. Teardown saves each tracker, as unloading the entry
    does, which also ends the delayed save the Store has pending.
    """
    built = []

    def _make(options=None, *, entry=None):
        coord = make_coordinator(
            RadvorRV, {"rain_events": True, **(options or {})}, entry=entry
        )
        coord.published = []
        coord.async_add_listener(
            lambda: coord.published.append(coord.data.data["rain_events"])
        )
        built.append(coord)
        return coord

    yield _make
    for coord in built:
        await coord._rain_tracker.async_save()


def _stored(hass_storage, entry, data, version=RAIN_EVENTS_STORE_VERSION) -> None:
    """Put ``data`` where the entry's rain-events Store reads it."""
    key = rain_events_store_key(entry.entry_id)
    hass_storage[key] = {"version": version, "minor_version": 1, "key": key, "data": data}


@contextmanager
def _serving(world):
    with (
        patch.object(products, "async_get", side_effect=world.get),
        patch.object(products, "read_odim_composite_at", side_effect=world.read),
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
async def test_rv_first_release_fills_the_hour_by_range_reads(rv_tracked) -> None:
    world = _RVWorld(_rain_between("13:30", "14:10"))
    coord = rv_tracked()

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
async def test_rv_next_release_fills_nothing_and_keeps_the_id(rv_tracked) -> None:
    world = _RVWorld(_rain_between("13:30", "15:00"))
    coord = rv_tracked()
    first, _ = await _rv_release(coord, world, "14:00")
    world.requests.clear()

    second, _ = await _rv_release(coord, world, "14:05")

    assert [h for _, h in world.requests] == [None]  # just the release itself
    assert second["rain_events"]["events"][0]["id"] == first["rain_events"]["events"][0]["id"]


@pytest.mark.asyncio
async def test_rv_failed_fill_stops_the_round_and_warns_once(rv_tracked, caplog) -> None:
    rain = _rain_between("13:30", "15:00")
    missing = {DAY_RV.replace(hour=13, minute=55)}
    world = _RVWorld(rain, missing=missing)
    coord = rv_tracked()

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
async def test_rv_unreadable_fill_asks_for_a_report(rv_tracked, caplog) -> None:
    """A file that arrived but does not hold the expected window is not DWD
    being late, so the warning must not say so."""
    world = _RVWorld(
        _rain_between("13:30", "15:00"), garbled={DAY_RV.replace(hour=13, minute=55)}
    )
    await _rv_release(rv_tracked(), world, "14:00")

    warnings = [r for r in caplog.records if "to fill the rain_events history" in r.message]
    assert len(warnings) == 1
    assert "Could not read" in warnings[0].message
    assert "please report it" in warnings[0].message
    assert "nothing is wrong with your setup" not in warnings[0].message


@pytest.mark.asyncio
async def test_rv_fill_budget_running_out_is_not_a_failure(rv_tracked, caplog) -> None:
    world = _RVWorld(_rain_between("13:30", "15:00"), delay=0.05)
    coord = rv_tracked()
    with patch.object(rain_events_tracker, "RAIN_FILL_BUDGET", timedelta(seconds=0.12)):
        data, _ = await _rv_release(coord, world, "14:00")

    steps = data["rain_events"]["steps"][:11]
    assert 0 < steps.count(None) < 11  # filled some, newest first, then stopped
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not coord._rain_tracker.fill_latch.failing


@pytest.mark.asyncio
async def test_rv_fill_runs_after_the_refresh(rv_tracked) -> None:
    """Setup waits for the RV refresh; the fill must not hold it."""
    world = _RVWorld(_rain_between("13:30", "14:10"))
    coord = rv_tracked()

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
async def test_rv_missed_release_keeps_the_previous_view_until_filled(rv_tracked) -> None:
    world = _RVWorld(_rain_between("13:30", "15:00"))
    coord = rv_tracked()
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
async def test_rv_releases_queue_behind_a_running_fill(rv_tracked) -> None:
    """A release must never reach the tracker before an older one."""
    world = _RVWorld(_rain_between("13:30", "15:00"))
    coord = rv_tracked()
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
async def test_rv_state_survives_a_restart_through_the_store(rv_tracked, make_entry) -> None:
    world = _RVWorld(_rain_between("13:30", "15:00"))
    entry = make_entry({"rain_events": True})
    before = rv_tracked(entry=entry)
    first, _ = await _rv_release(before, world, "14:00")
    await before._rain_tracker.async_save()  # what unloading the entry does

    restarted = rv_tracked(entry=entry)
    world.requests.clear()
    after, _ = await _rv_release(restarted, world, "14:20")

    assert after["rain_events"]["events"][0]["id"] == first["rain_events"]["events"][0]["id"]
    # Only the 20 minutes of downtime are filled.
    assert len([h for _, h in world.requests if h]) == 3


@pytest.mark.asyncio
async def test_rv_saves_promptly_only_while_something_is_at_stake(rv_tracked) -> None:
    from custom_components.dwd_precipitation.rain_events_tracker import (
        RAIN_IDLE_SAVE_DELAY,
        RAIN_SAVE_DELAY,
    )

    coord = rv_tracked()
    store = coord._rain_tracker.store
    with patch.object(store, "async_delay_save", wraps=store.async_delay_save) as save:
        await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
        assert save.call_args.args[1] == RAIN_IDLE_SAVE_DELAY.total_seconds()

        await _rv_release(coord, _RVWorld(_rain_between("15:00", "15:10")), "14:05")
        assert save.call_args.args[1] == RAIN_SAVE_DELAY.total_seconds()


@pytest.mark.asyncio
async def test_rv_unreadable_store_starts_over(rv_tracked, make_entry, hass_storage, caplog) -> None:
    entry = make_entry({"rain_events": True})
    _stored(hass_storage, entry, {"measured_start": "not a time", "measured": [1.0]})
    coord = rv_tracked(entry=entry)
    data, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
    assert data["rain_events"]["schema"] == 1
    assert any("Discarding the saved rain_events state" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_rv_store_that_cannot_be_loaded_starts_over(rv_tracked, make_entry, hass_storage, caplog) -> None:
    """A store HA cannot load (a newer version, say) is discarded, not retried."""
    entry = make_entry({"rain_events": True})
    _stored(hass_storage, entry, {}, version=RAIN_EVENTS_STORE_VERSION + 1)
    coord = rv_tracked(entry=entry)
    data, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
    second, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:05")

    assert data["rain_events"]["schema"] == 1
    assert second["rain_events"]["schema"] == 1
    discarded = [r for r in caplog.records if "Discarding the saved" in r.message]
    assert len(discarded) == 1


@pytest.mark.asyncio
async def test_rv_tracker_failure_leaves_the_sensors_alone(rv_tracked, caplog) -> None:
    coord = rv_tracked()
    with patch.object(rain_events_tracker, "update_rain_events", side_effect=RuntimeError("bug")):
        data, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
    assert data["rain_events"] is None
    assert data["max_060"] == 0.0
    assert any("Could not update the Rain events sensor" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_rv_new_release_hook_does_not_raise(rv_tracked, caplog) -> None:
    """Metadata without the series fails the tracker, not the RV update."""
    coord = rv_tracked()
    data: dict = {}
    await coord._async_on_new_release(
        DAY_RV, data, {"rain_within_2h": products.ProductMetadata("RV", DAY_RV)}
    )
    assert data["rain_events"] is None
    assert any("Could not update the Rain events sensor" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_rv_fetching_a_past_release_leaves_the_tracker_alone(rv_tracked) -> None:
    """async_fetch_release (the totals' backfill path) has no side effects."""
    world = _RVWorld(_rain_between("13:30", "15:00"))
    coord = rv_tracked()
    with _serving(world):
        cdata = await coord.async_fetch_release(DAY_RV.replace(hour=14))

    assert cdata.data["max_060"] == pytest.approx(12.0)
    assert "rain_events" not in cdata.data
    assert coord._rain_tracker.state is None
    assert coord._rain_tracker.fill_task is None


@pytest.mark.asyncio
async def test_rv_threshold_option_sets_the_wet_step(rv_tracked) -> None:
    coord = rv_tracked({"rain_event_threshold": 0.6})
    data, _ = await _rv_release(coord, _RVWorld(lambda _t: 0.0), "14:00")
    assert data["rain_events"]["wet_step_mm"] == 0.05


# ---------------------------------------------------------------------------
# Precipitation types (HymecNG)
# ---------------------------------------------------------------------------


class _Types:
    """Serves the HymecNG type of past releases, as the tracker fetches them."""

    def __init__(self, label="rain", missing=()) -> None:
        self.label = label
        self.missing = set(missing)
        self.requests: list[datetime] = []

    async def fetch(self, release):
        self.requests.append(release)
        if release in self.missing:
            import aiohttp

            raise aiohttp.ClientError("404")
        return self.label


@pytest.mark.asyncio
async def test_rv_fill_also_fetches_the_type_of_each_wet_step(rv_tracked) -> None:
    world = _RVWorld(_rain_between("13:30", "14:10"))
    types = _Types("snow")
    coord = rv_tracked()
    coord._rain_tracker.attach_types(types.fetch)

    data, _ = await _rv_release(coord, world, "14:00")

    # The wet steps before the release, newest first; not the dry ones, and
    # not 14:00, which HymecNG fetches itself.
    assert types.requests == [DAY_RV.replace(hour=13, minute=m) for m in (55, 50, 45, 40, 35)]
    event = data["rain_events"]["events"][0]
    assert event["observed"]["types"] == {"snow": 5}
    assert event["type"] == "snow"

    # HymecNG did not hand over 14:00 here, so the next release fetches it.
    types.requests.clear()
    await _rv_release(coord, world, "14:05")
    assert types.requests == [DAY_RV.replace(hour=14)]
    # Once HymecNG hands over its releases, nothing is left to fetch.
    types.requests.clear()
    for minute in (5, 10):
        await coord._rain_tracker.async_record_type(DAY_RV.replace(hour=14, minute=minute), "snow")
    await _rv_release(coord, world, "14:10")
    assert types.requests == []


@pytest.mark.asyncio
async def test_rv_type_recorded_by_hymecng_needs_no_fetch(rv_tracked) -> None:
    world = _RVWorld(_rain_between("13:30", "14:10"))
    types = _Types()
    coord = rv_tracked()
    tracker = coord._rain_tracker
    tracker.attach_types(types.fetch)
    await _rv_release(coord, world, "14:00")
    types.requests.clear()

    # HymecNG adopted 14:00 and adopts 14:05 before RV does.
    await tracker.async_record_type(DAY_RV.replace(hour=14), "rain")
    await tracker.async_record_type(DAY_RV.replace(hour=14, minute=5), "graupel")
    data, _ = await _rv_release(coord, world, "14:05")

    assert types.requests == []
    assert data["rain_events"]["events"][0]["type"] == "graupel"


@pytest.mark.asyncio
async def test_rv_failed_type_fill_warns_once_and_keeps_the_amounts(rv_tracked, caplog) -> None:
    world = _RVWorld(_rain_between("13:30", "14:10"))
    types = _Types(missing={DAY_RV.replace(hour=13, minute=50)})
    coord = rv_tracked()
    coord._rain_tracker.attach_types(types.fetch)

    data, _ = await _rv_release(coord, world, "14:00")
    await _rv_release(coord, world, "14:05")

    event = data["rain_events"]["events"][0]
    assert event["observed"]["mm"] == 6.0  # every analysis was filled
    assert event["observed"]["types"] == {"rain": 1}  # 13:55, then 13:50 failed
    warnings = [r for r in caplog.records if "DWD HymecNG release" in r.message]
    assert len(warnings) == 1
    assert "precipitation type stays unknown" in warnings[0].message
    assert not coord._rain_tracker.fill_latch.failing


@pytest.mark.asyncio
async def test_rv_without_hymecng_fetches_no_types(rv_tracked) -> None:
    world = _RVWorld(_rain_between("13:30", "14:10"))
    coord = rv_tracked()

    data, _ = await _rv_release(coord, world, "14:00")
    second, _ = await _rv_release(coord, world, "14:05")

    assert second["rain_events"]["events"][0]["type"] is None
    assert coord._rain_tracker.fill_task.done()


@pytest.mark.asyncio
async def test_rv_type_before_the_first_release_loads_the_store_once(
    rv_tracked, make_entry, hass_storage
) -> None:
    """HymecNG and RV both reach the state at setup; neither may lose the other."""
    world = _RVWorld(_rain_between("13:30", "15:00"))
    entry = make_entry({"rain_events": True})
    before = rv_tracked(entry=entry)
    first, _ = await _rv_release(before, world, "14:00")
    await before._rain_tracker.async_save()

    restarted = rv_tracked(entry=entry)
    tracker = restarted._rain_tracker
    at = DAY_RV.replace(hour=14, minute=5)
    await asyncio.gather(
        tracker.async_record_type(at, "hail"),
        _rv_release(restarted, world, "14:05"),
    )

    assert tracker.state.types == {at: "hail"}
    view = restarted.data.data["rain_events"]
    assert view["events"][0]["id"] == first["rain_events"]["events"][0]["id"]
