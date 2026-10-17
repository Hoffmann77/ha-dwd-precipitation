"""Sensor entities for the DWD Precipitation integration."""

from __future__ import annotations

import logging
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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import (
    KEY_AMOUNT,
    KEY_LAST_60,
    KEY_NEXT_60,
    KEY_NEXT_60_120,
    KEY_NEXT_120,
    KEY_PRECIPITATION_TYPE,
    RW_SLIDING_KEY,
    START_END_MODE_DURATION,
    PRECIP_TYPE_OPTIONS,
    DOMAIN,
)
from .coordinator import BaseProductUpdateCoordinator, ProductMetadata
from .dry_streak import (
    DryStreakExtraData,
    downtime_correction,
    fresh_anchor,
    amount_reading,
)
from .entity import DwdCoordinatorEntity, DwdEntityDescriptionMixin, unique_id_for
from .radar.isotime import iso
from .radar.rain_events import NO_EVENT, ONGOING, UPCOMING, VIEW_KEYS, overall_status
from .precipitation_total import (
    PrecipitationTotalExtraData,
    counted_on_grid,
    countable,
    missed_releases,
    split_fetchable,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class PrecipitationSensorEntityDescription(
    SensorEntityDescription, DwdEntityDescriptionMixin
):
    """Provide a description for a precipitation sensor."""


# What every amount (mm) and every intensity (mm/h) sensor shares.
# Spread into descriptions; each value goes to a differently typed field.
_MM: dict[str, Any] = dict(
    native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
    device_class=SensorDeviceClass.PRECIPITATION,
    suggested_display_precision=1,
    state_class=SensorStateClass.MEASUREMENT,
)
_MM_TOTAL: dict[str, Any] = _MM | dict(state_class=SensorStateClass.TOTAL_INCREASING)
_MMH: dict[str, Any] = dict(
    native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
    device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
    suggested_display_precision=1,
    state_class=SensorStateClass.MEASUREMENT,
)


# The gauge-adjusted analyses. RW's is a clock hour, so it is the "previous
# hour" rather than a "last 60 min": that name belongs to RS's rolling hour,
# a sliding window like every other "last"/"next" one.
RADOLAN_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="radolan_rw",
        translation_key="precipitation_previous_hour",
        **_MM,
        product_key="rw",
        sub_key=KEY_AMOUNT,
    ),
    PrecipitationSensorEntityDescription(
        key="radolan_sf",
        translation_key="precipitation_last_24h",
        **_MM,
        product_key="sf",
        sub_key=KEY_AMOUNT,
    ),
    PrecipitationSensorEntityDescription(
        key="radolan_sf_yesterday",
        translation_key="precipitation_yesterday",
        **_MM,
        product_key="sf_2350",
        sub_key=KEY_AMOUNT,
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
        translation_key="precipitation_total",
        **_MM_TOTAL,
        product_key="rw",
        max_backfill=48,
    ),
    PrecipitationTotalEntityDescription(
        key="radolan_sf_yesterday_total",
        translation_key="precipitation_total_daily",
        # Precipitation total is the one to use; this one puts every day's
        # rain under the next day in HA's statistics. Only applies when the
        # entity is first registered, so installs that have it keep it on.
        entity_registry_enabled_default=False,
        **_MM_TOTAL,
        product_key="sf_2350",
        max_backfill=7,
    ),
)


RADVOR_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="radvor_rs_000",
        translation_key="precipitation_last_60_min",
        **_MM,
        product_key="rs",
        sub_key=KEY_LAST_60,
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rs_060",
        translation_key="precipitation_next_60_min",
        **_MM,
        product_key="rs",
        sub_key=KEY_NEXT_60,
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rs_120",
        translation_key="precipitation_next_60_120_min",
        **_MM,
        product_key="rs",
        sub_key=KEY_NEXT_60_120,
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rs_000_120",
        translation_key="precipitation_next_120_min",
        **_MM,
        product_key="rs",
        sub_key=KEY_NEXT_120,
    ),
)


