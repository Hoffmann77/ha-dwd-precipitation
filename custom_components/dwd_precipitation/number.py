"""Number entities for the DWD Precipitation integration."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .warning import DEFAULT_LEAD_TIME, MAX_LEAD_TIME, MIN_LEAD_TIME, WarningSettings


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number platform."""
    async_add_entities([WarningLeadTimeNumber(entry, entry.runtime_data.warning)])


class WarningLeadTimeNumber(RestoreNumber):
    """How many minutes ahead the rain warning reports "soon"."""

    _attr_has_entity_name = True
    _attr_translation_key = "warning_lead_time"
    _attr_icon = "mdi:timer-alert-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = MIN_LEAD_TIME
    _attr_native_max_value = MAX_LEAD_TIME
    _attr_native_step = 5
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry: ConfigEntry, settings: WarningSettings) -> None:
        """Initialize the entity."""
        self._settings = settings
        self._attr_unique_id = f"{entry.entry_id}_warning_lead_time"
        self._attr_native_value = float(DEFAULT_LEAD_TIME)
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title or "DWD Precipitation",
        )

    async def async_added_to_hass(self) -> None:
        """Restore the last value the user set (default 60 min on first start)."""
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = last.native_value
        self._settings.set_lead_time(self._attr_native_value)

    async def async_set_native_value(self, value: float) -> None:
        """Store the new lead time and let the warning sensor re-evaluate."""
        self._attr_native_value = value
        self._settings.set_lead_time(value)
        self.async_write_ha_state()
