"""End-to-end integration test — entry setup → coordinators → sensor states.

Requires the ha-test dependency group (Linux only):
  pytest-homeassistant-custom-component imports homeassistant.runner which
  imports fcntl, a POSIX-only module not available on Windows.

Run with:
  uv run --group ha-test pytest tests/integration -v
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import async_get_platforms
from pytest import approx
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dwd_precipitation import PRODUCT_CLASSES
from custom_components.dwd_precipitation.const import CONF_DRY_STREAK_SOURCE, DOMAIN
from custom_components.dwd_precipitation.coordinator import ProductMetadata
from custom_components.dwd_precipitation.rain_events_tracker import RainEventsTracker
from custom_components.dwd_precipitation.products import (
    HymecNG,
    RadolanRW,
    RadolanRW10,
    RadolanSF,
    RadolanSFLastYesterday,
    RadvorRS,
    RadvorRV,
)


# Entity ids 2026.10.0 gave a new install, by key.
RELEASED_2026_10_0_IDS = {
    "radvor_rs_000": "precipitation_now",
    "radvor_rs_060": "precipitation_next_1h",
    "radvor_rs_120": "precipitation_next_1_2h",
    "radvor_peak_1h_120": "peak_hourly_precipitation_next_2h",
    "radvor_rv_max_intensity_060": "peak_intensity_next_1h",
    "radvor_rv_max_intensity_120": "peak_intensity_next_1_2h",
    "radvor_rv_precipitation_start": "precipitation_start",
    "radvor_rv_precipitation_end": "precipitation_end",
    "radvor_rv_precipitation_expected_120": "precipitation_expected",
    "hymecng_precipitation_type": "precipitation_type",
    "radolan_rw": "precipitation_last_1h",
    "radolan_sf": "precipitation_last_24h",
    "radolan_sf_yesterday": "precipitation_yesterday",
    "radolan_rw_total": "precipitation_total_hourly",
    "radolan_sf_yesterday_total": "precipitation_total_daily",
    "timespan_without_precipitation": "timespan_without_precipitation",
}

# What a new install gets for the entities renamed since.
RENAMED_SINCE_2026_10_0 = {
    "radvor_rs_000": "precipitation_last_60_min",
    "radvor_rs_060": "precipitation_next_60_min",
    "radvor_rs_120": "precipitation_next_60_120_min",
    "radvor_peak_1h_120": "peak_hourly_precipitation_next_120_min",
    "radvor_rv_max_intensity_060": "peak_intensity_next_60_min",
    "radvor_rv_max_intensity_120": "peak_intensity_next_60_120_min",
    "radolan_rw": "precipitation_previous_hour",
    "hymecng_precipitation_type": "precipitation_type_now",
    "radolan_rw_total": "precipitation_total",
}

# Added since 2026.10.0.
NEW_SINCE_2026_10_0 = {
    "radvor_rv_intensity_000": "precipitation_intensity_now",
    "radvor_rs_000_120": "precipitation_next_120_min",
    "radvor_rv_max_intensity_000_120": "peak_intensity_next_120_min",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("full_rolling_series", [False, True])
async def test_entry_setup_creates_sensors_with_correct_values(
    hass: HomeAssistant, full_rolling_series: bool
) -> None:
    """Full entry setup with mocked _fetch_and_parse; verify coordinators + sensor states.

    Run with the full-rolling-series option off and on: the peak-hour sensor
    reads RV or RS respectively, told apart here by giving the two different
    peaks (in reality they agree).
    """
    ts = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    rs_data = {
        "last_60": 1.5, "next_60": 2.0, "next_60_120": 0.5, "peak_1h": 6.5, "next_120": 2.5,
    }
    rs_meta = {
        "last_60": ProductMetadata("RS", ts, lead_time_minutes=0),
        "next_60": ProductMetadata("RS", ts, lead_time_minutes=60),
        "next_60_120": None,
        "peak_1h": ProductMetadata(
            source_product="RS",
            source_timestamp=ts,
            lead_time_minutes=75,
            data_start=ts + timedelta(minutes=15),
            data_end=ts + timedelta(minutes=75),
            rolling_1h=[{"lead": 75, "start": None, "end": None, "value": 6.5}],
        ),
        "next_120": None,
    }
    rw_meta = ProductMetadata("RW", datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc))
    rv_timing = ProductMetadata(source_product="RV", source_timestamp=ts)
    rv_data = {
        "intensity_000": 2.4,
        "amount_000": 0.2,
        "max_060": 48.0,
        "max_120": 12.0,
        "max_000_120": 48.0,
        "start_in": 0,
        "start_at": ts,
        "end_in": 30,
        "end_at": ts,
        "rain_within_2h": True,
        "peak_1h": 4.0,
    }
    rv_meta = {key: rv_timing for key in rv_data}
    rv_meta["intensity_000"] = rv_meta["amount_000"] = ProductMetadata(
        source_product="RV",
        source_timestamp=ts,
        lead_time_minutes=0,
        data_start=ts - timedelta(minutes=5),
        data_end=ts,
    )
    rv_meta["peak_1h"] = ProductMetadata(
        source_product="RV",
        source_timestamp=ts,
        lead_time_minutes=90,
        data_start=ts + timedelta(minutes=30),
        data_end=ts + timedelta(minutes=90),
        rolling_1h=[{"lead": 90, "start": None, "end": None, "value": 4.0}],
    )
    hymec_meta = ProductMetadata(source_product="HymecNG_top_view", source_timestamp=ts)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Home", "latitude": 51.05, "longitude": 13.73},
        options={"full_rolling_series": full_rolling_series},
    )
    entry.add_to_hass(hass)

    with (
        patch.object(
            RadvorRS,
            "_fetch_and_parse",
            new=AsyncMock(return_value=(rs_data, rs_meta)),
        ),
        patch.object(
            RadvorRV,
            "_fetch_and_parse",
            new=AsyncMock(return_value=(rv_data, rv_meta)),
        ),
        patch.object(
            HymecNG,
            "_fetch_and_parse",
            new=AsyncMock(
                return_value=(
                    {"precipitation_type": "snow"}, {"precipitation_type": hymec_meta}
                )
            ),
        ),
        patch.object(
            RadolanRW,
            "_fetch_and_parse",
            new=AsyncMock(return_value=({"amount": 3.2}, {"amount": rw_meta})),
        ),
        patch.object(
            RadolanSF,
            "_fetch_and_parse",
            new=AsyncMock(return_value=({"amount": 12.5}, {})),
        ),
        patch.object(
            RadolanSFLastYesterday,
            "_fetch_and_parse",
            new=AsyncMock(return_value=({"amount": 24.0}, {})),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinators = entry.runtime_data.coordinators
    assert set(coordinators) == {"rs", "rv", "hymecng", "rw", "sf", "sf_2350"}
    assert coordinators["rw"].data.data["amount"] == approx(3.2)
    assert coordinators["rs"].data.data == rs_data
    assert coordinators["rv"].data.data["max_060"] == approx(48.0)
    assert coordinators["hymecng"].data.data["precipitation_type"] == "snow"

    # Resolve entity_id via unique_id (avoids relying on HA's slug logic)
    ent_reg = er.async_get(hass)
    rw_entry = next(
        e
        for e in ent_reg.entities.values()
        if e.domain == "sensor" and e.unique_id.endswith("radolan_rw")
    )
    state = hass.states.get(rw_entry.entity_id)
    assert state is not None
    assert float(state.state) == approx(3.2)

    rs_000_entry = next(
        e
        for e in ent_reg.entities.values()
        if e.domain == "sensor" and e.unique_id.endswith("radvor_rs_000")
    )
    state = hass.states.get(rs_000_entry.entity_id)
    assert state is not None
    assert float(state.state) == approx(1.5)

    # The peak-hour sensor reads whichever product the option selects, and
    # carries that product's window and rolling-hour series.
    peak_entry = next(
        e
        for e in ent_reg.entities.values()
        if e.domain == "sensor" and e.unique_id.endswith("radvor_peak_1h_120")
    )
    state = hass.states.get(peak_entry.entity_id)
    assert state is not None
    peak, start, end = (
        (6.5, "12:15", "13:15") if full_rolling_series else (4.0, "12:30", "13:30")
    )
    assert float(state.state) == approx(peak)
    assert state.attributes["window_start"] == f"2025-06-01T{start}:00+00:00"
    assert state.attributes["window_end"] == f"2025-06-01T{end}:00+00:00"
    assert state.attributes["forecast_rolling_1h"][0]["value"] == approx(peak)

    # The current intensity is the analysis step as mm/h, with that 5-minute
    # window and its raw amount alongside.
    now_entry = next(
        e
        for e in ent_reg.entities.values()
        if e.domain == "sensor" and e.unique_id.endswith("radvor_rv_intensity_000")
    )
    state = hass.states.get(now_entry.entity_id)
    assert state is not None
    assert float(state.state) == approx(2.4)
    assert state.attributes["unit_of_measurement"] == "mm/h"
    assert state.attributes["amount_5min"] == approx(0.2)
    assert state.attributes["window_start"] == "2025-06-01T11:55:00+00:00"
    assert state.attributes["window_end"] == "2025-06-01T12:00:00+00:00"

    # Entity ids follow the English names. Keys are unchanged, so existing
    # installs keep the ids they already have; these are what new ones get.
    new_ids = {
        e.unique_id.removeprefix(f"{entry.entry_id}_"): e.entity_id.split(".", 1)[1]
        for e in ent_reg.entities.values()
        if e.config_entry_id == entry.entry_id
    }
    # No new id is one a released version gave another entity: on an old
    # install that entity still holds it, so recreating ids would collide.
    for key, entity_id in new_ids.items():
        slug = entity_id.removeprefix("mock_title_")
        owner = next(
            (k for k, s in RELEASED_2026_10_0_IDS.items() if s == slug), key
        )
        assert owner == key, f"{key} takes {slug}, which was {owner}'s"

    expected = {**RENAMED_SINCE_2026_10_0, **NEW_SINCE_2026_10_0}
    assert {key: new_ids[key] for key in expected} == {
        key: f"mock_title_{slug}" for key, slug in expected.items()
    }

    # The two 120-minute sensors: RS's two forecast hours added, RV's peak.
    assert float(_state_for(hass, "radvor_rs_000_120").state) == approx(2.5)
    assert float(_state_for(hass, "radvor_rv_max_intensity_000_120").state) == approx(48.0)

    # The peak-intensity sensor reports the extrapolated mm/h rate.
    max_060_entry = next(
        e
        for e in ent_reg.entities.values()
        if e.domain == "sensor" and e.unique_id.endswith("radvor_rv_max_intensity_060")
    )
    state = hass.states.get(max_060_entry.entity_id)
    assert state is not None
    assert float(state.state) == approx(48.0)

    # The new binary-sensor platform wires up and reflects rain_within_2h.
    rain_entry = next(
        e
        for e in ent_reg.entities.values()
        if e.domain == "binary_sensor"
        and e.unique_id.endswith("radvor_rv_precipitation_expected_120")
    )
    state = hass.states.get(rain_entry.entity_id)
    assert state is not None
    assert state.state == "on"

    # The HymecNG enum sensor reports the precipitation-type class label.
    hymec_entry = next(
        e
        for e in ent_reg.entities.values()
        if e.domain == "sensor" and e.unique_id.endswith("hymecng_precipitation_type")
    )
    state = hass.states.get(hymec_entry.entity_id)
    assert state is not None
    assert state.state == "snow"


RV_TS = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)

# The RV coordinator's payload is a dict keyed by entity sub-key, so a test that
# only wants "RV worked" still has to produce every key. Built here once
# rather than restated per test.
RV_DATA = {
    "intensity_000": 0.0,
    "amount_000": 0.0,
    "max_060": 48.0,
    "max_120": 12.0,
    "max_000_120": 48.0,
    "start_in": 0,
    "start_at": RV_TS,
    "end_in": 30,
    "end_at": RV_TS,
    "rain_within_2h": True,
    "peak_1h": 0.0,
}
RV_META = {
    key: ProductMetadata(source_product="RV", source_timestamp=RV_TS)
    for key in RV_DATA
}

# What each product's _fetch_and_parse returns when it is meant to succeed.
WORKING_PRODUCTS = {
    RadvorRS: (
        {"last_60": 1.5, "next_60": 2.0, "next_60_120": None, "peak_1h": 6.5, "next_120": None},
        {
            "last_60": None,
            "next_60": None,
            "next_60_120": None,
            "peak_1h": ProductMetadata(source_product="RS", source_timestamp=RV_TS),
            "next_120": None,
        },
    ),
    RadvorRV: (RV_DATA, RV_META),
    HymecNG: ({"precipitation_type": "snow"}, {}),
    RadolanRW: ({"amount": 3.2}, {}),
    RadolanRW10: ({"amount": 2.7}, {}),
    RadolanSF: ({"amount": 12.5}, {}),
    RadolanSFLastYesterday: ({"amount": 24.0}, {}),
}

# Adding a product to PRODUCT_CLASSES without a payload here would leave it
# unpatched -- these tests would then reach for the real DWD OpenData, or
# silently stop covering it. Fail at collection instead.
assert set(WORKING_PRODUCTS) == set(PRODUCT_CLASSES), (
    "every product in PRODUCT_CLASSES needs an entry in WORKING_PRODUCTS"
)


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a config entry added to hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Home", "latitude": 51.05, "longitude": 13.73},
        options={},
    )
    entry.add_to_hass(hass)

    return entry


@contextmanager
def _patched_products(**failures: Exception):
    """Patch every product's fetch, failing the ones named by PRODUCT_KEY."""
    with ExitStack() as stack:
        for cls, payload in WORKING_PRODUCTS.items():
            err = failures.get(cls.PRODUCT_KEY)
            mock = (
                AsyncMock(side_effect=err)
                if err is not None
                else AsyncMock(return_value=payload)
            )
            stack.enter_context(patch.object(cls, "_fetch_and_parse", new=mock))

        yield


