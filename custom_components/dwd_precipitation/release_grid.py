"""The release grid of a DWD product: when its releases are nominally due.

HA-free and without relative imports, like rain_events.py, so that the parser
tier and scripts/check_release_delay.py import it as it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo

_TICK = timedelta(microseconds=1)


@dataclass(frozen=True)
class ReleaseGrid:
    """Releases at ``offset`` past every multiple of ``interval``, on ``tz``'s clock.

    The grid lives on the wall clock of ``tz`` rather than in UTC because a
    local-time product (sf_2350, 23:50 local) keeps its wall-clock time across
    DST: its releases are 23 or 25 hours apart on the two changeover days, and
    adding 24 h to a UTC timestamp would land an hour off. For an interval
    that divides a day the multiples fall on every midnight.

    Every timestamp passed in must be aware; every one returned is UTC.
    """

    interval: timedelta
    offset: timedelta = timedelta()
    tz: tzinfo = UTC

    def at_or_before(self, moment: datetime) -> datetime:
        """Return the newest release at or before ``moment``.

        A release maps to itself; a timestamp that does not is off the grid
        (one stored from an older grid, say: RW's HH:50).
        """
        wall = moment.astimezone(self.tz).replace(tzinfo=None)
        floor = wall - (wall - self.offset - datetime.min) % self.interval
        # A wall time that occurs twice (autumn) means its first occurrence.
        return floor.replace(tzinfo=self.tz, fold=0).astimezone(UTC)

    def next_after(self, release: datetime) -> datetime:
        """Return the release after the on-grid ``release``."""
        return (release.astimezone(self.tz) + self.interval).astimezone(UTC)

    def previous(self, release: datetime) -> datetime:
        """Return the release before the on-grid ``release``."""
        return self.at_or_before(release - _TICK)

    def back(self, release: datetime, steps: int) -> datetime:
        """Return the release ``steps`` releases before the on-grid ``release``."""
        for _ in range(steps):
            release = self.previous(release)
        return release

    def walk(self, first: datetime, end: datetime) -> list[datetime]:
        """Return the releases from the on-grid ``first`` up to (excluding) ``end``."""
        releases: list[datetime] = []
        while first < end:
            releases.append(first)
            first = self.next_after(first)
        return releases
