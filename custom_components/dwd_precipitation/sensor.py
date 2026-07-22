"""Sensor entities for the DWD Precipitation integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfPrecipitationDepth,
    UnitOfTime,
    UnitOfVolumetricFlux,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_EXTRA_ATTRIBUTES,
    CONF_START_END_MODE,
    DEFAULT_START_END_MODE,
    START_END_MODE_DURATION,
)
from .coordinator import ProductMetadata
from .entity import DwdCoordinatorEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class PrecipitationSensorEntityDescription(SensorEntityDescription):
    """Provide a description for a precipitation sensor."""

    product_key: str
    access_fn: Callable[[Any], Any]
    # Optional companion attributes, computed from the coordinator data payload.
    # Always exposed (not gated behind the diagnostic-attributes option).
    attrs_fn: Callable[[Any], dict[str, Any]] | None = None


RADOLAN_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="radolan_rw",
        name="Precipitation last hour",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rw",
        access_fn=lambda d: d,
    ),
    PrecipitationSensorEntityDescription(
        key="radolan_sf",
        name="Precipitation last 24 hours",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="sf",
        access_fn=lambda d: d,
    ),
    PrecipitationSensorEntityDescription(
        key="radolan_sf_yesterday",
        name="Precipitation yesterday",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="sf_2350",
        access_fn=lambda d: d,
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
        product_key="rs",
        access_fn=lambda _list: _list[0],
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rs_060",
        name="Precipitation +1 hour",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rs",
        access_fn=lambda _list: _list[1],
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rs_120",
        name="Precipitation +2 hours",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rs",
        access_fn=lambda _list: _list[2],
    ),
)


# RV sensors whose shape does not depend on the start/end display mode: the two
# hourly totals and the two peak-intensity sensors.
RADVOR_RV_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="radvor_rv_060",
        name="Precipitation +1 hour (RV)",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rv",
        access_fn=lambda d: d["rv_060"],
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rv_120",
        name="Precipitation +2 hours (RV)",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rv",
        access_fn=lambda d: d["rv_120"],
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rv_max_intensity_060",
        name="Max precipitation intensity +1 hour (RV)",
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rv",
        access_fn=lambda d: d["max_060"],
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rv_max_intensity_120",
        name="Max precipitation intensity +2 hours (RV)",
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rv",
        access_fn=lambda d: d["max_120"],
    ),
)


def _rv_timing_sensors(
    mode: str,
) -> tuple[PrecipitationSensorEntityDescription, ...]:
    """Return the merged RV start/end sensors for the configured display mode.

    The entity keys are stable across modes so the entity id and unique id
    survive an options change; only the state representation (and the companion
    attribute) differs.
    """
    if mode == START_END_MODE_DURATION:
        return (
            PrecipitationSensorEntityDescription(
                key="rv_precipitation_start",
                name="Precipitation start",
                native_unit_of_measurement=UnitOfTime.MINUTES,
                device_class=SensorDeviceClass.DURATION,
                state_class=SensorStateClass.MEASUREMENT,
                product_key="rv",
                access_fn=lambda d: d["start_in"],
                attrs_fn=lambda d: {"at": d["start_at"]},
            ),
            PrecipitationSensorEntityDescription(
                key="rv_precipitation_end",
                name="Precipitation end",
                native_unit_of_measurement=UnitOfTime.MINUTES,
                device_class=SensorDeviceClass.DURATION,
                state_class=SensorStateClass.MEASUREMENT,
                product_key="rv",
                access_fn=lambda d: d["end_in"],
                attrs_fn=lambda d: {"at": d["end_at"]},
            ),
        )

    # Default: absolute timestamp, with the minutes-until value as an attribute.
    return (
        PrecipitationSensorEntityDescription(
            key="rv_precipitation_start",
            name="Precipitation start",
            device_class=SensorDeviceClass.TIMESTAMP,
            product_key="rv",
            access_fn=lambda d: d["start_at"],
            attrs_fn=lambda d: {"minutes_until": d["start_in"]},
        ),
        PrecipitationSensorEntityDescription(
            key="rv_precipitation_end",
            name="Precipitation end",
            device_class=SensorDeviceClass.TIMESTAMP,
            product_key="rv",
            access_fn=lambda d: d["end_at"],
            attrs_fn=lambda d: {"minutes_until": d["end_in"]},
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinators = entry.runtime_data.coordinators

    mode = entry.options.get(CONF_START_END_MODE, DEFAULT_START_END_MODE)

    entity_descriptions = (
        RADVOR_SENSORS
        + RADVOR_RV_SENSORS
        + _rv_timing_sensors(mode)
        + RADOLAN_SENSORS
    )

    async_add_entities(
        PrecipitationSensorEntity(
            coordinators[entity_description.product_key],
            entity_description,
        )
        for entity_description in entity_descriptions
    )


class PrecipitationSensorEntity(DwdCoordinatorEntity, SensorEntity):
    """Implementation of a precipitation sensor."""

    entity_description: PrecipitationSensorEntityDescription

    # The 5-minute constituent points would bloat the recorder history.
    _unrecorded_attributes = frozenset({"forecast_5min"})

    @property
    def native_value(self) -> float | datetime | None:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None

        if (data := self.coordinator.data.data) is None:
            return None

        return self.entity_description.access_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return companion values and, when enabled, diagnostic metadata."""
        if self.coordinator.data is None:
            return {}

        attrs: dict[str, Any] = {}

        # Companion attributes (e.g. the start/end representation not used as the
        # state) are a feature, so they are always exposed.
        attrs_fn = self.entity_description.attrs_fn
        if attrs_fn is not None and self.coordinator.data.data is not None:
            attrs.update(
                {
                    key: _plain_value(value)
                    for key, value in attrs_fn(self.coordinator.data.data).items()
                }
            )

        # Diagnostic metadata is opt-in via the integration options.
        if not self.coordinator.config_entry.options.get(
            CONF_EXTRA_ATTRIBUTES, False
        ):
            return attrs

        metadata: ProductMetadata = self.entity_description.access_fn(
            self.coordinator.data.metadata
        )
        if metadata is None:
            return attrs

        attrs["source_product"] = metadata.source_product
        attrs["source_timestamp"] = (
            metadata.source_timestamp.isoformat()
            if metadata.source_timestamp
            else None
        )
        attrs["lead_time_minutes"] = metadata.lead_time_minutes
        if metadata.data_start is not None:
            attrs["data_start"] = metadata.data_start.isoformat()
        if metadata.data_end is not None:
            attrs["data_end"] = metadata.data_end.isoformat()
        if getattr(metadata, "samples", None):
            attrs["forecast_5min"] = metadata.samples

        return attrs