def _state_for(hass: HomeAssistant, unique_id_suffix: str, domain: str = "sensor"):
    """Return the state of the entity whose unique id ends with the suffix."""
    entry = next(
        e
        for e in er.async_get(hass).entities.values()
        if e.domain == domain and e.unique_id.endswith(unique_id_suffix)
    )

    return hass.states.get(entry.entity_id)


@pytest.mark.parametrize("expected_lingering_timers", [True])
@pytest.mark.asyncio
async def test_one_failing_product_does_not_block_the_entry(
    hass: HomeAssistant,
    expected_lingering_timers: bool,
) -> None:
    """A dead product loses only its own entities; the rest of the entry loads."""
    entry = _entry(hass)

    with _patched_products(hymecng=OSError("DWD retired this product")):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED

    coordinators = entry.runtime_data.coordinators
    assert coordinators["hymecng"].last_update_success is False
    assert coordinators["rw"].last_update_success is True

    assert _state_for(hass, "hymecng_precipitation_type").state == "unavailable"
    assert float(_state_for(hass, "radolan_rw").state) == approx(3.2)


@pytest.mark.parametrize("expected_lingering_timers", [True])
@pytest.mark.asyncio
async def test_every_product_failing_leaves_the_entry_not_ready(
    hass: HomeAssistant,
    expected_lingering_timers: bool,
) -> None:
    """A total outage still puts the entry into HA's own setup-retry loop."""
    entry = _entry(hass)
    outage = {cls.PRODUCT_KEY: OSError("DWD OpenData is down") for cls in PRODUCT_CLASSES}

    with _patched_products(**outage):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.asyncio
