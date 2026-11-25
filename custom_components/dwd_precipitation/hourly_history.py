"""The hourly precipitation history: the entry's RW hours, kept and filled.

RW releases one clock hour of gauge-adjusted rain per file, and "Precipitation
previous hour" shows only the newest. Blueprints that judge rain over several
hours (DWD's continuous-rain warnings reach 72 h) need the hours before it,
and cannot keep them reliably themselves: a template sensor misses every hour
Home Assistant was down.

So the RW coordinator keeps them. Every hour it reads is recorded, whoever
asked for it: the release it adopts, and every past hour fetched through it
(the total's backfill, the dry streak's gap check). With the fetch option on,
the history also fetches the hours it is missing itself, as far back as
OpenData keeps them (RW_KEPT), and every other fetch of an hour it already
holds is answered from it instead of downloaded again.

Kept in a Store per entry; idle data is written at the entry's SaveDeadline,
and at once after a round that fetched hours, since refetching 47 files after
a second crash would cost more than one write.

"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN, RW_KEPT
from .radar.isotime import iso, parse_utc
from .release_grid import ReleaseGrid
from .save_deadline import SaveDeadline
from .utils import FailureLatch

_LOGGER = logging.getLogger(__name__)

HOURLY_HISTORY_STORE_VERSION = 1

# How soon the history is written after a round that fetched hours.
HOURLY_HISTORY_FILL_SAVE_DELAY = timedelta(seconds=10)


def hourly_history_store(hass: HomeAssistant, entry_id: str) -> Store:
    """Return the Store of one config entry's hourly history.

    The one place it is built, so the history and the clean-up on option-off
    and entry removal use the same key and version.

    """
    return Store(
        hass, HOURLY_HISTORY_STORE_VERSION, f"{DOMAIN}.{entry_id}.hourly_history"
    )


@dataclass
class HourlyHistoryState:
    """The RW hours held, by the end of each hour (UTC).

    A value is the hour's mm, or None when DWD's file had no data for the
    cell. An hour not in ``hours`` was never obtained.

    """

    hours: dict[datetime, float | None] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the hours as JSON-ready data for the Store, oldest first."""
        return {"hours": {iso(t): mm for t, mm in sorted(self.hours.items())}}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> HourlyHistoryState:
        """Rebuild the hours saved by :meth:`as_dict`.

        Raises ValueError for anything that is not an hour end with a number
        or None, so a damaged store is discarded as a whole rather than half
        read.

        """
        hours = raw.get("hours")
        if not isinstance(hours, dict):
            raise ValueError("hours is not a mapping")
        out: dict[datetime, float | None] = {}
        for raw_end, mm in hours.items():
            if (end := parse_utc(raw_end)) is None:
                raise ValueError(f"unreadable hour {raw_end!r}")
            if mm is not None and (isinstance(mm, bool) or not isinstance(mm, (int, float))):
                raise ValueError(f"hour amount {mm!r}")
            out[end] = mm
        return cls(out)


def hour_window(grid: ReleaseGrid, latest: datetime, kept: int) -> list[datetime]:
    """Return the ends of the ``kept`` hours up to ``latest``, oldest first.

    ``latest`` is an RW release on ``grid``: the end of the newest hour the
    window holds.

    """
    return [grid.back(latest, k) for k in range(kept - 1, -1, -1)]


def missing_hours(
    state: HourlyHistoryState, grid: ReleaseGrid, latest: datetime, kept: int
) -> list[datetime]:
    """Return the hours of the window up to ``latest`` not held, oldest first."""
    return [t for t in hour_window(grid, latest, kept) if t not in state.hours]


def hours_to_fetch(
    state: HourlyHistoryState, grid: ReleaseGrid, latest: datetime, kept: int
) -> list[datetime]:
    """Return the missing hours OpenData still keeps, newest first.

    ``latest`` is the newest RW release published. Newest first, so an hour
    DWD deleted a little early at the old end cannot hold up the rest.

    """
    oldest = grid.back(latest, RW_KEPT)
    return [t for t in reversed(missing_hours(state, grid, latest, kept)) if t >= oldest]


