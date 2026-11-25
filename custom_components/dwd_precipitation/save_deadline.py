"""SaveDeadline: when an entry's stores write what is not urgent.

Home Assistant's Store.async_delay_save restarts its timer on every call. A
store that calls it with every release (RV every 5 minutes, RW every hour)
therefore never writes on a long delay: the timer is pushed back each time,
and the data reaches the disk only when Home Assistant stops. A crash or power
cut then loses everything since the last start.

A SaveDeadline fixes the moment instead. The first idle save sets a due time
IDLE_SAVE_DELAY ahead, and every later one is scheduled for the time that is
left, so the data is updated but the write is not postponed. One deadline is
shared by all stores of an entry (the rain-events tracker, the hourly
history), so they write at the same moments rather than each on its own
clock: four times a day, plus whatever a store writes sooner because
something is at stake.

"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

# How long a store may hold data it has not written, at most.
IDLE_SAVE_DELAY = timedelta(hours=6)


class SaveDeadline:
    """A fixed idle-save time that an entry's stores share."""

    def __init__(self, delay: timedelta = IDLE_SAVE_DELAY) -> None:
        """Start without a due time; the first idle save sets one."""
        self._delay = delay
        self._due: datetime | None = None

    def seconds_left(self, now: datetime | None = None) -> float:
        """Return how long until the due time, starting a new one if it passed.

        ``now`` defaults to the current time. A due time that has passed was
        the moment every store with pending data wrote it, so the next idle
        save starts a new period.

        """
        now = now if now is not None else dt_util.utcnow()
        if self._due is None or self._due <= now:
            self._due = now + self._delay
        return (self._due - now).total_seconds()

    def delay_save(self, store: Store, data_func: Callable[[], Any]) -> None:
        """Schedule ``store`` to write ``data_func()`` at the due time.

        Replaces whatever the store had scheduled, as async_delay_save always
        does, but keeps the moment: a later call does not move it.

        """
        store.async_delay_save(data_func, self.seconds_left())
