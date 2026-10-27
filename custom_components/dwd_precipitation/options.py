"""The options of a config entry, read in one place.

Every option's key and default live in DEFAULT_OPTIONS; DwdOptions is the
typed snapshot every consumer reads, with one field per key, named like it.
A snapshot is enough: changing an option reloads the entry, so a
coordinator or entity never outlives the options it was built with.

Rain warnings are config subentries, read the same way: DEFAULT_RAIN_WARNING
holds every field's default and rain_warning_rule() the typed rule. Adding,
changing or removing one reloads the entry too.

"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry

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
    CONF_COMBINE,
    CONF_LEAD_TIME,
    CONF_MIN_MM,
    CONF_MIN_PEAK_10MIN,
    CONF_MIN_PEAK_1H,
    SUBENTRY_RAIN_WARNING,
)
from .radar.rain_warning import COMBINE_ANY, COMBINES, WarningRule

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


# Every field of a rain-warning subentry, with the value one without it gets.
# The minimums are optional: None (or absent) means not asked for.
DEFAULT_RAIN_WARNING: dict[str, Any] = {
    CONF_LEAD_TIME: 30,
    CONF_MIN_MM: None,
    CONF_MIN_PEAK_1H: None,
    CONF_MIN_PEAK_10MIN: None,
    CONF_COMBINE: COMBINE_ANY,
}


def rain_warning_rule(data: Mapping[str, Any]) -> WarningRule:
    """Read a rain-warning subentry's data, with the defaults for the rest.

    ``data`` is the subentry's ``data`` mapping as the subentry flow saved it.
    Every key of DEFAULT_RAIN_WARNING becomes a field of the rule. A combine
    value no version wrote counts as the default.

    """
    values = {key: data.get(key, default) for key, default in DEFAULT_RAIN_WARNING.items()}
    values[CONF_LEAD_TIME] = int(values[CONF_LEAD_TIME])
    for key in (CONF_MIN_MM, CONF_MIN_PEAK_1H, CONF_MIN_PEAK_10MIN):
        if values[key] is not None:
            values[key] = float(values[key])
    if values[CONF_COMBINE] not in COMBINES:
        values[CONF_COMBINE] = DEFAULT_RAIN_WARNING[CONF_COMBINE]
    return WarningRule(**values)


def rain_warning_subentries(entry: ConfigEntry) -> list[ConfigSubentry]:
    """Return the entry's rain-warning subentries, in the order they were added."""
    return [
        subentry
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_RAIN_WARNING
    ]


def tracks_rain_events(entry: ConfigEntry, options: DwdOptions) -> bool:
    """Return whether the entry runs the rain-events tracker.

    For the Rain events sensor (the option) or for any rain warning, which
    filters its view. Without either there is no tracker, no fill requests
    and no store. Adding or removing a warning reloads the entry, like an
    option change, so asking once at setup is enough.

    """
    return options.rain_events or bool(rain_warning_subentries(entry))

