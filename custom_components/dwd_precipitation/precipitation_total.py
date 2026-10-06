"""Domain logic for the cumulative "Precipitation total" sensors.

A total adds up a RADOLAN accumulation product one release at a time: RW for an
hourly-updated total, sf_2350 for a daily one. Each release is a window that
starts where the previous one ended, so summing every release exactly once gives
the rain that fell over the whole period. The sensors are TOTAL_INCREASING, so
Home Assistant's long-term statistics and utility_meter turn them into daily,
monthly and yearly sums.

Everything is keyed on the release timestamp rather than on value changes: two
equally wet hours in a row are two releases and must both be counted, and a
release seen twice (a refresh, a restart) must be counted once.

Holds the persisted payload and the pure helpers; the entity lives in sensor.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.helpers.restore_state import ExtraStoredData
from homeassistant.util import dt as dt_util


@dataclass
class PrecipitationTotalExtraData(ExtraStoredData):
    """Persisted running total and the newest release already counted in it."""

    total: float | None
    last_release: datetime | None

    def as_dict(self) -> dict[str, Any]:
        """Serialize the total for restore_state."""
        return {
            "total": self.total,
            "last_release": (
                self.last_release.isoformat() if self.last_release else None
            ),
        }

    @classmethod
    def from_dict(cls, restored: dict[str, Any]) -> "PrecipitationTotalExtraData":
        """Rebuild the total from a restored dict, forcing UTC-awareness."""
        raw = restored.get("last_release")
        ts = dt_util.parse_datetime(raw) if raw else None
        if ts is not None and ts.tzinfo is None:
            ts = dt_util.as_utc(ts)

        total = restored.get("total")

        return cls(
            total=float(total) if total is not None else None,
            last_release=ts,
        )


def countable(value: Any) -> float | None:
    """Return a reading as mm to add to the total, or None if it is unusable.

    NaN marks a cell outside radar coverage. Negative values cannot be rain, and
    adding one would make a TOTAL_INCREASING sensor look like it was reset.
    """
    if value is None:
        return None

    value = float(value)
    if math.isnan(value) or value < 0:
        return None

    return value


def missed_releases(
    coordinator: Any,
    last_counted: datetime,
    current: datetime,
    limit: int,
) -> list[datetime]:
    """Return the releases strictly between last_counted and current, oldest first.

    These are the windows nobody counted: Home Assistant was down, or the
    product failed for longer than one release. Walked with the coordinator's
    own _next_release_after, so a local-time product steps over DST changeovers
    exactly as its schedule does. Only the newest ``limit`` are returned; older
    files are unlikely to still be on OpenData, and a long outage should not
    turn into a burst of downloads at startup.
    """
    missed: list[datetime] = []
    release = coordinator._next_release_after(last_counted)

    while release < current:
        missed.append(release)
        release = coordinator._next_release_after(release)

    return missed[-limit:] if limit > 0 else []
