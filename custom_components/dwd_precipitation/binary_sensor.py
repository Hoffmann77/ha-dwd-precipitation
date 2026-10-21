"""Binary sensor entities for the DWD Precipitation integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.helpers.entity import EntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import DwdCoordinatorEntity, DwdEntityDescriptionMixin, RainWarningEntity
from .options import rain_warning_subentries


@dataclass(frozen=True, kw_only=True)
class DwdBinarySensorEntityDescription(
    BinarySensorEntityDescription, DwdEntityDescriptionMixin
):
    """Provide a description for a DWD binary sensor."""


BINARY_SENSORS = (
    DwdBinarySensorEntityDescription(
        key="radvor_rv_precipitation_expected_120",
        translation_key="precipitation_expected",
        icon="mdi:weather-rainy",
        product_key="rv",
        sub_key="rain_within_2h",
        attrs_fn=lambda d: {"minutes_until": d.get("start_in"), "at": d.get("start_at")},
        # The full 25-point RV forecast series, always exposed (not behind the
        # extra-attributes option, unlike the other sensors' diagnostics):
        # automations and blueprints read it. Kept out of the recorder.
        metadata_attrs_fn=lambda meta: (
            {"forecast_5min": meta.samples} if meta.samples else {}
        ),
    ),
)

# A rain warning's on/off entity, one per rain-warning subentry: on while it
# rains or is about to, by that warning's rules. Its unique-id suffix is
# "<subentry_id>_rain_warning".
RAIN_WARNING_BINARY_SENSOR = EntityDescription(
    key="rain_warning",
    translation_key="rain_warning",
    icon="mdi:umbrella",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor platform for one config entry.

    Home Assistant calls this once per entry after the integration's own setup.
    It creates "Precipitation expected" on the entry's RV coordinator (the
    5-minute RADVOR forecast), which setup has already refreshed once, and the
    on/off entity of every rain warning, added to its subentry.

    """
    coordinators = entry.runtime_data.coordinators

    async_add_entities(
        DwdBinarySensorEntity(
            coordinators[description.product_key],
            description,
        )
        for description in BINARY_SENSORS
    )
    for subentry in rain_warning_subentries(entry):
        async_add_entities(
            [
                RainWarningBinarySensor(
                    coordinators["rv"],
                    RAIN_WARNING_BINARY_SENSOR,
                    subentry,
                    entry.runtime_data.rain_warnings[subentry.subentry_id],
                )
            ],
            config_subentry_id=subentry.subentry_id,
        )


class DwdBinarySensorEntity(DwdCoordinatorEntity, BinarySensorEntity):
    """Binary sensor derived from an RV coordinator payload."""

    entity_description: DwdBinarySensorEntityDescription

    # The 5-minute forecast series would bloat the recorder history.
    _unrecorded_attributes = frozenset({"forecast_5min"})

    @property
    def is_on(self) -> bool | None:
        """Return True when precipitation is forecast within the horizon.

        That is RV's ``rain_within_2h``: rain is falling now or forecast within
        the next two hours, above the configured precipitation threshold. False
        means dry for the whole forecast; None while the coordinator has no
        data yet.

        """
        return self._value()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return when the rain starts, and the 5-minute forecast series.

        ``minutes_until`` and ``at`` say when precipitation begins (None when
        it is not forecast). ``forecast_5min`` is RV's whole 25-step series,
        one point per 5 minutes with its window, amount and rate. Automations
        and blueprints read it, so it is always exposed, unlike the other
        sensors' diagnostics, and it is kept out of the recorder so it does not
        bloat the history.

        """
        return self._described_attributes()


class RainWarningBinarySensor(RainWarningEntity, BinarySensorEntity):
    """Rain warning: on while it rains or is about to (rain or soon)."""

    @property
    def is_on(self) -> bool | None:
        """Return True while the warning is rain or soon, False while dry.

        None (unknown) while there is no rain-events view to judge. The details
        (which event, when, how much) are on the warning's status sensor.

        """
        verdict = self._verdict()
        return None if verdict is None else verdict.is_on