async def test_local_time_product_is_scheduled_in_local_time(
    hass: HomeAssistant,
) -> None:
    """sf_2350's release grid is local wall-clock, so its tracker must be too.

    Registering it in UTC fetches it an offset's worth of hours late every day,
    which leaves the sensor past its staleness deadline in the meantime.
    """
    entry = _entry(hass)

    with (
        patch(
            "custom_components.dwd_precipitation.coordinator.async_track_time_change"
        ) as local_track,
        patch(
            "custom_components.dwd_precipitation.coordinator.async_track_utc_time_change"
        ) as utc_track,
        _patched_products(),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinators = entry.runtime_data.coordinators

    # Exactly one product uses local time, and it registers its own grid --
    # which carries this entry's fetch jitter, so read it off the coordinator
    # rather than restating a second here.
    assert local_track.call_count == 1
    assert local_track.call_args.kwargs == coordinators["sf_2350"].track_time_change_args[0]

    # Everything else stays on UTC.
    assert utc_track.call_count == sum(
        len(c.track_time_change_args)
        for c in coordinators.values()
        if not c.USE_LOCAL_TIME
    )


def _dry_streak_sensor(hass: HomeAssistant):
    """Return the live Timespan without precipitation entity object."""
    return next(
        entity
        for platform in async_get_platforms(hass, DOMAIN)
        for entity in platform.entities.values()
        if entity.unique_id.endswith("_timespan_without_precipitation")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("minor_version", "options", "bound_to"),
    [
        # A current entry without the key falls back to the default (RW).
        (2, {}, "rw"),
        (2, {CONF_DRY_STREAK_SOURCE: "rw"}, "rw"),
        (2, {CONF_DRY_STREAK_SOURCE: "rs"}, "rs"),
        # An entry from before the option keeps counting RS after the upgrade...
        (1, {}, "rs"),
        # ...unless it already carries a source, which the migration leaves alone.
        (1, {CONF_DRY_STREAK_SOURCE: "rw"}, "rw"),
        # A value no version ever wrote counts as the default, and the RW
        # coordinator it binds to is built for it.
        (2, {CONF_DRY_STREAK_SOURCE: "radar"}, "rw"),
    ],
)
async def test_dry_streak_sensor_binds_to_the_configured_source(
    hass: HomeAssistant, minor_version: int, options: dict, bound_to: str
) -> None:
    """The dry streak follows dry_streak_source; old entries are pinned to RS."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Home", "latitude": 51.05, "longitude": 13.73},
        options=options,
        version=1,
        minor_version=minor_version,
    )
    entry.add_to_hass(hass)

    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.minor_version == 2
    if minor_version == 1:
        assert entry.options[CONF_DRY_STREAK_SOURCE] == bound_to
    # An RW dry streak counts RW's 10-minute runs.
    key = "rw_10min" if bound_to == "rw" else bound_to
    assert _dry_streak_sensor(hass).coordinator is entry.runtime_data.coordinators[key]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "built"),
    [
        # Nothing uses the 10-minute runs: no coordinator, no requests.
        ({CONF_DRY_STREAK_SOURCE: "rs"}, False),
        # The option that once showed them as the last hour is gone; a value a
        # pre-release stored is ignored.
        ({CONF_DRY_STREAK_SOURCE: "rs", "rw_last_hour_mode": "sliding"}, False),
        # The dry streak needs them.
        ({CONF_DRY_STREAK_SOURCE: "rw"}, True),
    ],
)
async def test_sliding_rw_is_built_only_when_used(
    hass: HomeAssistant, options: dict, built: bool
) -> None:
    """rw_10min exists only for the dry streak that uses it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Home", "latitude": 51.05, "longitude": 13.73},
        options=options,
        minor_version=2,
    )
    entry.add_to_hass(hass)

    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinators = entry.runtime_data.coordinators
    assert ("rw_10min" in coordinators) is built
    # The previous hour and the hourly total are always RW's clock hours.
    total = next(
        entity
        for platform in async_get_platforms(hass, DOMAIN)
        for entity in platform.entities.values()
        if entity.unique_id.endswith("_radolan_rw_total")
    )
    assert total.coordinator is coordinators["rw"]
    assert float(_state_for(hass, "radolan_rw").state) == approx(3.2)


