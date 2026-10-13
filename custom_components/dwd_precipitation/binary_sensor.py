"""Binary sensor entities for the DWD Precipitation integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import DwdCoordinatorEntity, DwdEntityDescriptionMixin


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
        access_fn=lambda d: d["rain_within_2h"],
        attrs_fn=lambda d: {"minutes_until": d.get("start_in"), "at": d.get("start_at")},
        # The full 25-point RV forecast series, always exposed (not behind the
        # extra-attributes option, unlike the other sensors' diagnostics):
        # automations and blueprints read it. Kept out of the recorder.
        metadata_attrs_fn=lambda meta: (
            {"forecast_5min": meta.samples} if meta.samples else {}
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinators = entry.runtime_data.coordinators

    async_add_entities(
        DwdBinarySensorEntity(
            coordinators[description.product_key],
            description,
        )
        for description in BINARY_SENSORS
    )


class DwdBinarySensorEntity(DwdCoordinatorEntity, BinarySensorEntity):
    """Binary sensor derived from an RV coordinator payload."""

    entity_description: DwdBinarySensorEntityDescription

    # The 5-minute forecast series would bloat the recorder history.
    _unrecorded_attributes = frozenset({"forecast_5min"})

    @property
    def is_on(self) -> bool | None:
        """Return True when precipitation is forecast within the horizon."""
        return self._value()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the forecast start and the 5-minute RV forecast."""
        return self._described_attributes()
