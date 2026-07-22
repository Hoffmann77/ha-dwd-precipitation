"""Binary sensor entities for the DWD Precipitation integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import DwdCoordinatorEntity


@dataclass(frozen=True, kw_only=True)
class DwdBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Provide a description for a DWD binary sensor."""

    product_key: str
    access_fn: Callable[[Any], Any]


BINARY_SENSORS = (
    DwdBinarySensorEntityDescription(
        key="rv_rain_within_2h",
        name="Rain expected next 2 hours",
        icon="mdi:weather-rainy",
        product_key="rv",
        access_fn=lambda d: d["rain_within_2h"],
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

    @property
    def is_on(self) -> bool | None:
        """Return True when precipitation is forecast within the horizon."""
        if self.coordinator.data is None:
            return None

        if (data := self.coordinator.data.data) is None:
            return None

        return self.entity_description.access_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the forecast start time so automations can read it directly."""
        if self.coordinator.data is None or self.coordinator.data.data is None:
            return {}

        data = self.coordinator.data.data
        start_at = data.get("start_at")
        return {
            "minutes_until": data.get("start_in"),
            "at": start_at.isoformat() if start_at is not None else None,
        }
