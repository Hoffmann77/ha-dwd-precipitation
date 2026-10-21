"""The options of a config entry, read in one place.

Every option's key and default live in DEFAULT_OPTIONS; DwdOptions is the
typed snapshot every consumer reads, with one field per key, named like it.
A snapshot is enough: changing an option reloads the entry, so a
coordinator or entity never outlives the options it was built with.

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


@dataclass(frozen=True)
class DwdOptions:
    """One entry's options, each set (stored or default); fields named like the keys."""

    extra_state_attributes: bool
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
        """Read an entry's stored options, with the defaults for the rest.

        ``options`` is the entry's ``entry.options`` mapping, which holds only
        what the user (or a migration) saved. Every key of DEFAULT_OPTIONS
        becomes a field, taking the default when it is not stored. A dry-streak
        source no version wrote is replaced by the default and kept in
        ``unknown_dry_streak_source``, so sensor setup can warn about it.

        """
        values = {key: options.get(key, default) for key, default in DEFAULT_OPTIONS.items()}
        if values["dry_streak_source"] not in DRY_STREAK_SOURCES:
            values["unknown_dry_streak_source"] = values["dry_streak_source"]
            values["dry_streak_source"] = DEFAULT_DRY_STREAK_SOURCE
        values["rain_events"] = bool(values["rain_events"])
        return cls(**values)

    @property
    def dry_streak_coordinator_key(self) -> str:
        """Return the key of the coordinator the dry streak counts.

        The option's value is a product key ("rs" or "rw"), except that RW is
        counted from its 10-minute runs, which have their own coordinator
        ("rw_10min"). RadolanRW10.is_needed and the sensor setup both ask this,
        so the coordinator the sensor binds to is always one that was built.

        """
        if self.dry_streak_source == DRY_STREAK_SOURCE_RW:
            return RW_SLIDING_KEY
        return self.dry_streak_source

