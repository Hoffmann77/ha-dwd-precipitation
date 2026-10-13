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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.helpers.restore_state import ExtraStoredData
from homeassistant.util import dt as dt_util


@dataclass
class PrecipitationTotalExtraData(ExtraStoredData):
    """Persisted running total, the newest release counted in it, and the
    older releases still missing from it (to be fetched and added)."""

    total: float | None
    last_release: datetime | None
    pending: list[datetime] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Serialize the total for restore_state."""
        return {
            "total": self.total,
            "last_release": (
                self.last_release.isoformat() if self.last_release else None
            ),
            "pending": [release.isoformat() for release in self.pending],
        }

    @classmethod
    def from_dict(cls, restored: dict[str, Any]) -> "PrecipitationTotalExtraData":
        """Rebuild the total from a restored dict, forcing UTC-awareness.

        A total stored before ``pending`` existed restores with none.
        """
        total = restored.get("total")

        return cls(
            total=float(total) if total is not None else None,
            last_release=_parse_utc(restored.get("last_release")),
            pending=sorted(
                ts
                for raw in restored.get("pending") or ()
                if (ts := _parse_utc(raw)) is not None
            ),
        )


def _parse_utc(raw: Any) -> datetime | None:
    """Parse a stored ISO timestamp as an aware UTC datetime."""
    ts = dt_util.parse_datetime(raw) if isinstance(raw, str) else None
    if ts is not None and ts.tzinfo is None:
        ts = dt_util.as_utc(ts)

    return ts


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


def first_uncounted_release(coordinator: Any, last_counted: datetime) -> datetime:
    """Return the first release whose window starts at or after last_counted.

    Normally simply the release after it. If last_counted is off the product's
    grid, the grid moved under a stored total: RW went from the HH:50 run to
    the HH:00 one in 2026.10.1. The first new-grid release after it would
    overlap what is already counted (10:00-11:00 after 09:50-10:50), so the
    count resumes one release later. That leaves the minutes between the two
    grids out once (10:50-11:00), where the overlap would count 50 twice.
    """
    release = coordinator._next_release_after(last_counted)
    on_grid = coordinator._release_at_or_before(release)
    if on_grid == release:
        return release

    return coordinator._next_release_after(on_grid)


def missed_releases(
    coordinator: Any,
    last_counted: datetime,
    current: datetime,
    limit: int,
) -> list[datetime]:
    """Return the uncounted releases from last_counted up to current, oldest first.

    These are the windows nobody counted: Home Assistant was down, or the
    product failed for longer than one release. Walked with the coordinator's
    own _next_release_after, so a local-time product steps over DST changeovers
    exactly as its schedule does, starting at first_uncounted_release. Only the
    newest ``limit`` are returned; older files are unlikely to still be on
    OpenData, and a long outage should not turn into a burst of downloads at
    startup.
    """
    missed: list[datetime] = []
    release = first_uncounted_release(coordinator, last_counted)

    while release < current:
        missed.append(release)
        release = coordinator._next_release_after(release)

    return missed[-limit:] if limit > 0 else []


def split_fetchable(
    coordinator: Any,
    pending: list[datetime],
    current: datetime,
    limit: int,
) -> tuple[list[datetime], list[datetime]]:
    """Split pending releases into (still fetchable, given up), oldest first.

    Fetchable means among the ``limit`` releases before ``current`` -- the same
    window missed_releases draws from, and what DWD keeps on OpenData. Counted
    by walking the grid, so a local-time product's DST days count as one
    release each, like everywhere else.
    """
    keep: list[datetime] = []
    drop: list[datetime] = []
    for release in sorted(set(pending)):
        steps, walk = 0, release
        while walk < current and steps <= limit:
            walk = coordinator._next_release_after(walk)
            steps += 1
        (keep if steps <= limit else drop).append(release)

    return keep, drop
