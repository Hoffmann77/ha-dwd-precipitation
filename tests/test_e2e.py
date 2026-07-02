"""End-to-end integration test — entry setup → coordinators → sensor states.

Requires the ha-test dependency group (Linux only):
  pytest-homeassistant-custom-component imports homeassistant.runner which
  imports fcntl, a POSIX-only module not available on Windows.

Run with:
  uv run --group ha-test pytest tests/test_e2e.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest import approx
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dwd_precipitation.const import DOMAIN
from custom_components.dwd_precipitation.products import (
    RadolanRW,
    RadolanSF,
    RadolanSFLastYesterday,
    RadvorRS,
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
    assert set(coordinators) == {"rs", "rw", "sf", "sf_2350"}
    assert coordinators["rw"].data.data == approx(3.2)
    assert coordinators["rs"].data.data == [1.5, 2.0, None]

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
