"""Rain warning sensor + lead-time number, set up through a real config entry."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.dwd_precipitation.coordinator import ProductMetadata

from .test_setup_entry import RV_DATA, RV_META, _entry, _patched_products, _state_for


def _rv_with_rain_in(minutes: int):
    """RV payload whose forecast series has 15 min of 2 mm/h starting in ``minutes``."""
    now = dt_util.utcnow()
    base = now - timedelta(minutes=2)  # analysis window ended 2 min ago
    samples = []
    for k in range(25):
        start = base + timedelta(minutes=5 * k - 5)
        end = base + timedelta(minutes=5 * k)
        wet = minutes <= (start - now).total_seconds() / 60 + 3 < minutes + 15
        samples.append({
            "lead": 5 * k,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "intensity": 2.0 if wet else 0.0,
        })
    meta = dict(RV_META)
    meta["rain_within_2h"] = ProductMetadata(
        source_product="RV", source_timestamp=base, samples=samples
    )
    return RV_DATA, meta


@pytest.mark.parametrize("expected_lingering_timers", [True])
@pytest.mark.asyncio
async def test_rain_warning_follows_forecast_and_lead_time(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    from custom_components.dwd_precipitation.products import RadvorRV
    from unittest.mock import AsyncMock, patch

    with _patched_products(), patch.object(
        RadvorRV, "_fetch_and_parse", new=AsyncMock(return_value=_rv_with_rain_in(40))
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    number = _state_for(hass, "_warning_lead_time", domain="number")
    assert number is not None
    assert float(number.state) == 60

    warning = _state_for(hass, "_rain_warning")
    assert warning.state == "soon"
    assert 35 <= warning.attributes["rain_starts_in_min"] <= 45
    assert warning.attributes["precipitation_type"] == "snow"  # HymecNG stub
    assert warning.attributes["lead_time_min"] == 60

    # Shorter lead time: the same rain is now too far away to warn about.
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": number.entity_id, "value": 20},
        blocking=True,
    )
    await hass.async_block_till_done()
    warning = _state_for(hass, "_rain_warning")
    assert warning.state == "dry"
    assert warning.attributes["lead_time_min"] == 20


@pytest.mark.parametrize("expected_lingering_timers", [True])
@pytest.mark.asyncio
async def test_neighbourhood_option_removes_area_sensors(hass: HomeAssistant) -> None:
    """Turning the option off drops the area sensors; the rain warning stays."""
    from homeassistant.helpers import entity_registry as er

    entry = _entry(hass)

    def _area_entities():
        return {
            e.unique_id.removeprefix(f"{entry.entry_id}_")
            for e in er.async_get(hass).entities.values()
            if e.config_entry_id == entry.entry_id
            and e.unique_id.endswith(("_area_precipitation_start", "_nearest_precipitation"))
        }

    with _patched_products():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert _area_entities() == {
            "radvor_rv_area_precipitation_start",
            "radvor_rv_nearest_precipitation",
        }

        # Options changes reload the entry.
        hass.config_entries.async_update_entry(
            entry, options={"neighbourhood_evaluation": False}
        )
        await hass.async_block_till_done()

        assert _area_entities() == set()
        assert _state_for(hass, "_rain_warning") is not None
        assert _state_for(hass, "_warning_lead_time", domain="number") is not None
