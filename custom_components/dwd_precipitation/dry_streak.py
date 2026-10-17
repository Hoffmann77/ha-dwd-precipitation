"""Domain logic for the "Timespan without precipitation" dry-streak sensor.

Holds the persisted-anchor payload and the pure helpers that decide where the
dry-streak anchor should sit. Kept separate from ``sensor.py`` so the streak
logic is easy to read and unit-test in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, NamedTuple

from homeassistant.helpers.restore_state import ExtraStoredData

from .const import KEY_AMOUNT
from .radar.isotime import iso, parse_utc


class Reading(NamedTuple):
    """A RADOLAN analysis at the location: its amount (mm) and its window."""

    value: float | None
    start: datetime | None
    end: datetime | None


NO_READING = Reading(None, None, None)


@dataclass
class DryStreakExtraData(ExtraStoredData):
    """Persisted anchor for the days-without-rain sensor."""

    dry_since: datetime | None

    def as_dict(self) -> dict[str, Any]:
        """Serialize the anchor for restore_state."""
        return {"dry_since": iso(self.dry_since)}

    @classmethod
    def from_dict(cls, restored: dict[str, Any]) -> "DryStreakExtraData":
        """Rebuild the anchor from a restored dict, forcing UTC-awareness."""
        return cls(dry_since=parse_utc(restored.get("dry_since")))


def amount_reading(coordinator: Any) -> Reading:
    """Return a RADOLAN coordinator's amount and window; NO_READING without data."""
    cdata = getattr(coordinator, "data", None) if coordinator else None
    if cdata is None or (value := cdata.data.get(KEY_AMOUNT)) is None:
        return NO_READING

    meta = cdata.metadata.get(KEY_AMOUNT)

    return Reading(
        float(value),
        getattr(meta, "data_start", None),
        getattr(meta, "data_end", None),
    )


def downtime_correction(
    threshold: float, rw: Reading, sf: Reading, now: datetime
) -> datetime | None:
    """Newest time we have positive rain evidence, to clamp a stale anchor forward.

    Used only at startup to catch rain that fell while HA was down. Returns a UTC
    datetime to clamp the anchor forward to, or None when there is no evidence.
    """
    if rw.value is not None and rw.value >= threshold:
        # Rain within the last hour -> the streak is effectively zero.
        return rw.end or now

    if sf.value is not None and sf.value >= threshold:
        # Rain within the last 24h (but not the last hour). We cannot pin the exact
        # time, so cap the streak at the start of the SF window (~24h ago).
        return sf.start or now

    return None


def fresh_anchor(threshold: float, rw: Reading, sf: Reading, now: datetime) -> datetime:
    """Anchor for a fresh install: the oldest time we can prove it has been dry."""
    if sf.value is not None and sf.value < threshold and sf.start:
        return sf.start  # dry for at least the 24h SF window

    if rw.value is not None and rw.value < threshold and rw.start:
        return rw.start  # dry for at least the last hour

    return now
