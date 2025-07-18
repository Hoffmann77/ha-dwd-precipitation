"""Sensor entities for the Heat pump Signal integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from operator import attrgetter

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfPrecipitationDepth
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)

from .const import DOMAIN
from .coordinator import UpdateCoordinator


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class PrecipitationSensorEntityDescription(SensorEntityDescription):
    """Provide a description for a precipitation sensor."""

    value_fn: Callable[[dict], float | None]


RADOLAN_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="radolan_rw",
        name="Precipitation last hour",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda model: model["rw"],
    ),
    PrecipitationSensorEntityDescription(
        key="radolan_sf",
        name="Precipitation last 24 hours",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda model: model["sf"],
    ),
    PrecipitationSensorEntityDescription(
        key="radolan_sf_yesterday",
        name="Precipitation yesterday",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda model: model["sf_2350"],
    ),
    PrecipitationSensorEntityDescription(
        key="radolan_sf_today",
        name="Precipitation today",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda model: model["sf"] - model["sf_0050"],
    ),
)


RADVOR_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="radvor_rq_000",
        name="Precipitation now",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda model: model["rq"][0],
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rq_060",
        name="Precipitation +1 hour",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda model: model["rq"][1],
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rq_120",
        name="Precipitation +2 hours",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda model: model["rq"][2],
    ),
)


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensor platform."""
    #coordinator = hass.data[DOMAIN][entry.entry_id]

    coordinator = entry.runtime_data.coordinator

    # async_add_entities(
    #     PrecipitationSensorEntity(coordinator, description)
    #     for description in PRECIPTITATION_SENSORS
    #     if description.exists_fn(entry)
    # )

    async_add_entities(
        PrecipitationSensorEntity(coordinator, description)
        for description in RADVOR_SENSORS
        #if description.exists_fn(entry)
    )

    async_add_entities(
        PrecipitationSensorEntity(coordinator, description)
        for description in RADOLAN_SENSORS
        #if description.exists_fn(entry)
    )



class DwdCoordinatorEntity(CoordinatorEntity[UpdateCoordinator]):
    """Coordinator entity."""

    entity_description: PrecipitationSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
            self,
            coordinator: UpdateCoordinator,
            description: PrecipitationSensorEntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)

        self.entity_description = description
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=coordinator.config_entry.title or "Heat pump Signal",
        )


class PrecipitationSensorEntity(DwdCoordinatorEntity, SensorEntity):
    """Implementation of a precipitation sensor."""

    entity_description: PrecipitationSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
            self,
            coordinator: UpdateCoordinator,
            description: PrecipitationSensorEntityDescription,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator, description)

        self._attr_unique_id = (
            f"{self.coordinator.config_entry.entry_id}"
            + f"_{self.entity_description.key}"
        )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        precipitation = self.coordinator.data
        assert precipitation is not None

        return self.entity_description.value_fn(precipitation)


# class PrecipitationTodaySensorEntity(PrecipitationSensorEntity):
#     """Implementation of a precipitation sensor."""

#     @property
#     def native_value(self):
#         """Return the state of the sensor."""
#         precipitation = self.coordinator.data
#         assert precipitation is not None

#         today = precipitation["sf"] -  precipitation["sf_0050"]

#         return today