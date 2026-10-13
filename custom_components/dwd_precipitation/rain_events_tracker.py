"""The rain-events tracker of one config entry: store, fill, track, publish.

radar/rain_events.py is the pure logic; this is its life in Home Assistant.
The RV coordinator hands it every release it adopts and lends it two things:
a way to fetch one missed analysis, and a way to publish a view that is ready
after the RV update (a background fill). Everything else, from the Store to
the save policy and the once-per-run warnings, lives here.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .radar.rain_events import (
    RainEventsState,
    at_stake,
    record_measured,
    steps_to_fill,
    update as update_rain_events,
    wet_step_milli,
)
from .utils import FailureLatch

_LOGGER = logging.getLogger(__name__)

RAIN_EVENTS_STORE_VERSION = 1

# One background round of filling missed analyses takes this long, at most.
RAIN_FILL_BUDGET = timedelta(seconds=30)

# How soon the state is written: promptly while an event or an unknown step is
# at stake, otherwise not before shutdown (see RainEventsTracker._schedule_save).
RAIN_SAVE_DELAY = timedelta(seconds=10)
RAIN_IDLE_SAVE_DELAY = timedelta(hours=12)


def rain_events_store_key(entry_id: str) -> str:
    """Return the Store key of one config entry's rain_events state."""
    return f"{DOMAIN}.{entry_id}.rain_events"


def rain_events_store(hass: HomeAssistant, entry_id: str) -> Store:
    """Return the Store of one config entry's rain_events state.

    The one place it is built, so a version bump (or a migration) reaches the
    tracker and the clean-up on option-off and entry removal alike.
    """
    return Store(hass, RAIN_EVENTS_STORE_VERSION, rain_events_store_key(entry_id))


def _describe_fill_failure(err: Exception, step_end: datetime) -> str:
    """Return the warning for a missed RV analysis that could not be filled.

    Only a failed download is DWD's doing; a file that arrived but could not
    be read is worth a report. Plain ASCII, like _describe_fetch_error.
    """
    what = (
        f"the missed DWD RV release {step_end.strftime('%Y-%m-%d %H:%M UTC')} "
        f"to fill the rain_events history ({err or type(err).__name__})"
    )
    if isinstance(err, (aiohttp.ClientError, TimeoutError)):
        cause = (
            f"Could not fetch {what}. DWD OpenData did not serve it; nothing "
            "is wrong with your setup."
        )
    else:
        cause = (
            f"Could not read {what}. This is likely a change on DWD's side or "
            "a bug in the integration; please report it if it keeps happening."
        )
    return f"{cause} The step stays unknown and is retried with the next releases"


