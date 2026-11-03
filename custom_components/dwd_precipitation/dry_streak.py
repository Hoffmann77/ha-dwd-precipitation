"""Domain logic for the "Timespan without precipitation" dry-streak sensor.

Holds the persisted-anchor payload and the pure helpers that decide where the
dry-streak anchor should sit. Kept separate from ``sensor.py`` so the streak
logic is easy to read and unit-test in isolation.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from homeassistant.helpers.restore_state import ExtraStoredData

from .const import KEY_AMOUNT
from .release_grid import ReleaseGrid
from .radar.isotime import iso, parse_utc

# Every dry-streak source reports a rolling hour: a reading covers the hour
# before its timestamp.
SOURCE_WINDOW = timedelta(hours=1)


class Reading(NamedTuple):
    """A RADOLAN analysis at the location: its amount (mm) and its window."""

    value: float | None
    start: datetime | None
    end: datetime | None


NO_READING = Reading(None, None, None)


@dataclass
class DryStreakExtraData(ExtraStoredData):
    """Persisted anchor for the days-without-rain sensor, how far the streak
    has watched, and the RW hours still to check for a gap.

    """

    dry_since: datetime | None
    watched_until: datetime | None = None
    gap_hours: list[datetime] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Serialize the anchor for restore_state.

        The anchor (``dry_since``) is the time the dry streak counts from,
        normally the end of the last hour that reached the reset threshold.
        ``watched_until`` is the end of the newest hour the streak has seen,
        ``gap_hours`` the RW releases still to be fetched for time it has not
        (see unwatched_hours). Home Assistant stores this dict with the
        entity's last state and hands it back after a restart (see from_dict),
        so the streak survives restarts, and a downtime counts as a gap.

        """
        return {
            "dry_since": iso(self.dry_since),
            "watched_until": iso(self.watched_until),
            "gap_hours": [iso(release) for release in self.gap_hours],
        }

    @classmethod
    def from_dict(cls, restored: dict[str, Any]) -> "DryStreakExtraData":
        """Rebuild the anchor from a restored dict.

        The counterpart of as_dict. A missing or unreadable timestamp restores
        as None (or is dropped from ``gap_hours``); a None anchor is treated
        like a fresh install, and a None ``watched_until`` (stored before
        2026.11.0) starts watching at the next reading. A timestamp without a
        time zone is taken as UTC.

        """
        return cls(
            dry_since=parse_utc(restored.get("dry_since")),
            watched_until=parse_utc(restored.get("watched_until")),
            gap_hours=sorted(
                ts
                for raw in restored.get("gap_hours") or ()
                if (ts := parse_utc(raw)) is not None
            ),
        )


def amount_reading(coordinator: Any) -> Reading:
    """Return a RADOLAN coordinator's amount and window.

    ``coordinator`` is the entry's RW (last hour) or SF (last 24 hours)
    coordinator, or None when the entry has none. Used at startup to look for
    rain that fell during a downtime. Returns NO_READING when the coordinator,
    its data or the amount is missing, so callers need only check the fields.

    """
    return release_reading(getattr(coordinator, "data", None) if coordinator else None)


def release_reading(cdata: Any) -> Reading:
    """Return the amount and window of one RADOLAN release's CoordinatorData.

    What amount_reading reads from a coordinator's current release, for a
    release fetched on its own (an RW hour fetched for a gap, see
    unwatched_hours). NO_READING when ``cdata`` or its amount is missing.

    """
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
    """Return when rain was last proven, to move a restored anchor forward.

    Used only at startup, to catch rain that fell while Home Assistant was down
    and the streak was not watching. RW's last hour is checked first: if it
    reached the threshold, the streak starts at that hour's end. Otherwise SF's
    last 24 hours: if they did, the streak starts at the start of that window,
    since SF cannot say when within the day it rained. None when neither
    reached the threshold.

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
    """Return where a new install's dry streak starts.

    A new install has no history, so the streak starts as far back as the
    analyses prove it was dry: the start of SF's 24 hours if they stayed below
    the threshold, else the start of RW's hour if it did, else now. Without it,
    every new install would report 0 days even after a dry week.

    """
    if sf.value is not None and sf.value < threshold and sf.start:
        return sf.start  # dry for at least the 24h SF window

    if rw.value is not None and rw.value < threshold and rw.start:
        return rw.start  # dry for at least the last hour

    return now


def unwatched_hours(
    grid: ReleaseGrid, watched_until: datetime, reading_end: datetime
) -> list[datetime]:
    """Return the RW clock hours that overlap time the streak did not watch.

    ``watched_until`` is the end of the newest hour the streak has seen;
    ``reading_end`` the end of the source's new reading, which covers the hour
    before it. When that hour starts after ``watched_until``, the stretch
    between was not watched: the source had no data for the location, DWD
    failed, or Home Assistant was down. A shorter gap needs nothing, since the
    new reading's hour covers it. ``grid`` is RW's: the result are its
    releases (each the end of its clock hour) whose hour overlaps the stretch,
    oldest first, for the sensor to fetch and compare against the threshold.

    """
    if reading_end - SOURCE_WINDOW <= watched_until:
        return []

    first = grid.next_after(grid.at_or_before(watched_until))

    return grid.walk(first, reading_end)
