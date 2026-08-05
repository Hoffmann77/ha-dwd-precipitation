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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EXTRA_ATTRIBUTES,
    CONF_PRECIPITATION_RESET_THRESHOLD,
    DEFAULT_PRECIPITATION_RESET_THRESHOLD,
    CONF_START_END_MODE,
    DEFAULT_START_END_MODE,
    START_END_MODE_DURATION,
    PRECIP_TYPE_OPTIONS,
    DOMAIN,
)
from .coordinator import BaseProductUpdateCoordinator, ProductMetadata
from .dry_streak import (
    DryStreakExtraData,
    downtime_correction,
    fresh_anchor,
    scalar_reading,
)
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
        translation_key="precipitation_last_1h_adjusted",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rw",
        access_fn=lambda d: d,
    ),
    PrecipitationSensorEntityDescription(
        key="radolan_sf",
        translation_key="precipitation_last_24h",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="sf",
        access_fn=lambda d: d,
    ),
    PrecipitationSensorEntityDescription(
        key="radolan_sf_yesterday",
        translation_key="precipitation_yesterday",
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
        translation_key="precipitation_last_1h",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rs",
        access_fn=lambda _list: _list[0],
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rs_060",
        translation_key="precipitation_next_1h",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rs",
        access_fn=lambda _list: _list[1],
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rs_120",
        translation_key="precipitation_next_1_2h",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rs",
        access_fn=lambda _list: _list[2],
    ),
)


# RV sensors whose shape does not depend on the start/end display mode: the two
# peak-intensity sensors.
RADVOR_RV_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="radvor_rv_max_intensity_060",
        translation_key="precipitation_peak_next_1h",
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rv",
        access_fn=lambda d: d["max_060"],
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rv_max_intensity_120",
        translation_key="precipitation_peak_next_1_2h",
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rv",
        access_fn=lambda d: d["max_120"],
    ),
)


HYMECNG_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="hymecng_precipitation_type",
        translation_key="precipitation_type",
        icon="mdi:weather-snowy-rainy",
        device_class=SensorDeviceClass.ENUM,
        options=PRECIP_TYPE_OPTIONS,
        product_key="hymecng",
        access_fn=lambda d: d,
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
                key="radvor_rv_precipitation_start",
                translation_key="precipitation_start",
                native_unit_of_measurement=UnitOfTime.MINUTES,
                device_class=SensorDeviceClass.DURATION,
                state_class=SensorStateClass.MEASUREMENT,
                product_key="rv",
                access_fn=lambda d: d["start_in"],
                attrs_fn=lambda d: {"at": d["start_at"]},
            ),
            PrecipitationSensorEntityDescription(
                key="radvor_rv_precipitation_end",
                translation_key="precipitation_end",
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
            key="radvor_rv_precipitation_start",
            translation_key="precipitation_start",
            device_class=SensorDeviceClass.TIMESTAMP,
            product_key="rv",
            access_fn=lambda d: d["start_at"],
            attrs_fn=lambda d: {"minutes_until": d["start_in"]},
        ),
        PrecipitationSensorEntityDescription(
            key="radvor_rv_precipitation_end",
            translation_key="precipitation_end",
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
        + HYMECNG_SENSORS
        + RADOLAN_SENSORS
    )

    entities: list[SensorEntity] = [
        PrecipitationSensorEntity(
            coordinators[entity_description.product_key],
            entity_description,
        )
        for entity_description in entity_descriptions
    ]
    entities.append(TimespanWithoutPrecipitationSensor(coordinators["rs"]))

    async_add_entities(entities)


class PrecipitationSensorEntity(DwdCoordinatorEntity, SensorEntity):
    """Implementation of a precipitation sensor."""

    entity_description: PrecipitationSensorEntityDescription

    # The 5-minute constituent points would bloat the recorder history.
    _unrecorded_attributes = frozenset({"forecast_5min"})

    @property
    def native_value(self) -> float | datetime | str | None:
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


