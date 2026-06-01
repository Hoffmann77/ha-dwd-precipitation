"""Sensor entities for the Heat pump Signal integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util
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
    metadata_key: str
    stale_after: timedelta
    metadata_index: int | None = None


RADOLAN_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="radolan_rw",
        name="Precipitation last hour",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda model: model["rw"],
        metadata_key="rw",
        stale_after=timedelta(hours=2),
    ),
    PrecipitationSensorEntityDescription(
        key="radolan_sf",
        name="Precipitation last 24 hours",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda model: model["sf"],
        metadata_key="sf",
        stale_after=timedelta(hours=30),
    ),
    PrecipitationSensorEntityDescription(
        key="radolan_sf_yesterday",
        name="Precipitation yesterday",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda model: model["sf_2350"],
        metadata_key="sf_2350",
        stale_after=timedelta(hours=30),
    ),
)


RADVOR_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="radvor_rs_000",
        name="Precipitation now",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda model: model["rs"][0],
        metadata_key="rs",
        stale_after=timedelta(minutes=15),
        metadata_index=0,
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rs_060",
        name="Precipitation +1 hour",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda model: model["rs"][1],
        metadata_key="rs",
        stale_after=timedelta(minutes=15),
        metadata_index=1,
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rs_120",
        name="Precipitation +2 hours",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda model: model["rs"][2],
        metadata_key="rs",
        stale_after=timedelta(minutes=15),
        metadata_index=2,
    ),
)


def _plain_value(value: Any) -> Any:
    """Return values suitable for Home Assistant state attributes."""
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "decode"):
        return value.decode()
    if hasattr(value, "item"):
        return value.item()
    return value


def _metadata_datetime(metadata: dict[str, Any]) -> datetime | None:
    """Extract a UTC source timestamp from product metadata."""
    value = metadata.get("datetime")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return dt_util.as_utc(value)

    return None


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensor platform."""
    coordinator = entry.runtime_data.coordinator

    async_add_entities(
        PrecipitationSensorEntity(coordinator, description)
        for description in RADVOR_SENSORS
    )

    async_add_entities(
        PrecipitationSensorEntity(coordinator, description)
        for description in RADOLAN_SENSORS
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
            name=coordinator.config_entry.title or "DWD Precipitation",
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

    def _metadata(self) -> dict[str, Any]:
        """Return metadata for this sensor's source product."""
        precipitation = self.coordinator.data
        if precipitation is None:
            return {}

        metadata = precipitation.get(f"{self.entity_description.metadata_key}_metadata")
        index = self.entity_description.metadata_index
        if isinstance(metadata, (list, tuple)) and index is not None:
            if index < len(metadata) and isinstance(metadata[index], dict):
                return metadata[index]
            return {}

        if isinstance(metadata, dict):
            return metadata

        return {}

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic metadata as attributes."""
        metadata = self._metadata()
        if not metadata:
            return {}

        source_dt = _metadata_datetime(metadata)
        if source_dt is None:
            timestamp = None
            data_age = None
            status = "unknown_timestamp"
        else:
            timestamp = source_dt.isoformat()
            now = dt_util.utcnow()
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            data_age = (now - source_dt).total_seconds()
            status = (
                "ok"
                if data_age <= self.entity_description.stale_after.total_seconds()
                else "stale"
            )

        return {
            "source_product": _plain_value(
                metadata.get("product")
                or metadata.get("producttype")
                or metadata.get("prodname")
            ),
            "source_timestamp": timestamp,
            "data_age_seconds": round(data_age) if data_age is not None else None,
            "data_status": status,
            "lead_time_minutes": _plain_value(
                metadata.get("lead_time_minutes")
                if "lead_time_minutes" in metadata
                else (
                    metadata.get("predictiontime")
                    if "predictiontime" in metadata
                    else metadata.get("VV")
                )
            ),
        }