class RainEventsTracker:
    """Keep one entry's rain events across releases and restarts."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        threshold_mmh: float,
        fetch_analysis: Callable[[datetime], Awaitable[float | None]],
        publish: Callable[[dict[str, Any]], None],
        store: Store | None = None,
    ) -> None:
        """Set up the tracker; nothing is loaded before the first release.

        Writes the state once more when the entry unloads: an options change
        reloads the entry, and the new tracker must read the current state,
        not one a pending delayed save still holds.
        """
        self._hass = hass
        self._entry = entry
        # The entry's rain_event_threshold as a wet-step limit; changing it
        # reloads the entry, and the tracker starts new events for it.
        self._milli = wet_step_milli(threshold_mmh)
        self._fetch_analysis = fetch_analysis
        self._publish = publish
        self.store = store if store is not None else rain_events_store(hass, entry.entry_id)
        self.state: RainEventsState | None = None
        self._saved_ended: str | None = None
        # The background fill-and-track round, if one was started; and the
        # last view this run published, shown while a round is still running.
        self.fill_task: asyncio.Task | None = None
        self._view: dict[str, Any] | None = None
        self.fill_latch = FailureLatch()
        self._latch = FailureLatch()
        entry.async_on_unload(self.async_save)

    @staticmethod
    async def async_remove(hass: HomeAssistant, entry_id: str) -> None:
        """Delete an entry's stored state (option turned off, entry removed)."""
        await rain_events_store(hass, entry_id).async_remove()

    async def async_track(
        self, release: datetime, metadata: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Track the release just adopted; return the view to publish now.

        ``metadata`` is RV's; its ``rain_within_2h`` samples are the analysis
        followed by the 24 forecast steps.

        The missed analyses must be filled *before* the tracker sees the
        release: updating first and recomputing after the fill can swap event
        ids and lose ``forecast_at_onset`` when it rained during a downtime.
        A fill takes seconds, though, and this runs inside the RV refresh
        that setup waits for. So when there is anything to fill, the update
        moves to a background task that fills, updates and publishes the
        view; until then the sensor keeps the view it showed before (none
        right after a restart). Every later release queues behind a running
        fill, so releases always reach the tracker in order.

        A failure here must not cost the RV sensors their update, so it is
        logged (once per run of failures) and the view is left out (None).
        """
        try:
            series = metadata["rain_within_2h"]
            base = series.source_timestamp or release
            values = [s["value"] for s in series.samples]
            state = await self._async_state()
        except Exception:
            self._failed()
            return None
        milli = self._milli
        running = self.fill_task is not None and not self.fill_task.done()
        if running or steps_to_fill(state, base):
            self.fill_task = self._entry.async_create_background_task(
                self._hass,
                self._async_fill_and_track(
                    self.fill_task if running else None, state, base, values, milli
                ),
                "dwd_precipitation rain_events fill",
            )
            return self._view
        return self._track(state, base, values, milli)

    def _track(
        self,
        state: RainEventsState,
        base: datetime,
        values: list[float | None],
        milli: int,
    ) -> dict[str, Any] | None:
        """Feed release ``base`` to the tracker (filled already); None on failure."""
        try:
            view = update_rain_events(state, base, values[0], values[1:], milli)
        except Exception:
            self._failed()
            return None
        self._latch.ok()
        self._schedule_save(state)
        self._view = view
        return view

    def _failed(self) -> None:
        """Log a tracker failure once per run of failures."""
        if self._latch.fail():
            _LOGGER.exception(
                "Could not update the Rain events sensor; the other RV "
                "sensors are not affected"
            )

    async def _async_fill_and_track(
        self,
        previous: asyncio.Task | None,
        state: RainEventsState,
        base: datetime,
        values: list[float | None],
        milli: int,
    ) -> None:
        """Fill release ``base``'s window, track it, and publish the view."""
        if previous is not None:
            await asyncio.wait([previous])
        try:
            await self._async_fill_missed(state, base)
        except Exception:
            self._failed()
            return
        view = self._track(state, base, values, milli)
        # A newer release queued behind this one publishes its own view.
        if view is not None and self.fill_task is asyncio.current_task():
            self._publish(view)

    async def _async_state(self) -> RainEventsState:
        """Return the tracker state, loading it from the store on first use."""
        if self.state is None:
            try:
                raw = await self.store.async_load()
                self.state = RainEventsState.from_dict(raw) if raw else RainEventsState()
            except Exception as err:  # noqa: BLE001 - any unreadable store
                # Also a store written by another version: discarding it costs
                # the event ids and up to an hour of measured history, where
                # keeping it would fail every release until the option is off.
                _LOGGER.warning(
                    "Discarding the saved rain_events state, which could not be "
                    "read (%s). Event ids start over; nothing else is affected",
                    err or type(err).__name__,
                )
                self.state = RainEventsState()
            self._saved_ended = (self.state.last_ended or {}).get("id")
        return self.state

    async def _async_fill_missed(self, state: RainEventsState, base: datetime) -> None:
        """Fetch the analysis of each missed release still in the window.

        Sequential, newest first, within RAIN_FILL_BUDGET; the first failure
        ends the round and the rest wait for the next release. Each fill reads
        only the analysis member, ~4-7 % of the archive. Runs in the
        background round, never in the refresh (see async_track).
        """
        missing = steps_to_fill(state, base)
        if not missing:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + RAIN_FILL_BUDGET.total_seconds()
        for step_end in missing:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            budget = asyncio.timeout(remaining)
            try:
                async with budget:
                    value = await self._fetch_analysis(step_end)
            except Exception as err:  # noqa: BLE001 - every failure is retried later
                if budget.expired():
                    # Our own limit, not a failure: the rest waits for the
                    # next release.
                    _LOGGER.debug(
                        "Fill budget used up at the RV analysis of %s", step_end
                    )
                    return
                _LOGGER.debug("Could not fill the RV analysis of %s: %s", step_end, err)
                if self.fill_latch.fail():
                    _LOGGER.warning(_describe_fill_failure(err, step_end))
                return
            _LOGGER.debug("Filled the RV analysis of %s: %s", step_end, value)
            record_measured(state, step_end, value)
        self.fill_latch.ok()

    def _schedule_save(self, state: RainEventsState) -> None:
        """Persist the tracker: soon while it matters, else at shutdown.

        Every release changes the state, but on a dry day nothing in it is
        worth an SD-card write every 5 minutes: losing it in a crash costs
        one fill round after the restart. The long delay keeps being pushed
        back by each release, and Home Assistant writes pending saves when
        it stops.
        """
        ended = (state.last_ended or {}).get("id")
        if at_stake(state) or ended != self._saved_ended:
            delay = RAIN_SAVE_DELAY
            self._saved_ended = ended
        else:
            delay = RAIN_IDLE_SAVE_DELAY
        self.store.async_delay_save(state.as_dict, delay.total_seconds())

    async def async_save(self) -> None:
        """Write the state now (entry unload), so a reload reads it back."""
        if self.state is not None:
            await self.store.async_save(self.state.as_dict())