class TimespanWithoutPrecipitationSensor(
    CoordinatorEntity[BaseProductUpdateCoordinator], RestoreEntity, SensorEntity
):
    """Number of days since precipitation last reached the reset threshold.

    Counts elapsed time since an anchor (``dry_since``). The anchor is re-set
    whenever "Precipitation last 1h" reaches the configurable threshold, and stands
    otherwise, so the value grows continuously while it stays dry and drops back
    to ~0 when it rains. The anchor is persisted across restarts and corrected on
    startup against the RW/SF accumulation products to catch rain during downtime.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "timespan_without_precipitation"
    _attr_icon = "mdi:weather-sunny"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: BaseProductUpdateCoordinator) -> None:
        """Initialize the sensor, bound to the RS ("Precipitation last 1h") coordinator."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_timespan_without_precipitation"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title or "DWD Precipitation",
        )
        self._dry_since: datetime | None = None

    @property
    def _threshold(self) -> float:
        """Return the configured rain reset threshold in mm."""
        return self.coordinator.config_entry.options.get(
            CONF_PRECIPITATION_RESET_THRESHOLD, DEFAULT_PRECIPITATION_RESET_THRESHOLD
        )

    def _precip_now(self) -> float | None:
        """Return the latest RS hourly total (mm), or None if unavailable."""
        cdata = self.coordinator.data
        if cdata is None or cdata.data is None:
            return None

        value = cdata.data[0]  # rs lead time [0] == the past hour's total
        if value is None:
            return None

        value = float(value)

        return None if value != value else value  # drop NaN

    def _measurement_time(self) -> datetime:
        """Return the rs_000 measurement timestamp, falling back to utcnow()."""
        cdata = self.coordinator.data
        if cdata is not None and cdata.metadata:
            meta = cdata.metadata[0]
            if meta is not None and meta.source_timestamp is not None:
                return meta.source_timestamp  # UTC-aware

        return dt_util.utcnow()

    def _process(self) -> None:
        """Refresh the dry-since anchor from the latest coordinator data."""
        precip = self._precip_now()
        if precip is not None and precip >= self._threshold:
            self._dry_since = self._measurement_time()  # it rained -> reset
        elif self._dry_since is None:
            self._dry_since = self._measurement_time()  # first observation

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._process()
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        """Restore the anchor and correct it for any rain during downtime."""
        await super().async_added_to_hass()

        if (restored := await self.async_get_last_extra_data()) is not None:
            self._dry_since = DryStreakExtraData.from_dict(
                restored.as_dict()
            ).dry_since

        now = dt_util.utcnow()
        siblings = self.coordinator.config_entry.runtime_data.coordinators
        rw = scalar_reading(siblings.get("rw"))
        sf = scalar_reading(siblings.get("sf"))

        if self._dry_since is not None:
            # Clamp a stale restored anchor forward if RW/SF show recent rain.
            correction = downtime_correction(self._threshold, rw, sf, now)
            if correction is not None and correction > self._dry_since:
                self._dry_since = correction
        else:
            # Fresh install: establish the oldest provable dry time.
            self._dry_since = fresh_anchor(self._threshold, rw, sf, now)

        # coordinator.data is already populated by the first refresh; catch up once.
        self._process()

    @property
    def extra_restore_state_data(self) -> DryStreakExtraData:
        """Return the anchor to persist across restarts."""
        return DryStreakExtraData(dry_since=self._dry_since)

    @property
    def native_value(self) -> float | None:
        """Return the dry streak in days."""
        if self._dry_since is None:
            return None

        seconds = max((dt_util.utcnow() - self._dry_since).total_seconds(), 0.0)

        return round(seconds / 86400, 4)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the dry streak in hours (always present)."""
        if self._dry_since is None:
            return {"hours_without_precipitation": None}

        seconds = max((dt_util.utcnow() - self._dry_since).total_seconds(), 0.0)

        return {
            "hours_without_precipitation": round(seconds / 3600, 2),
            "dry_since": self._dry_since.isoformat(),
        }