@pytest.mark.asyncio
async def test_entry_from_a_newer_major_version_is_not_migrated(
    hass: HomeAssistant,
) -> None:
    """A downgrade must not touch an entry it does not understand."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Home", "latitude": 51.05, "longitude": 13.73},
        options={},
        version=2,
        minor_version=1,
    )
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR
    assert entry.options == {}


@pytest.mark.asyncio
async def test_renamed_sensor_keeps_an_existing_entity_id(hass: HomeAssistant) -> None:
    """The renames change names, never the entity ids users already have.

    Up to 2026.10.0 RS was "Precipitation now" and RW "Precipitation last 1h".
    New installs get new ids for both; an existing one keeps the old ones.
    """
    entry = _entry(hass)
    ent_reg = er.async_get(hass)
    for key, object_id in (
        ("radvor_rs_000", "home_precipitation_now"),
        ("radolan_rw", "home_precipitation_last_1h"),
    ):
        ent_reg.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{entry.entry_id}_{key}",
            config_entry=entry,
            suggested_object_id=object_id,
        )

    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    rs = hass.states.get("sensor.home_precipitation_now")
    assert rs.attributes["friendly_name"].endswith("Precipitation last 60 min")
    rw = hass.states.get("sensor.home_precipitation_last_1h")
    assert rw.attributes["friendly_name"].endswith("Precipitation previous hour")


@pytest.mark.asyncio
async def test_removing_the_entry_deletes_its_rain_events_store(
    hass: HomeAssistant, hass_storage
) -> None:
    """Nothing the entry stored outlives it."""
    entry = _entry(hass)
    key = f"dwd_precipitation.{entry.entry_id}.rain_events"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {}}
    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert key not in hass_storage


@pytest.mark.asyncio
async def test_unloading_writes_the_rain_events_state(
    hass: HomeAssistant, hass_storage
) -> None:
    """An options change reloads the entry; the new tracker must read today's state."""
    from custom_components.dwd_precipitation.radar.rain_events import RainEventsState

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Home", "latitude": 51.05, "longitude": 13.73},
        options={"rain_events": True},
    )
    entry.add_to_hass(hass)
    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    tracker = entry.runtime_data.coordinators["rv"]._rain_tracker
    tracker.state = RainEventsState(base=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc))

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    stored = hass_storage[f"dwd_precipitation.{entry.entry_id}.rain_events"]["data"]
    assert stored["base"] == "2025-06-01T12:00:00+00:00"


