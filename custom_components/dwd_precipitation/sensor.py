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
from homeassistant.const import UnitOfPrecipitationDepth, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EXTRA_ATTRIBUTES,
    CONF_RAIN_THRESHOLD,
    DEFAULT_RAIN_THRESHOLD,
    DOMAIN,
)
from .coordinator import BaseProductUpdateCoordinator, ProductMetadata

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class PrecipitationSensorEntityDescription(SensorEntityDescription):
    """Provide a description for a precipitation sensor."""

    product_key: str
    access_fn: Callable[[Any], Any]


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
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinators = entry.runtime_data.coordinators

    entity_descriptions = RADVOR_SENSORS + RADOLAN_SENSORS

    entities: list[SensorEntity] = [
        PrecipitationSensorEntity(
            coordinators[entity_description.product_key],
            entity_description,
        )
        for entity_description in entity_descriptions
    ]
    entities.append(DaysWithoutRainSensor(coordinators["rs"]))

    async_add_entities(entities)


class DwdCoordinatorEntity(CoordinatorEntity[BaseProductUpdateCoordinator]):
    """Base coordinator entity."""

    entity_description: PrecipitationSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BaseProductUpdateCoordinator,
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

    def __init__(
        self,
        coordinator: BaseProductUpdateCoordinator,
        description: PrecipitationSensorEntityDescription,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator, description)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{description.key}"
        )

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None

        if (data := self.coordinator.data.data) is None:
            return None

        return self.entity_description.access_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic metadata as state attributes."""
        extra_state_attributes = self.coordinator.config_entry.options.get(
            CONF_EXTRA_ATTRIBUTES, False
        )
        if not extra_state_attributes:
            return {}

        if self.coordinator.data is None:
            return {}

        metadata: ProductMetadata = self.entity_description.access_fn(
            self.coordinator.data.metadata
        )
        if metadata is None:
            return {}

        attrs: dict[str, Any] = {
            "source_product": metadata.source_product,
            "source_timestamp": (
                metadata.source_timestamp.isoformat()
                if metadata.source_timestamp
                else None
            ),
            "lead_time_minutes": metadata.lead_time_minutes,
        }
        if metadata.data_start is not None:
            attrs["data_start"] = metadata.data_start.isoformat()
        if metadata.data_end is not None:
            attrs["data_end"] = metadata.data_end.isoformat()

        return attrs


@dataclass
class DryStreakExtraData(ExtraStoredData):
    """Persisted anchor for the days-without-rain sensor."""

    dry_since: datetime | None

    def as_dict(self) -> dict[str, Any]:
        """Serialize the anchor for restore_state."""
        return {
            "dry_since": self.dry_since.isoformat() if self.dry_since else None
        }

    @classmethod
    def from_dict(cls, restored: dict[str, Any]) -> "DryStreakExtraData":
        """Rebuild the anchor from a restored dict, forcing UTC-awareness."""
        raw = restored.get("dry_since")
        ts = dt_util.parse_datetime(raw) if raw else None
        if ts is not None and ts.tzinfo is None:
            ts = dt_util.as_utc(ts)

        return cls(dry_since=ts)


def _scalar_reading(
    coordinator: BaseProductUpdateCoordinator | None,
) -> tuple[float | None, datetime | None, datetime | None]:
    """Return (value, data_start, data_end) from a scalar RADOLAN coordinator.

    Yields (None, None, None) when the coordinator or its data is missing.
    """
    cdata = getattr(coordinator, "data", None) if coordinator else None
    if cdata is None or cdata.data is None:
        return (None, None, None)

    meta = cdata.metadata

    return (
        float(cdata.data),
        getattr(meta, "data_start", None),
        getattr(meta, "data_end", None),
    )


def _downtime_correction(
    threshold: float,
    rw: tuple[float | None, datetime | None, datetime | None],
    sf: tuple[float | None, datetime | None, datetime | None],
    now: datetime,
) -> datetime | None:
    """Newest time we have positive rain evidence, to clamp a stale anchor forward.

    Used only at startup to catch rain that fell while HA was down. Returns a UTC
    datetime to clamp the anchor forward to, or None when there is no evidence.
    """
    rw_value, _, rw_end = rw
    if rw_value is not None and rw_value >= threshold:
        # Rain within the last hour -> the streak is effectively zero.
        return rw_end or now

    sf_value, sf_start, _ = sf
    if sf_value is not None and sf_value >= threshold:
        # Rain within the last 24h (but not the last hour). We cannot pin the exact
        # time, so cap the streak at the start of the SF window (~24h ago).
        return sf_start or now

    return None


def _fresh_anchor(
    threshold: float,
    rw: tuple[float | None, datetime | None, datetime | None],
    sf: tuple[float | None, datetime | None, datetime | None],
    now: datetime,
) -> datetime:
    """Anchor for a fresh install: the oldest time we can prove it has been dry."""
    sf_value, sf_start, _ = sf
    if sf_value is not None and sf_value < threshold and sf_start:
        return sf_start  # dry for at least the 24h SF window

    rw_value, rw_start, _ = rw
    if rw_value is not None and rw_value < threshold and rw_start:
        return rw_start  # dry for at least the last hour

    return now


class DaysWithoutRainSensor(
    CoordinatorEntity[BaseProductUpdateCoordinator], RestoreEntity, SensorEntity
):
    """Number of days since precipitation last reached the reset threshold.

    Counts elapsed time since an anchor (``dry_since``). The anchor is re-set
    whenever "precipitation now" reaches the configurable threshold, and stands
    otherwise, so the value grows continuously while it stays dry and drops back
    to ~0 when it rains. The anchor is persisted across restarts and corrected on
    startup against the RW/SF accumulation products to catch rain during downtime.
    """

    _attr_has_entity_name = True
    _attr_name = "Days without rain"
    _attr_icon = "mdi:weather-sunny"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: BaseProductUpdateCoordinator) -> None:
        """Initialize the sensor, bound to the RS ("precipitation now") coordinator."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_days_without_rain"
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
            CONF_RAIN_THRESHOLD, DEFAULT_RAIN_THRESHOLD
        )

    def _precip_now(self) -> float | None:
        """Return the current "precipitation now" value (mm), or None if unavailable."""
        cdata = self.coordinator.data
        if cdata is None or cdata.data is None:
            return None

        value = cdata.data[0]  # rs lead time [0] == "precipitation now"
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
        rw = _scalar_reading(siblings.get("rw"))
        sf = _scalar_reading(siblings.get("sf"))

        if self._dry_since is not None:
            # Clamp a stale restored anchor forward if RW/SF show recent rain.
            correction = _downtime_correction(self._threshold, rw, sf, now)
            if correction is not None and correction > self._dry_since:
                self._dry_since = correction
        else:
            # Fresh install: establish the oldest provable dry time.
            self._dry_since = _fresh_anchor(self._threshold, rw, sf, now)

        # coordinator.data is already populated by the first refresh; catch up once.
        self._process()

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
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
            return {"hours_without_rain": None}

        seconds = max((dt_util.utcnow() - self._dry_since).total_seconds(), 0.0)

        return {
            "hours_without_rain": round(seconds / 3600, 2),
            "dry_since": self._dry_since.isoformat(),
        }
