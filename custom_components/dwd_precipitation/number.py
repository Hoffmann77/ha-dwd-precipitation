"""Number platform: each rain warning's lead time, as a slider."""

from __future__ import annotations

from dataclasses import replace
from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_LEAD_TIME, LEAD_TIME_MAX, LEAD_TIME_MIN, LEAD_TIME_STEP
from .entity import RainWarningEntity
from .options import rain_warning_subentries

# A rain warning's lead time, one per rain-warning subentry, on the warning's
# device. Its unique-id suffix is "<subentry_id>_rain_warning_lead_time".
RAIN_WARNING_LEAD_TIME = NumberEntityDescription(
    key="rain_warning_lead_time",
    translation_key="rain_warning_lead_time",
    icon="mdi:timer-sand",
    entity_category=EntityCategory.CONFIG,
    native_min_value=LEAD_TIME_MIN,
    native_max_value=LEAD_TIME_MAX,
    native_step=LEAD_TIME_STEP,
    native_unit_of_measurement=UnitOfTime.MINUTES,
    mode=NumberMode.SLIDER,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the lead-time slider of every rain warning, added to its subentry."""
    coordinators = entry.runtime_data.coordinators
    for subentry in rain_warning_subentries(entry):
        async_add_entities(
            [
                RainWarningLeadTimeNumber(
                    coordinators["rv"],
                    RAIN_WARNING_LEAD_TIME,
                    subentry,
                    entry.runtime_data.rain_warnings[subentry.subentry_id],
                )
            ],
            config_subentry_id=subentry.subentry_id,
        )


class RainWarningLeadTimeNumber(RainWarningEntity, NumberEntity):
    """Lead time of a rain warning: how many minutes before the rain it turns on.

    The same value as in the warning's form. Moving the slider changes the
    running warning at once (the current forecast is judged again) and saves
    the value in the subentry, without reloading the entry.

    """

    @property
    def available(self) -> bool:
        """Return True: the setting can be changed while the forecast is out."""
        return True

    @property
    def native_value(self) -> float:
        """Return the warning's lead time in minutes."""
        return self._warning.rule.lead_time

    async def async_set_native_value(self, value: float) -> None:
        """Use ``value`` minutes as the lead time and save it in the subentry.

        The warning judges the current forecast again, so its two sensors
        follow at once. Saving the subentry calls the entry's update listener,
        which sees that only the lead time changed, and the warning already
        has it, so it does not reload.

        """
        lead_time = int(value)
        self._warning.set_rule(replace(self._warning.rule, lead_time=lead_time))
        self.coordinator.async_update_listeners()
        entry = self.coordinator.config_entry
        subentry = entry.subentries[self._subentry_id]
        self.hass.config_entries.async_update_subentry(
            entry, subentry, data={**subentry.data, CONF_LEAD_TIME: lead_time}
        )
