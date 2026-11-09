"""The service's scheduler: one loop, jobs on fixed grids of UTC time.

Every job is a catch-up (it works out from the database what is missing), so
the scheduler only has to call each one now and then: once at start-up, then
on its grid. A job that raises is logged and called again on its next turn;
it never stops the loop.

"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


@dataclass
class Job:
    """A job and the grid it runs on: every ``interval``, ``offset`` past it."""

    name: str
    run: Callable[[], object]
    interval: timedelta
    offset: timedelta = timedelta()

    def next_after(self, now: datetime) -> datetime:
        """Return the job's first grid time strictly after ``now`` (UTC)."""
        step = self.interval.total_seconds()
        base = now.timestamp() - self.offset.total_seconds()
        k = int(base // step) + 1
        return datetime.fromtimestamp(k * step + self.offset.total_seconds(), UTC)


def touch(path: Path) -> None:
    """Write the current time to the heartbeat file the healthcheck reads."""
    path.write_text(f"{time.time():.0f}\n")


def run_forever(
    jobs: list[Job],
    stop: threading.Event,
    heartbeat: Path,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Run every job once, then each on its grid, until ``stop`` is set."""
    due = {job.name: clock() for job in jobs}
    while not stop.is_set():
        touch(heartbeat)
        now = clock()
        for job in jobs:
            if stop.is_set():
                break
            if due[job.name] > now:
                continue
            try:
                job.run()
            except Exception:
                _LOGGER.exception("%s job failed; retried on its next turn", job.name)
            touch(heartbeat)
            due[job.name] = job.next_after(clock())
        wait = (min(due.values()) - clock()).total_seconds()
        # Wake at least every minute, so the heartbeat stays fresh while idle.
        stop.wait(timeout=min(max(wait, 0.0), 60.0))
