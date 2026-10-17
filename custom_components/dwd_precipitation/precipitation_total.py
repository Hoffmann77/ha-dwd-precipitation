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

from .release_grid import ReleaseGrid
from .radar.isotime import iso, parse_utc


@dataclass
class PrecipitationTotalExtraData(ExtraStoredData):
    """Persisted running total, the newest release counted in it, and the
    older releases still missing from it (to be fetched and added).

    """

    total: float | None
    last_release: datetime | None
    pending: list[datetime] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Serialize the total for restore_state.

        The total (mm), the newest release counted in it and the older releases
        still to be fetched and added (``pending``), with the timestamps as ISO
        strings. Home Assistant stores this with the entity's state and hands
        it back after a restart (see from_dict).

        """
        return {
            "total": self.total,
            "last_release": iso(self.last_release),
            "pending": [iso(release) for release in self.pending],
        }

    @classmethod
    def from_dict(cls, restored: dict[str, Any]) -> "PrecipitationTotalExtraData":
        """Rebuild the total from a restored dict, forcing UTC-awareness.

        The counterpart of as_dict. A timestamp that cannot be read is dropped
        (or restores as None), and a total stored before ``pending`` existed
        restores with an empty list.

        """
        total = restored.get("total")

        return cls(
            total=float(total) if total is not None else None,
            last_release=parse_utc(restored.get("last_release")),
            pending=sorted(
                ts
                for raw in restored.get("pending") or ()
                if (ts := parse_utc(raw)) is not None
            ),
        )


def countable(value: Any) -> float | None:
    """Return a reading as mm to add to the total, or None if it is unusable.

    ``value`` is the amount a release reported for the location. None and NaN
    mark a cell without data (outside radar coverage, a radar outage); such a
    release adds nothing. Negative values cannot be rain, and adding one would
    make a TOTAL_INCREASING sensor look like it was reset.

    """
    if value is None:
        return None

    value = float(value)
    if math.isnan(value) or value < 0:
        return None

    return value


def counted_on_grid(grid: ReleaseGrid, last_counted: datetime) -> datetime:
    """Return the release on ``grid`` that a stored ``last_counted`` stands for.

    A release on the grid stands for itself. One from an older grid (RW's HH:50
    run, before 2026.10.1) maps to the new-grid release before the first window
    wholly after it, so ten minutes are left out once instead of fifty counted
    twice (ADR 0002). Applied once, when the total is restored, so the counting
    continues on the current grid.

    """
    if grid.at_or_before(last_counted) == last_counted:
        return last_counted

    return grid.at_or_before(grid.next_after(last_counted))


def missed_releases(
    grid: ReleaseGrid,
    last_counted: datetime,
    current: datetime,
    limit: int,
) -> tuple[list[datetime], tuple[datetime, datetime] | None]:
    """Return the uncounted releases still fetchable, and the stretch that is not.

    The releases after ``last_counted`` and before ``current`` were missed:
    Home Assistant was down, or the product failed. Only the ``limit`` newest
    are still on OpenData, so only they come back, oldest first, for the sensor
    to fetch and add. An older stretch comes back as its (first, last) release,
    for the caller to log; None when nothing is lost. Walked on the grid, so a
    DST day counts as one release.

    """
    first = grid.next_after(last_counted)
    oldest = grid.back(current, limit)
    lost = (first, grid.previous(oldest)) if first < oldest else None

    return grid.walk(max(first, oldest), current), lost


def split_fetchable(
    grid: ReleaseGrid,
    pending: list[datetime],
    current: datetime,
    limit: int,
) -> tuple[list[datetime], list[datetime]]:
    """Split pending releases into (still fetchable, given up), oldest first.

    ``pending`` are missed releases not yet added. Fetchable means among the
    ``limit`` releases before ``current``: the same window missed_releases
    draws from, and what DWD keeps on OpenData. Anything older can no longer be
    fetched, so the sensor drops it and logs it once. Counted on the grid, so a
    local-time product's DST days count as one release each.

    """
    oldest = grid.back(current, limit)
    releases = sorted(set(pending))

    return (
        [r for r in releases if r >= oldest],
        [r for r in releases if r < oldest],
    )
