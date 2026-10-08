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
    UnitOfLength,
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
    CONF_FULL_ROLLING_SERIES,
    DEFAULT_FULL_ROLLING_SERIES,
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
from .precipitation_total import (
    PrecipitationTotalExtraData,
    countable,
    missed_releases,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class PrecipitationSensorEntityDescription(SensorEntityDescription):
    """Provide a description for a precipitation sensor."""

    product_key: str
    access_fn: Callable[[Any], Any]
    # Optional companion attributes, computed from the coordinator data payload.
    # Always exposed (not gated behind the diagnostic-attributes option).
    attrs_fn: Callable[[Any], dict[str, Any]] | None = None
    # Like attrs_fn, but computed from this entity's ProductMetadata (as picked
    # by access_fn). Also always exposed.
    metadata_attrs_fn: Callable[[ProductMetadata], dict[str, Any]] | None = None


RADOLAN_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="radolan_rw",
        translation_key="precipitation_last_1h",
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


@dataclass(frozen=True, kw_only=True)
class PrecipitationTotalEntityDescription(SensorEntityDescription):
    """Provide a description for a cumulative precipitation total."""

    product_key: str
    # How many missed releases to fetch after a gap (see missed_releases).
    max_backfill: int


# Two totals over the same rain: RW counts each hour as soon as it is analysed,
# sf_2350 counts each day once, the morning after. They are separate entities
# rather than one with a source option so that switching never makes a
# TOTAL_INCREASING sensor jump.
TOTAL_SENSORS = (
    PrecipitationTotalEntityDescription(
        key="radolan_rw_total",
        translation_key="precipitation_total_hourly",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.TOTAL_INCREASING,
        product_key="rw",
        max_backfill=48,
    ),
    PrecipitationTotalEntityDescription(
        key="radolan_sf_yesterday_total",
        translation_key="precipitation_total_daily",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.TOTAL_INCREASING,
        product_key="sf_2350",
        max_backfill=7,
    ),
)


RADVOR_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="radvor_rs_000",
        translation_key="precipitation_now",
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


def _peak_hour_attrs(meta: ProductMetadata) -> dict[str, Any]:
    """Return the peak window and the rolling-hour series behind it."""
    return {
        "window_start": meta.data_start,
        "window_end": meta.data_end,
        "forecast_rolling_1h": meta.rolling_1h,
    }


def _peak_hour_sensor(full_rolling_series: bool) -> PrecipitationSensorEntityDescription:
    """Return "Peak hourly precipitation next 2h", bound to the product feeding it.

    The value is the same from either product (RS equals summed RV for every
    window wholly in the future). RV is the default because it has already
    decoded the steps; RS only when the option asks for the 12 windows RV
    cannot reach. The key is product-neutral so toggling the option keeps the
    entity, its id and its history.
    """
    common = dict(
        key="radvor_peak_1h_120",
        translation_key="peak_hourly_precipitation_next_2h",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        metadata_attrs_fn=_peak_hour_attrs,
    )
    if full_rolling_series:
        return PrecipitationSensorEntityDescription(
            product_key="rs", access_fn=lambda _list: _list[3], **common
        )
    return PrecipitationSensorEntityDescription(
        product_key="rv", access_fn=lambda d: d["peak_1h"], **common
    )


# RV sensors whose shape does not depend on the start/end display mode: the two
# peak-intensity sensors.
RADVOR_RV_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="radvor_rv_max_intensity_060",
        translation_key="peak_intensity_next_1h",
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rv",
        access_fn=lambda d: d["max_060"],
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rv_max_intensity_120",
        translation_key="peak_intensity_next_1_2h",
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rv",
        access_fn=lambda d: d["max_120"],
    ),
    # Closest rain around the location in the latest analysis (radar.area).
    PrecipitationSensorEntityDescription(
        key="radvor_rv_nearest_precipitation",
        translation_key="nearest_precipitation",
        icon="mdi:map-marker-distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        product_key="rv",
        access_fn=lambda d: d["nearest_km"],
        attrs_fn=lambda d: {
            "bearing": d["nearest_bearing"],
            "direction": d["nearest_direction"],
        },
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
            PrecipitationSensorEntityDescription(
                key="radvor_rv_area_precipitation_start",
                translation_key="area_precipitation_start",
                native_unit_of_measurement=UnitOfTime.MINUTES,
                device_class=SensorDeviceClass.DURATION,
                state_class=SensorStateClass.MEASUREMENT,
                product_key="rv",
                access_fn=lambda d: d["area_start_in"],
                attrs_fn=lambda d: {"at": d["area_start_at"]},
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
        PrecipitationSensorEntityDescription(
            key="radvor_rv_area_precipitation_start",
            translation_key="area_precipitation_start",
            device_class=SensorDeviceClass.TIMESTAMP,
            product_key="rv",
            access_fn=lambda d: d["area_start_at"],
            attrs_fn=lambda d: {"minutes_until": d["area_start_in"]},
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
    full_rolling_series = entry.options.get(
        CONF_FULL_ROLLING_SERIES, DEFAULT_FULL_ROLLING_SERIES
    )

    entity_descriptions = (
        RADVOR_SENSORS
        + (_peak_hour_sensor(full_rolling_series),)
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
    entities.extend(
        PrecipitationTotalSensor(coordinators[description.product_key], description)
        for description in TOTAL_SENSORS
    )
    entities.append(TimespanWithoutPrecipitationSensor(coordinators["rs"]))

    async_add_entities(entities)


class PrecipitationSensorEntity(DwdCoordinatorEntity, SensorEntity):
    """Implementation of a precipitation sensor."""

    entity_description: PrecipitationSensorEntityDescription

    # The per-lead forecast series would bloat the recorder history.
    _unrecorded_attributes = frozenset({"forecast_5min", "forecast_rolling_1h"})

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

        metadata: ProductMetadata | None = (
            self.entity_description.access_fn(self.coordinator.data.metadata)
            if self.coordinator.data.metadata
            else None
        )
        metadata_attrs_fn = self.entity_description.metadata_attrs_fn
        if metadata_attrs_fn is not None and metadata is not None:
            attrs.update(
                {
                    key: _plain_value(value)
                    for key, value in metadata_attrs_fn(metadata).items()
                }
            )

        # Diagnostic metadata is opt-in via the integration options.
        if not self.coordinator.config_entry.options.get(
            CONF_EXTRA_ATTRIBUTES, False
        ):
            return attrs

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


class PrecipitationTotalSensor(DwdCoordinatorEntity, RestoreEntity, SensorEntity):
    """Running total of a RADOLAN accumulation product, one release at a time.

    Counts every release once, keyed on its timestamp (see precipitation_total).
    The first release seen after setup only sets the starting point: its window
    predates the sensor, so the total starts at 0. After a gap -- Home Assistant
    was down, or DWD failed for longer than a release -- the missed releases are
    fetched in the background and added as they arrive. A restart during that
    backfill drops whatever it had not fetched yet.
    """

    entity_description: PrecipitationTotalEntityDescription

    def __init__(
        self,
        coordinator: BaseProductUpdateCoordinator,
        description: PrecipitationTotalEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description)
        self._total: float | None = None
        self._last_release: datetime | None = None

    @property
    def available(self) -> bool:
        """Return True once there is a total.

        A total does not go stale the way a reading does: while the product is
        failing it is still the right sum of everything counted so far, and the
        missed releases are added once they can be fetched.
        """
        return self._total is not None

    @property
    def native_value(self) -> float | None:
        """Return the running total in mm."""
        return None if self._total is None else round(self._total, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the end of the newest window included in the total."""
        return {
            "counted_until": (
                self._last_release.isoformat() if self._last_release else None
            )
        }

    @property
    def extra_restore_state_data(self) -> PrecipitationTotalExtraData:
        """Return the total to persist across restarts."""
        return PrecipitationTotalExtraData(
            total=self._total, last_release=self._last_release
        )

    async def async_added_to_hass(self) -> None:
        """Restore the total and count whatever was released in the meantime."""
        await super().async_added_to_hass()

        if (restored := await self.async_get_last_extra_data()) is not None:
            data = PrecipitationTotalExtraData.from_dict(restored.as_dict())
            self._total = data.total
            self._last_release = data.last_release

        # coordinator.data is already populated by the first refresh.
        self._count_new_release()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._count_new_release()
        super()._handle_coordinator_update()

    @callback
    def _count_new_release(self) -> None:
        """Add the coordinator's release to the total if it is a new one."""
        release = self.coordinator.curr_release
        cdata = self.coordinator.data
        if release is None or cdata is None:
            return

        if self._last_release is not None and release <= self._last_release:
            return

        if self._last_release is None or self._total is None:
            # First release ever seen: it fixes the starting point only.
            self._total = self._total or 0.0
            self._last_release = release
            return

        missed = missed_releases(
            self.coordinator,
            self._last_release,
            release,
            self.entity_description.max_backfill,
        )

        if (value := countable(cdata.data)) is not None:
            self._total += value
        self._last_release = release

        if missed:
            self.coordinator.config_entry.async_create_background_task(
                self.hass,
                self._async_backfill(missed),
                f"{self.entity_id} backfill",
            )

    async def _async_backfill(self, releases: list[datetime]) -> None:
        """Fetch releases that were never counted and add them to the total."""
        failed = 0
        for release in releases:
            try:
                value, _metadata = await self.coordinator._fetch_and_parse(release)
            except Exception as err:  # noqa: BLE001 - any failure skips the file
                _LOGGER.debug(
                    "%s: could not backfill %s: %s",
                    self.entity_id,
                    release.isoformat(),
                    err,
                )
                failed += 1
                continue

            if (mm := countable(value)) is not None:
                self._total = (self._total or 0.0) + mm
                self.async_write_ha_state()

        if failed:
            _LOGGER.info(
                "%s: %s of %s missed DWD releases could not be fetched, so the "
                "total leaves them out",
                self.entity_id,
                failed,
                len(releases),
            )


class TimespanWithoutPrecipitationSensor(
    CoordinatorEntity[BaseProductUpdateCoordinator], RestoreEntity, SensorEntity
):
    """Number of days since precipitation last reached the reset threshold.

    Counts elapsed time since an anchor (``dry_since``). The anchor is re-set
    whenever "Precipitation now" reaches the configurable threshold, and stands
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
        """Initialize the sensor, bound to the RS ("Precipitation now") coordinator."""
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
