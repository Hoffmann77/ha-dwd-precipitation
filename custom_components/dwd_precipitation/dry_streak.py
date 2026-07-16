"""Domain logic for the "days without rain" dry-streak sensor.

Holds the persisted-anchor payload and the pure helpers that decide where the
dry-streak anchor should sit. Kept separate from ``sensor.py`` so the streak
logic is easy to read and unit-test in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.helpers.restore_state import ExtraStoredData
from homeassistant.util import dt as dt_util


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


def scalar_reading(
    coordinator: Any,
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


def downtime_correction(
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


def fresh_anchor(
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
