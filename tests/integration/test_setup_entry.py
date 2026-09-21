"""End-to-end integration test — entry setup → coordinators → sensor states.

Requires the ha-test dependency group (Linux only):
  pytest-homeassistant-custom-component imports homeassistant.runner which
  imports fcntl, a POSIX-only module not available on Windows.

Run with:
  uv run --group ha-test pytest tests/integration -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest import approx
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dwd_precipitation.const import DOMAIN
from custom_components.dwd_precipitation.coordinator import ProductMetadata
from custom_components.dwd_precipitation.products import (
    HymecNG,
    RadolanRW,
    RadolanSF,
    RadolanSFLastYesterday,
    RadvorRS,
    RadvorRV,
)


@pytest.mark.asyncio
async def test_entry_setup_creates_sensors_with_correct_values(
    hass: HomeAssistant,
) -> None:
    """Full entry setup with mocked _fetch_and_parse; verify coordinators + sensor states."""
    ts = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    rs_data = [1.5, 2.0, None]
    rs_meta = [
        {"product": "ACRR", "datetime": ts, "lead_time_minutes": 0},
        {"product": "ACRR", "datetime": ts, "lead_time_minutes": 60},
        {},
    ]
    rw_meta = {"producttype": "RW", "datetime": datetime(2025, 6, 1, 12, 50)}
    rv_timing = ProductMetadata(source_product="RV", source_timestamp=ts)
    rv_data = {
        "max_060": 48.0,
        "max_120": 12.0,
        "start_in": 0,
        "start_at": ts,
        "end_in": 30,
        "end_at": ts,
        "rain_within_2h": True,
    }
    rv_meta = {key: rv_timing for key in rv_data}
    hymec_meta = ProductMetadata(source_product="HymecNG_top_view", source_timestamp=ts)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Home", "latitude": 51.05, "longitude": 13.73},
        options={},
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
            new=AsyncMock(return_value=("snow", hymec_meta)),
        ),
        patch.object(
            RadolanRW,
            "_fetch_and_parse",
            new=AsyncMock(return_value=(3.2, rw_meta)),
        ),
        patch.object(
            RadolanSF,
            "_fetch_and_parse",
            new=AsyncMock(return_value=(12.5, {})),
        ),
        patch.object(
            RadolanSFLastYesterday,
            "_fetch_and_parse",
            new=AsyncMock(return_value=(24.0, {})),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinators = entry.runtime_data.coordinators
    assert set(coordinators) == {"rs", "rv", "hymecng", "rw", "sf", "sf_2350"}
    assert coordinators["rw"].data.data == approx(3.2)
    assert coordinators["rs"].data.data == [1.5, 2.0, None]
    assert coordinators["rv"].data.data["max_060"] == approx(48.0)
    assert coordinators["hymecng"].data.data == "snow"

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


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a config entry added to hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Home", "latitude": 51.05, "longitude": 13.73},
        options={},
    )
    entry.add_to_hass(hass)

    return entry


@pytest.mark.parametrize("expected_lingering_timers", [True])
@pytest.mark.asyncio
async def test_one_failing_product_does_not_block_the_entry(
    hass: HomeAssistant,
    expected_lingering_timers: bool,
) -> None:
    """A dead product loses only its own entities; the rest of the entry loads."""
    entry = _entry(hass)

    ts = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    rv_timing = ProductMetadata(source_product="RV", source_timestamp=ts)
    rv_data = {
        "max_060": 48.0,
        "max_120": 12.0,
        "start_in": 0,
        "start_at": ts,
        "end_in": 30,
        "end_at": ts,
        "rain_within_2h": True,
    }

    with (
        patch.object(
            RadvorRS,
            "_fetch_and_parse",
            new=AsyncMock(return_value=([1.5, 2.0, None], [{}, {}, {}])),
        ),
        patch.object(
            RadvorRV,
            "_fetch_and_parse",
            new=AsyncMock(return_value=(rv_data, {k: rv_timing for k in rv_data})),
        ),
        patch.object(
            HymecNG,
            "_fetch_and_parse",
            new=AsyncMock(side_effect=OSError("DWD retired this product")),
        ),
        patch.object(
            RadolanRW, "_fetch_and_parse", new=AsyncMock(return_value=(3.2, {}))
        ),
        patch.object(
            RadolanSF, "_fetch_and_parse", new=AsyncMock(return_value=(12.5, {}))
        ),
        patch.object(
            RadolanSFLastYesterday,
            "_fetch_and_parse",
            new=AsyncMock(return_value=(24.0, {})),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED

    coordinators = entry.runtime_data.coordinators
    assert coordinators["hymecng"].last_update_success is False
    assert coordinators["rw"].last_update_success is True

    ent_reg = er.async_get(hass)
    hymec_entry = next(
        e
        for e in ent_reg.entities.values()
        if e.domain == "sensor" and e.unique_id.endswith("hymecng_precipitation_type")
    )
    assert hass.states.get(hymec_entry.entity_id).state == "unavailable"

    rw_entry = next(
        e
        for e in ent_reg.entities.values()
        if e.domain == "sensor" and e.unique_id.endswith("radolan_rw")
    )
    assert float(hass.states.get(rw_entry.entity_id).state) == approx(3.2)


@pytest.mark.parametrize("expected_lingering_timers", [True])
@pytest.mark.asyncio
async def test_every_product_failing_leaves_the_entry_not_ready(
    hass: HomeAssistant,
    expected_lingering_timers: bool,
) -> None:
    """A total outage still puts the entry into HA's own setup-retry loop."""
    entry = _entry(hass)
    boom = AsyncMock(side_effect=OSError("DWD OpenData is down"))

    with (
        patch.object(RadvorRS, "_fetch_and_parse", new=boom),
        patch.object(RadvorRV, "_fetch_and_parse", new=boom),
        patch.object(HymecNG, "_fetch_and_parse", new=boom),
        patch.object(RadolanRW, "_fetch_and_parse", new=boom),
        patch.object(RadolanSF, "_fetch_and_parse", new=boom),
        patch.object(RadolanSFLastYesterday, "_fetch_and_parse", new=boom),
    ):
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
    ts = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    rv_timing = ProductMetadata(source_product="RV", source_timestamp=ts)
    rv_data = {
        "max_060": 48.0,
        "max_120": 12.0,
        "start_in": 0,
        "start_at": ts,
        "end_in": 30,
        "end_at": ts,
        "rain_within_2h": True,
    }

    with (
        patch(
            "custom_components.dwd_precipitation.coordinator.async_track_time_change"
        ) as local_track,
        patch(
            "custom_components.dwd_precipitation.coordinator.async_track_utc_time_change"
        ) as utc_track,
        patch.object(
            RadvorRS,
            "_fetch_and_parse",
            new=AsyncMock(return_value=([1.5, 2.0, None], [{}, {}, {}])),
        ),
        patch.object(
            RadvorRV,
            "_fetch_and_parse",
            new=AsyncMock(return_value=(rv_data, {k: rv_timing for k in rv_data})),
        ),
        patch.object(
            HymecNG, "_fetch_and_parse", new=AsyncMock(return_value=("snow", {}))
        ),
        patch.object(
            RadolanRW, "_fetch_and_parse", new=AsyncMock(return_value=(3.2, {}))
        ),
        patch.object(
            RadolanSF, "_fetch_and_parse", new=AsyncMock(return_value=(12.5, {}))
        ),
        patch.object(
            RadolanSFLastYesterday,
            "_fetch_and_parse",
            new=AsyncMock(return_value=(24.0, {})),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinators = entry.runtime_data.coordinators

    # Exactly one product uses local time, and it registers its own grid --
    # which carries this entry's fetch jitter, so read the expected kwargs off
    # the coordinator rather than restating a second here.
    assert local_track.call_count == 1
    assert (
        local_track.call_args.kwargs
        == coordinators["sf_2350"].track_time_change_args[0]
    )

    # Everything else stays on UTC. track_time_change_args is a cached_property,
    # so it has to be read off an instance -- off the class it is the descriptor.
    assert utc_track.call_count == sum(
        len(c.track_time_change_args)
        for c in coordinators.values()
        if not c.USE_LOCAL_TIME
    )