def _peak_hour_attrs(meta: ProductMetadata) -> dict[str, Any]:
    """Return the peak window and the rolling-hour series behind it."""
    return {
        "window_start": meta.data_start,
        "window_end": meta.data_end,
        "forecast_rolling_1h": meta.rolling_1h,
    }


# RV sensors whose shape does not depend on the start/end display mode: the
# current intensity, the three peak-intensity sensors and the peak hour.
RADVOR_RV_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="radvor_rv_intensity_000",
        translation_key="precipitation_intensity_now",
        **_MMH,
        product_key="rv",
        sub_key="intensity_000",
        # "Now" is the latest analysis, the 5 minutes ending at the release
        # time; the window and the unscaled amount say so.
        attrs_fn=lambda d: {"amount_5min": d["amount_000"]},
        metadata_attrs_fn=lambda meta: {
            "window_start": meta.data_start,
            "window_end": meta.data_end,
        },
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rv_max_intensity_060",
        translation_key="peak_intensity_next_60_min",
        **_MMH,
        product_key="rv",
        sub_key="max_060",
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rv_max_intensity_120",
        translation_key="peak_intensity_next_60_120_min",
        **_MMH,
        product_key="rv",
        sub_key="max_120",
    ),
    PrecipitationSensorEntityDescription(
        key="radvor_rv_max_intensity_000_120",
        translation_key="peak_intensity_next_120_min",
        **_MMH,
        product_key="rv",
        sub_key="max_000_120",
    ),
    # Summed from RV's 5-minute steps, which match RS's rolling hours. The
    # key keeps its product-neutral name from when RS fed it with the full
    # rolling series option on.
    PrecipitationSensorEntityDescription(
        key="radvor_peak_1h_120",
        translation_key="peak_hourly_precipitation_next_120_min",
        **_MM,
        product_key="rv",
        sub_key="peak_1h",
        metadata_attrs_fn=_peak_hour_attrs,
    ),
)


HYMECNG_SENSORS = (
    PrecipitationSensorEntityDescription(
        key="hymecng_precipitation_type",
        translation_key="precipitation_type_now",
        icon="mdi:weather-snowy-rainy",
        device_class=SensorDeviceClass.ENUM,
        options=PRECIP_TYPE_OPTIONS,
        product_key="hymecng",
        sub_key=KEY_PRECIPITATION_TYPE,
    ),
)