class HourlyHistory:
    """Keep one entry's RW hours across releases and restarts."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        grid: ReleaseGrid,
        hours_kept: int,
        fetch: Callable[[datetime], Awaitable[float | None]] | None,
        store: Store | None = None,
    ) -> None:
        """Set up the history; nothing is loaded before it is first used.

        ``grid`` is RW's release grid, ``hours_kept`` the hourly_history_hours
        option, and ``fetch`` downloads one past hour's amount for the
        location (None when the fetch option is off: then only hours read
        anyway are kept). The history is written once more when the entry
        unloads, so a reload reads it back.

        """
        self._hass = hass
        self._entry = entry
        self.grid = grid
        self.hours_kept = hours_kept
        self._fetch = fetch
        self.store = store if store is not None else hourly_history_store(hass, entry.entry_id)
        # Setup replaces it with the one the entry's other stores share.
        self.save_deadline = SaveDeadline()
        self.state: HourlyHistoryState | None = None
        self._load_lock = asyncio.Lock()
        self._listeners: list[CALLBACK_TYPE] = []
        self.fill_task: asyncio.Task | None = None
        self._fill_latch = FailureLatch()
        entry.async_on_unload(self.async_save)

    @staticmethod
    async def async_remove(hass: HomeAssistant, entry_id: str) -> None:
        """Delete an entry's stored history (option turned off, entry removed)."""
        await hourly_history_store(hass, entry_id).async_remove()

    @callback
    def async_add_listener(self, update: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Call ``update`` whenever hours join outside an RW update; return the undo."""
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def _notify(self) -> None:
        """Tell the listeners (the sensor) that the history changed."""
        for update in list(self._listeners):
            update()

    async def async_state(self) -> HourlyHistoryState:
        """Return the history, loading it from the store on first use.

        A store that cannot be read is discarded with a warning: the hours
        OpenData still keeps are fetched again, the older ones stay missing.

        """
        async with self._load_lock:
            if self.state is None:
                self.state = await self._async_load()
        return self.state

    async def _async_load(self) -> HourlyHistoryState:
        """Read the history from the store; an empty one if it cannot be read."""
        try:
            raw = await self.store.async_load()
            return HourlyHistoryState.from_dict(raw) if raw else HourlyHistoryState()
        except Exception as err:  # noqa: BLE001 - any unreadable store
            _LOGGER.warning(
                "Discarding the saved hourly precipitation history, which could "
                "not be read (%s). Hours DWD still serves are fetched again",
                err or type(err).__name__,
            )
            return HourlyHistoryState()

    async def async_lookup(self, hour: datetime) -> tuple[bool, float | None]:
        """Return whether ``hour`` is held, and its amount (None: no data)."""
        state = await self.async_state()
        return hour in state.hours, state.hours.get(hour)

    async def async_record(self, hour: datetime, mm: float | None) -> None:
        """Keep the amount of the RW hour ending ``hour`` (None: no data).

        For hours fetched outside an RW update (another sensor's backfill):
        the sensor is told, and the state saved at the deadline. Hours off
        the hourly grid, or older than the window, are not kept. Never raises.

        """
        try:
            if self._keep(await self.async_state(), hour, mm):
                self._schedule_save()
                self._notify()
        except Exception:  # noqa: BLE001 - a history failure must not fail a fetch
            _LOGGER.exception("Could not record RW hour %s in the hourly history", hour)

    async def async_on_release(self, release: datetime, mm: float | None) -> None:
        """Keep the release RW adopts, drop what left the window, fill the rest.

        Called by the RW coordinator before it publishes the release, so the
        sensor shows it with the update. Never raises.

        """
        try:
            state = await self.async_state()
            self._keep(state, release, mm)
            oldest = hour_window(self.grid, release, self.hours_kept)[0]
            state.hours = {t: v for t, v in state.hours.items() if t >= oldest}
            self._schedule_save()
            self._start_fill(state, release)
        except Exception:  # noqa: BLE001 - a history failure must not fail RW
            _LOGGER.exception("Could not update the hourly precipitation history")

    def _keep(self, state: HourlyHistoryState, hour: datetime, mm: float | None) -> bool:
        """Record ``hour`` if it is one the window can hold; return whether kept."""
        if self.grid.at_or_before(hour) != hour:
            return False
        if state.hours:
            newest = max(state.hours)
            if hour < hour_window(self.grid, newest, self.hours_kept)[0]:
                return False
        state.hours[hour] = mm
        return True

    def _schedule_save(self) -> None:
        """Write the history at the entry's idle-save deadline."""
        if self.state is not None:
            self.save_deadline.delay_save(self.store, self.state.as_dict)

    def _start_fill(self, state: HourlyHistoryState, latest: datetime) -> None:
        """Fetch the missing hours in the background, one round at a time.

        Only with the fetch option, and only hours OpenData still keeps. A
        round already running is left to finish; the next release starts
        another for what is still missing.

        """
        if self._fetch is None or (self.fill_task is not None and not self.fill_task.done()):
            return
        if not hours_to_fetch(state, self.grid, latest, self.hours_kept):
            return
        self.fill_task = self._entry.async_create_background_task(
            self._hass, self._async_fill(state, latest), "dwd_precipitation hourly history fill"
        )

    async def _async_fill(self, state: HourlyHistoryState, latest: datetime) -> None:
        """Fetch the missing hours, newest first; the first failure ends the round.

        A failure is logged once per run of failures; the next release retries.
        A round that added hours is written soon and shown at once.

        """
        assert self._fetch is not None
        added = False
        try:
            for hour in hours_to_fetch(state, self.grid, latest, self.hours_kept):
                try:
                    mm = await self._fetch(hour)
                except Exception as err:  # noqa: BLE001 - retried with the next release
                    _LOGGER.debug("Could not fetch RW %s for the hourly history: %s", hour, err)
                    if self._fill_latch.fail():
                        _LOGGER.info(
                            "Could not fetch the missed DWD RW hour ending %s for the "
                            "hourly precipitation history (%s). It stays missing and "
                            "is retried with the next RW release",
                            hour.strftime("%Y-%m-%d %H:%M UTC"),
                            err or type(err).__name__,
                        )
                    return
                state.hours[hour] = mm
                added = True
            self._fill_latch.ok()
        finally:
            if added:
                self.store.async_delay_save(
                    state.as_dict, HOURLY_HISTORY_FILL_SAVE_DELAY.total_seconds()
                )
                self._notify()

    async def async_save(self) -> None:
        """Write the history now (entry unload); nothing before it is loaded."""
        if self.state is not None:
            await self.store.async_save(self.state.as_dict())

    def view(self, latest: datetime | None) -> dict[str, Any]:
        """Return the sensor's attributes for the window ending ``latest``.

        ``latest`` is the newest RW hour due. ``hours`` holds the hours of the
        window obtained (mm, None for no data), ``missing`` the others, both
        oldest first; ``hours_kept`` is the window length.

        """
        out: dict[str, Any] = {"hours": {}, "missing": [], "hours_kept": self.hours_kept}
        if latest is None or self.state is None:
            return out
        held = self.state.hours
        for t in hour_window(self.grid, latest, self.hours_kept):
            if t in held:
                out["hours"][iso(t)] = held[t]
            else:
                out["missing"].append(iso(t))
        return out

    def newest_held(self) -> datetime | None:
        """Return the end of the newest hour held; None before the first."""
        if self.state is None or not self.state.hours:
            return None
        return max(self.state.hours)

    def newest(self, latest: datetime | None) -> datetime | None:
        """Return the end of the newest hour held in the window up to ``latest``."""
        if latest is None or self.state is None:
            return None
        oldest = hour_window(self.grid, latest, self.hours_kept)[0]
        held = [t for t in self.state.hours if oldest <= t <= latest]
        return max(held, default=None)
