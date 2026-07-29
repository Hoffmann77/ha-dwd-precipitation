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

from .const import CONF_EXTRA_ATTRIBUTES
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

    # The 25-point 5-minute forecast series would bloat the recorder history.
    _unrecorded_attributes = frozenset({"forecast_5min"})

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
        """Expose the forecast start time (and, when enabled, the raw curve)."""
        if self.coordinator.data is None or self.coordinator.data.data is None:
            return {}

        data = self.coordinator.data.data
        start_at = data.get("start_at")
        attrs: dict[str, Any] = {
            "minutes_until": data.get("start_in"),
            "at": start_at.isoformat() if start_at is not None else None,
        }

        # The raw 5-minute RV forecast is opt-in via the diagnostic option.
        if self.coordinator.config_entry.options.get(CONF_EXTRA_ATTRIBUTES, False):
            metadata = self.entity_description.access_fn(self.coordinator.data.metadata)
            if metadata is not None and getattr(metadata, "samples", None):
                attrs["forecast_5min"] = metadata.samples

        return attrs