RAIN_VIEW = {
    "schema": 1,
    "base": "2025-06-01T12:00:00+00:00",
    "wet_step_mm": 0.008,
    "steps_start": "2025-06-01T11:00:00+00:00",
    "steps": [0.0] * 36,
    "history_complete": True,
    "events": [{"id": "20250601t1200-0", "status": "upcoming"}],
    "last_ended": None,
}


@pytest.mark.asyncio
async def test_rain_events_sensor_with_the_option(hass: HomeAssistant) -> None:
    """With the option on, the view is its own sensor's attributes."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Home", "latitude": 51.05, "longitude": 13.73},
        options={"rain_events": True},
    )
    entry.add_to_hass(hass)

    tracker = AsyncMock(return_value=RAIN_VIEW)
    with _patched_products(), patch.object(RainEventsTracker, "async_track", new=tracker):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = _state_for(hass, "radvor_rv_rain_events")
    assert state.entity_id == "sensor.mock_title_rain_events"
    assert state.state == "upcoming"
    assert state.attributes["schema"] == 1
    assert state.attributes["events"] == RAIN_VIEW["events"]
    assert state.attributes["options"] == ["none", "upcoming", "ongoing"]
    assert entry.runtime_data.coordinators["rv"]._rain_tracker is not None

    flag = _state_for(hass, "radvor_rv_precipitation_expected_120", "binary_sensor")
    assert "rain_events" not in flag.attributes


@pytest.mark.asyncio
async def test_rain_events_off_runs_no_tracker_and_leaves_nothing(
    hass: HomeAssistant, hass_storage
) -> None:
    """Off (the default): no tracker, and what an earlier "on" left is removed."""
    entry = _entry(hass)
    unique_id = f"{entry.entry_id}_radvor_rv_rain_events"
    er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, unique_id, config_entry=entry
    )
    key = f"dwd_precipitation.{entry.entry_id}.rain_events"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {}}

    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.runtime_data.coordinators["rv"]._rain_tracker is None
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id) is None
    assert key not in hass_storage


@pytest.mark.asyncio
async def test_the_entrys_products_share_one_download_cache(hass: HomeAssistant) -> None:
    """rw/rw_10min and sf/sf_2350 can only share downloads through one cache."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Home", "latitude": 51.05, "longitude": 13.73},
        options={CONF_DRY_STREAK_SOURCE: "rw"},
    )
    entry.add_to_hass(hass)
    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinators = entry.runtime_data.coordinators
    assert "rw_10min" in coordinators
    caches = {id(c.download_cache) for c in coordinators.values()}
    assert len(caches) == 1 and None not in {c.download_cache for c in coordinators.values()}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("threshold", "moved"),
    [
        (2.0, True),    # RW's 3.2 mm in the last hour: it rained while HA was down
        (30.0, False),  # neither RW (3.2) nor SF (12.5) reaches it
    ],
)
async def test_restored_dry_streak_is_corrected_for_rain_during_downtime(
    hass: HomeAssistant, freezer, threshold: float, moved: bool
) -> None:
    """The anchor restored from days ago moves forward if RW/SF saw rain since."""
    from homeassistant.core import State
    from pytest_homeassistant_custom_component.common import (
        mock_restore_cache_with_extra_data,
    )

    now = datetime(2025, 6, 1, 12, 35, tzinfo=timezone.utc)
    freezer.move_to(now)
    restored = datetime(2025, 5, 28, 8, 0, tzinfo=timezone.utc)
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State("sensor.mock_title_timespan_without_precipitation", "4.2"),
                {"dry_since": restored.isoformat()},
            )
        ],
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Home", "latitude": 51.05, "longitude": 13.73},
        # RS counts (1.5 mm, below both thresholds), so only the correction
        # can move the anchor.
        options={CONF_DRY_STREAK_SOURCE: "rs", "precipitation_reset_threshold": threshold},
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    anchor = _dry_streak_sensor(hass)._dry_since
    assert anchor == (now if moved else restored)