# The rain-event tracker's view, for blueprints. Its state is the status of
# the nearest event; the view itself (schema 1) is the attributes.
RAIN_EVENTS_SENSOR = SensorEntityDescription(
    key="radvor_rv_rain_events",
    translation_key="rain_events",
    icon="mdi:weather-pouring",
    device_class=SensorDeviceClass.ENUM,
    options=[NO_EVENT, UPCOMING, ONGOING],
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
                sub_key="start_in",
                attrs_fn=lambda d: {"at": d["start_at"]},
            ),
            PrecipitationSensorEntityDescription(
                key="radvor_rv_precipitation_end",
                translation_key="precipitation_end",
                native_unit_of_measurement=UnitOfTime.MINUTES,
                device_class=SensorDeviceClass.DURATION,
                state_class=SensorStateClass.MEASUREMENT,
                product_key="rv",
                sub_key="end_in",
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
            sub_key="start_at",
            attrs_fn=lambda d: {"minutes_until": d["start_in"]},
        ),
        PrecipitationSensorEntityDescription(
            key="radvor_rv_precipitation_end",
            translation_key="precipitation_end",
            device_class=SensorDeviceClass.TIMESTAMP,
            product_key="rv",
            sub_key="end_at",
            attrs_fn=lambda d: {"minutes_until": d["end_in"]},
        ),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinators = entry.runtime_data.coordinators
    options = entry.runtime_data.options

    entity_descriptions = (
        RADVOR_SENSORS
        + RADVOR_RV_SENSORS
        + _rv_timing_sensors(options.start_end_mode)
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
    # Rain events are opt-in. With the option off there is no tracker, so the
    # entity goes too, rather than lingering as "no longer provided".
    if options.rain_events:
        entities.append(RainEventsSensor(coordinators["rv"], RAIN_EVENTS_SENSOR))
    else:
        registry = er.async_get(hass)
        if entity_id := registry.async_get_entity_id(
            "sensor", DOMAIN, unique_id_for(entry.entry_id, RAIN_EVENTS_SENSOR.key)
        ):
            registry.async_remove(entity_id)

    # Changing the source reloads the entry, so binding once at setup is enough.
    # The unique id does not depend on it, so the entity and its persisted
    # dry_since survive a switch. RW counts its 10-minute runs: as strongly
    # gauge-adjusted as the hourly run, and a reset shows up to an hour sooner.
    if options.unknown_dry_streak_source is not None:
        _LOGGER.warning(
            "Unknown dry streak source %r in the options of %s; counting %r "
            "instead. Saving the options again fixes it",
            options.unknown_dry_streak_source,
            entry.title,
            options.dry_streak_source,
        )
    entities.append(
        TimespanWithoutPrecipitationSensor(
            coordinators[options.dry_streak_coordinator_key],
            _PAST_HOUR_KEY[options.dry_streak_coordinator_key],
            hourly=coordinators.get("rw"),
            daily=coordinators.get("sf"),
        )
    )

    async_add_entities(entities)


class PrecipitationSensorEntity(DwdCoordinatorEntity, SensorEntity):
    """Implementation of a precipitation sensor."""

    entity_description: PrecipitationSensorEntityDescription

    # The per-lead forecast series would bloat the recorder history, and the
    # windows move with every release: each would be a new attribute row every
    # 5 minutes, while what they say follows from the release time.
    _unrecorded_attributes = frozenset(
        {"forecast_5min", "forecast_rolling_1h", "window_start", "window_end"}
    )

    @property
    def native_value(self) -> float | datetime | str | None:
        """Return the state of the sensor."""
        return self._value()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return companion values and, when enabled, diagnostic metadata."""
        if self.coordinator.data is None:
            return {}

        # Companion attributes (e.g. the start/end representation not used as
        # the state) are a feature, so they are always exposed.
        attrs = self._described_attributes()

        # Diagnostic metadata is opt-in via the integration options.
        if not self.coordinator.options.extra_state_attributes:
            return attrs

        if (metadata := self._metadata()) is None:
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


class RainEventsSensor(DwdCoordinatorEntity, SensorEntity):
    """The rain-event tracker's view: nearest status as state, view as attributes.

    The attributes are the schema-1 contract with blueprints (README "Rain
    events"), a few KB that change every release, so none is recorded.
    """

    _unrecorded_attributes = frozenset(VIEW_KEYS)

    def _view(self) -> dict[str, Any] | None:
        """Return the tracker's view of the latest release, if it has one."""
        if self.coordinator.data is None or self.coordinator.data.data is None:
            return None

        return self.coordinator.data.data.get("rain_events")

    @property
    def native_value(self) -> str | None:
        """Return ongoing, upcoming or none; unknown if the tracker failed."""
        view = self._view()
        return None if view is None else overall_status(view)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the view: the events, their steps and the last ended one."""
        return dict(self._view() or {})


class PrecipitationTotalSensor(DwdCoordinatorEntity, RestoreEntity, SensorEntity):
    """Running total of a RADOLAN accumulation product, one release at a time.

    Counts every release once, keyed on its timestamp (see precipitation_total).
    The first release seen after setup only sets the starting point: its window
    predates the sensor, so the total starts at 0. After a gap -- Home Assistant
    was down, or DWD failed for longer than a release -- the missed releases go
    on a pending list that is stored with the total, and are fetched in the
    background and added as they arrive. A release leaves the list only once it
    is added, so neither a restart nor a failed fetch loses it: what is left is
    tried again at startup and with every new release, until it is too old for
    OpenData to still serve.
    """

    entity_description: PrecipitationTotalEntityDescription

    def __init__(
        self,
        coordinator: BaseProductUpdateCoordinator,
        description: PrecipitationTotalEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description)
        # A counted release always has a total: _last_release is set only
        # together with _total (async_added_to_hass keeps that for a damaged
        # restore payload too).
        self._total: float | None = None
        self._last_release: datetime | None = None
        self._pending: list[datetime] = []
        self._backfilling = False

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
        return {"counted_until": iso(self._last_release)}

    @property
    def extra_restore_state_data(self) -> PrecipitationTotalExtraData:
        """Return the total, and what is still missing from it, to persist."""
        return PrecipitationTotalExtraData(
            total=self._total,
            last_release=self._last_release,
            pending=list(self._pending),
        )

    async def async_added_to_hass(self) -> None:
        """Restore the total and count whatever was released in the meantime."""
        await super().async_added_to_hass()

        if (restored := await self.async_get_last_extra_data()) is not None:
            self._restore(PrecipitationTotalExtraData.from_dict(restored.as_dict()))

        # coordinator.data is already populated by the first refresh.
        self._count_new_release()
        # Resume a backfill a restart interrupted, even with no new release.
        self._start_backfill()

    def _restore(self, data: PrecipitationTotalExtraData) -> None:
        """Adopt a restored total, on the product's current release grid."""
        self._total = data.total
        if data.total is None or data.last_release is None:
            return  # Without a total, nothing was counted: start over.

        self._last_release = counted_on_grid(self.coordinator.grid, data.last_release)
        self._pending = data.pending

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

        if self._last_release is None:
            # First release ever seen: it fixes the starting point only.
            self._total = self._total or 0.0
            self._last_release = release
            return

        missed, lost = missed_releases(
            self.coordinator.grid,
            self._last_release,
            release,
            self.entity_description.max_backfill,
        )
        if lost:
            _LOGGER.info(
                "%s: the DWD releases from %s to %s were missed and are too old "
                "to fetch now, so the total leaves them out",
                self.entity_id,
                lost[0].isoformat(),
                lost[1].isoformat(),
            )

        if (value := countable(cdata.data.get(KEY_AMOUNT))) is not None:
            self._total = (self._total or 0.0) + value
        self._last_release = release
        self._pending = sorted(set(self._pending) | set(missed))

        # A new release means DWD is serving again: retry what is missing.
        self._start_backfill()

    @callback
    def _start_backfill(self) -> None:
        """Give up on releases too old to fetch, and fetch the rest."""
        if self._last_release is None:
            return

        self._pending, gone = split_fetchable(
            self.coordinator.grid,
            self._pending,
            self._last_release,
            self.entity_description.max_backfill,
        )
        if gone:
            _LOGGER.info(
                "%s: %s missed DWD release(s) from %s to %s could not be "
                "fetched while DWD still served them, so the total leaves "
                "them out",
                self.entity_id,
                len(gone),
                gone[0].isoformat(),
                gone[-1].isoformat(),
            )

        if not self._pending or self._backfilling:
            return

        self._backfilling = True
        self.coordinator.config_entry.async_create_background_task(
            self.hass,
            self._async_backfill(),
            f"{self.entity_id} backfill",
        )

    async def _async_backfill(self) -> None:
        """Fetch the pending releases, oldest first, and add them to the total.

        Each is tried once per round, including any that join the list while
        the round runs. A release leaves the list only once it is fetched; a
        failure stays for the next round.
        """
        tried: set[datetime] = set()
        failed = 0
        added = False
        try:
            while todo := [r for r in self._pending if r not in tried]:
                release = todo[0]
                tried.add(release)
                try:
                    fetched = await self.coordinator.async_fetch_release(release)
                    value = fetched.data.get(KEY_AMOUNT)
                except Exception as err:  # noqa: BLE001 - retried next round
                    _LOGGER.debug(
                        "%s: could not backfill %s: %s",
                        self.entity_id,
                        release.isoformat(),
                        err,
                    )
                    failed += 1
                    continue

                if release not in self._pending:
                    continue  # given up on while it was being fetched
                self._pending.remove(release)
                if (mm := countable(value)) is not None:
                    self._total = (self._total or 0.0) + mm
                    added = True
        finally:
            self._backfilling = False
            # One state write per round, not one per release: a restart after
            # two days down backfills 48 releases.
            if added:
                self.async_write_ha_state()

        if failed:
            _LOGGER.debug(
                "%s: %s missed DWD release(s) could not be fetched yet; they "
                "are retried with the next release",
                self.entity_id,
                failed,
            )


# Where each dry-streak source keeps its past-hour total.
_PAST_HOUR_KEY = {"rs": KEY_LAST_60, RW_SLIDING_KEY: KEY_AMOUNT}


DRY_STREAK_SENSOR = SensorEntityDescription(
    key="timespan_without_precipitation",
    translation_key="timespan_without_precipitation",
    icon="mdi:weather-sunny",
    device_class=SensorDeviceClass.DURATION,
    native_unit_of_measurement=UnitOfTime.DAYS,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=2,
)


class TimespanWithoutPrecipitationSensor(
    DwdCoordinatorEntity, RestoreEntity, SensorEntity
):
    """Number of days since precipitation last reached the reset threshold.

    Counts elapsed time since an anchor (``dry_since``). The anchor is re-set
    whenever the past-hour total of the dry-streak source (RW or RS ``_000``,
    see ``CONF_DRY_STREAK_SOURCE``) reaches the configurable threshold, and
    stands otherwise, so the value grows continuously while it stays dry and
    drops back to ~0 when it rains. The anchor is persisted across restarts and
    corrected on startup against the RW/SF accumulation products to catch rain
    during downtime.
    """

    def __init__(
        self,
        coordinator: BaseProductUpdateCoordinator,
        sub_key: str,
        hourly: BaseProductUpdateCoordinator | None = None,
        daily: BaseProductUpdateCoordinator | None = None,
    ) -> None:
        """Initialize the sensor, bound to the dry-streak source's coordinator.

        Availability follows the source's staleness deadline, like every other
        entity (DwdCoordinatorEntity.available).
        """
        super().__init__(coordinator, DRY_STREAK_SENSOR)
        self._dry_since: datetime | None = None
        # Where the source keeps its past-hour total (see _PAST_HOUR_KEY).
        self._sub_key = sub_key
        # The analyses that correct the anchor for rain during downtime:
        # RW's last clock hour and SF's last 24 h, whatever the source.
        self._hourly = hourly
        self._daily = daily

    @property
    def _threshold(self) -> float:
        """Return the configured rain reset threshold in mm."""
        return self.coordinator.options.precipitation_reset_threshold

    def _reading(self) -> tuple[Any, ProductMetadata | None]:
        """Return the source's past-hour total and its metadata, unconverted.

        Either part is None when the coordinator has nothing.
        """
        cdata = self.coordinator.data
        if cdata is None:
            return None, None

        return cdata.data.get(self._sub_key), cdata.metadata.get(self._sub_key)

    def _precip_now(self) -> float | None:
        """Return the source's latest past-hour total (mm), or None if unavailable."""
        value, _ = self._reading()
        if value is None:
            return None

        value = float(value)

        return None if value != value else value  # drop NaN

    def _measurement_time(self) -> datetime:
        """Return the end of the source's hour, falling back to utcnow()."""
        _, meta = self._reading()
        if (ts := getattr(meta, "source_timestamp", None)) is not None:
            return ts  # UTC-aware

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
        rw = amount_reading(self._hourly)
        sf = amount_reading(self._daily)

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
