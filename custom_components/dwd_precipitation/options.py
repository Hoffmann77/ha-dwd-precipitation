"""The options of a config entry, read in one place.

Every option's key and default live in DEFAULT_OPTIONS; DwdOptions is the
typed snapshot every consumer reads. A snapshot is enough: changing an
option reloads the entry, so a coordinator or entity never outlives the
options it was built with.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_DRY_STREAK_SOURCE,
    CONF_EXTRA_ATTRIBUTES,
    CONF_FULL_ROLLING_SERIES,
    CONF_PRECIPITATION_END_ALGORITHM,
    CONF_PRECIPITATION_RESET_THRESHOLD,
    CONF_PRECIPITATION_THRESHOLD,
    CONF_RAIN_EVENT_THRESHOLD,
    CONF_RAIN_EVENTS,
    CONF_START_END_MODE,
    CONF_UNAVAILABLE_WHEN_STALE,
    DEFAULT_DRY_STREAK_SOURCE,
    DEFAULT_EXTRA_ATTRIBUTES,
    DEFAULT_FULL_ROLLING_SERIES,
    DEFAULT_PRECIPITATION_END_ALGORITHM,
    DEFAULT_PRECIPITATION_RESET_THRESHOLD,
    DEFAULT_PRECIPITATION_THRESHOLD,
    DEFAULT_RAIN_EVENT_THRESHOLD,
    DEFAULT_RAIN_EVENTS,
    DEFAULT_START_END_MODE,
    DEFAULT_UNAVAILABLE_WHEN_STALE,
    DRY_STREAK_SOURCE_RW,
    DRY_STREAK_SOURCES,
    RW_SLIDING_KEY,
)

# Every option the form offers, with the value an entry without it gets.
DEFAULT_OPTIONS: dict[str, Any] = {
    CONF_EXTRA_ATTRIBUTES: DEFAULT_EXTRA_ATTRIBUTES,
    CONF_UNAVAILABLE_WHEN_STALE: DEFAULT_UNAVAILABLE_WHEN_STALE,
    CONF_PRECIPITATION_THRESHOLD: DEFAULT_PRECIPITATION_THRESHOLD,
    CONF_START_END_MODE: DEFAULT_START_END_MODE,
    CONF_PRECIPITATION_END_ALGORITHM: DEFAULT_PRECIPITATION_END_ALGORITHM,
    CONF_FULL_ROLLING_SERIES: DEFAULT_FULL_ROLLING_SERIES,
    CONF_RAIN_EVENTS: DEFAULT_RAIN_EVENTS,
    CONF_RAIN_EVENT_THRESHOLD: DEFAULT_RAIN_EVENT_THRESHOLD,
    CONF_PRECIPITATION_RESET_THRESHOLD: DEFAULT_PRECIPITATION_RESET_THRESHOLD,
    CONF_DRY_STREAK_SOURCE: DEFAULT_DRY_STREAK_SOURCE,
}

# DwdOptions field for each option key.
_FIELD_BY_KEY: dict[str, str] = {
    CONF_EXTRA_ATTRIBUTES: "extra_attributes",
    CONF_UNAVAILABLE_WHEN_STALE: "unavailable_when_stale",
    CONF_PRECIPITATION_THRESHOLD: "precipitation_threshold",
    CONF_START_END_MODE: "start_end_mode",
    CONF_PRECIPITATION_END_ALGORITHM: "precipitation_end_algorithm",
    CONF_FULL_ROLLING_SERIES: "full_rolling_series",
    CONF_RAIN_EVENTS: "rain_events",
    CONF_RAIN_EVENT_THRESHOLD: "rain_event_threshold",
    CONF_PRECIPITATION_RESET_THRESHOLD: "precipitation_reset_threshold",
    CONF_DRY_STREAK_SOURCE: "dry_streak_source",
}


@dataclass(frozen=True)
class DwdOptions:
    """One entry's options, each set (stored or default)."""

    extra_attributes: bool
    unavailable_when_stale: bool
    precipitation_threshold: float
    start_end_mode: str
    precipitation_end_algorithm: str
    full_rolling_series: bool
    rain_events: bool
    rain_event_threshold: float
    precipitation_reset_threshold: float
    dry_streak_source: str
    # A stored dry_streak_source no version wrote, replaced by the default;
    # sensor setup warns about it.
    unknown_dry_streak_source: Any = None

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> DwdOptions:
        """Read an entry's stored options, with the defaults for the rest."""
        values = {
            field: options.get(key, DEFAULT_OPTIONS[key])
            for key, field in _FIELD_BY_KEY.items()
        }
        if values["dry_streak_source"] not in DRY_STREAK_SOURCES:
            values["unknown_dry_streak_source"] = values["dry_streak_source"]
            values["dry_streak_source"] = DEFAULT_DRY_STREAK_SOURCE
        values["rain_events"] = bool(values["rain_events"])
        return cls(**values)

    @property
    def dry_streak_coordinator_key(self) -> str:
        """Return the key of the coordinator the dry streak counts.

        The source is a product key, except that RW counts its 10-minute
        runs. RadolanRW10.is_needed and the sensor setup both ask this, so
        the coordinator the sensor binds to is always one that was built.
        """
        if self.dry_streak_source == DRY_STREAK_SOURCE_RW:
            return RW_SLIDING_KEY
        return self.dry_streak_source

