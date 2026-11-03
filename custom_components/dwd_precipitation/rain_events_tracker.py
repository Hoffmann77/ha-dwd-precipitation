"""The rain-events tracker of one config entry: store, fill, track, publish.

radar/rain_events.py is the pure logic; this is its life in Home Assistant.
The RV coordinator hands it every release it adopts and lends it two things:
a way to fetch one missed analysis, and a way to publish a view that is ready
after the RV update (a background fill). The HymecNG coordinator hands it the
precipitation type of every release it adopts, and lends it a way to fetch a
missed one. Everything else, from the Store to the save policy and the
once-per-run warnings, lives here.

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
    RainEventsView,
    at_stake,
    record_measured,
    record_type,
    steps_to_fill,
    types_to_fill,
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
    """Return the Store key of one config entry's rain_events state.

    One store per entry, under the integration's domain; Home Assistant keeps
    it as a file in its .storage directory.

    """
    return f"{DOMAIN}.{entry_id}.rain_events"


def rain_events_store(hass: HomeAssistant, entry_id: str) -> Store:
    """Return the Store of one config entry's rain_events state.

    The one place it is built, so a version bump (or a migration) reaches the
    tracker and the clean-up on option-off and entry removal alike.

    """
    return Store(hass, RAIN_EVENTS_STORE_VERSION, rain_events_store_key(entry_id))


def _describe_fill_failure(
    err: Exception, step_end: datetime, product: str = "RV", lost: str = "step"
) -> str:
    """Return the warning for a missed release that could not be filled.

    ``step_end`` is the step that stays unknown, ``product`` the DWD product
    that was fetched for it (RV for the amount, HymecNG for the type) and
    ``lost`` what of it stays unknown. Only a failed download is DWD's doing; a
    file that arrived but could not be read is worth a report. Plain ASCII,
    like _describe_fetch_error.

    """
    what = (
        f"the missed DWD {product} release "
        f"{step_end.strftime('%Y-%m-%d %H:%M UTC')} to fill the rain_events "
        f"history ({err or type(err).__name__})"
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
    return (
        f"{cause} The {lost} stays unknown and is retried with the next releases"
    )


class RainEventsTracker:
    """Keep one entry's rain events across releases and restarts."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        threshold_mmh: float,
        fetch_analysis: Callable[[datetime], Awaitable[float | None]],
        publish: Callable[[RainEventsView], None],
        store: Store | None = None,
        value_key: str = "value",
    ) -> None:
        """Set up the tracker; nothing is loaded before the first release.

        ``threshold_mmh`` is the rain_event_threshold option,
        ``fetch_analysis`` fetches one missed measured step and ``publish``
        shows a view finished in the background (both lent by RadvorRV). Writes
        the state once more when the entry unloads: an options change reloads
        the entry, and the new tracker must read the current state, not one a
        pending delayed save still holds. ``value_key`` picks the sample
        value followed: "value" for the own cell, "event_value" for the
        neighbourhood evaluation's (the wettest cell nearby while rain
        approaches, else the own cell).

        """
        self._hass = hass
        self._entry = entry
        # The entry's rain_event_threshold as a wet-step limit; changing it
        # reloads the entry, and the tracker starts new events for it.
        self._milli = wet_step_milli(threshold_mmh)
        self._fetch_analysis = fetch_analysis
        self._value_key = value_key
        # Lent by the HymecNG coordinator (attach_types); None without one.
        self._fetch_type: Callable[[datetime], Awaitable[str | None]] | None = None
        self._publish = publish
        self.store = store if store is not None else rain_events_store(hass, entry.entry_id)
        self.state: RainEventsState | None = None
        # RV and HymecNG both reach the state; it is loaded only once.
        self._load_lock = asyncio.Lock()
        self._saved_ended: str | None = None
        # The background fill-and-track round, if one was started; and the
        # last view this run published, shown while a round is still running.
        self.fill_task: asyncio.Task | None = None
        self._view: RainEventsView | None = None
        self.fill_latch = FailureLatch()
        self.type_fill_latch = FailureLatch()
        self._track_latch = FailureLatch()
        entry.async_on_unload(self.async_save)

    def attach_types(
        self, fetch_type: Callable[[datetime], Awaitable[str | None]]
    ) -> None:
        """Let the tracker fill missed precipitation types with ``fetch_type``.

        Called at setup with the HymecNG coordinator's fetch of one past
        release's type for the location (None when the file has none).

        """
        self._fetch_type = fetch_type

    async def async_record_type(self, release: datetime, label: str | None) -> None:
        """Record the HymecNG type of ``release``, the moment its step ends.

        Called by the HymecNG coordinator for every release it adopts, usually
        before RV adopts the same release; the type is published with the next
        view the tracker computes. Never raises: a failure is logged once, like
        any tracker failure, and costs only the type.

        """
        try:
            record_type(await self._async_state(), release, label)
        except Exception:
            self._failed()

    def _types_to_fill(self, state: RainEventsState, base: datetime) -> list[datetime]:
        """Return the types worth fetching now; none without a HymecNG fetch."""
        if self._fetch_type is None:
            return []
        return types_to_fill(state, base, self._milli)

    @staticmethod
    async def async_remove(hass: HomeAssistant, entry_id: str) -> None:
        """Delete an entry's stored state (option turned off, entry removed).

        Turning the option on again then starts clean.

        """
        await rain_events_store(hass, entry_id).async_remove()

    async def async_track(
        self, release: datetime, metadata: dict[str, Any]
    ) -> RainEventsView | None:
        """Track the release just adopted; return the view to publish now.

        ``metadata`` is RV's; its forecast series holds the analysis and the 24
        forecast steps. Missed analyses must be filled before the release is
        processed, or event ids can swap. A fill takes seconds, so when one is
        needed it runs in a background task that publishes when done, and the
        sensor keeps its previous view meanwhile. A failure is logged once and
        gives None, never failing the RV update.

        """
        try:
            series = metadata["rain_within_2h"]
            base = series.source_timestamp or release
            values = [s[self._value_key] for s in series.samples]
            state = await self._async_state()
        except Exception:
            self._failed()
            return None
        milli = self._milli
        running = self.fill_task is not None and not self.fill_task.done()
        if running or steps_to_fill(state, base) or self._types_to_fill(state, base):
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
    ) -> RainEventsView | None:
        """Feed release ``base`` to the tracker (filled already); None on failure.

        ``values`` are the analysis and the 24 forecast steps, ``milli`` the
        wet limit. On success the state is saved (see _schedule_save) and the
        view kept for the next release that has to wait for a fill.

        """
        try:
            view = update_rain_events(state, base, values[0], values[1:], milli)
        except Exception:
            self._failed()
            return None
        self._track_latch.ok()
        self._schedule_save(state)
        self._view = view
        return view

    def _failed(self) -> None:
        """Log a tracker failure once per run of failures.

        With the traceback, since a failure here is a bug or an unexpected
        file; the other RV sensors are not affected.

        """
        if self._track_latch.fail():
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
        """Fill release ``base``'s window, track it, and publish the view.

        The background round async_track starts. It waits for the previous
        round first, so releases reach the tracker in order. Only the newest
        round publishes; an older one's view is already out of date.

        """
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
        """Return the tracker state, loading it from the store on first use.

        A store that cannot be read is discarded with a warning: that costs the
        event ids and up to an hour of history, where keeping it would fail
        every release. Without a store the state starts empty.

        """
        async with self._load_lock:
            if self.state is None:
                self.state = await self._async_load()
                self._saved_ended = (self.state.last_ended or {}).get("id")
        return self.state

    async def _async_load(self) -> RainEventsState:
        """Read the state from the store; a fresh one if it cannot be read."""
        try:
            raw = await self.store.async_load()
            return RainEventsState.from_dict(raw) if raw else RainEventsState()
        except Exception as err:  # noqa: BLE001 - any unreadable store
            # Also a store written by another version: discarding it costs
            # the event ids and up to an hour of measured history, where
            # keeping it would fail every release until the option is off.
            _LOGGER.warning(
                "Discarding the saved rain_events state, which could not be "
                "read (%s). Event ids start over; nothing else is affected",
                err or type(err).__name__,
            )
            return RainEventsState()

    async def _async_fill_missed(self, state: RainEventsState, base: datetime) -> None:
        """Fetch what the tracker missed of the releases still in the window.

        First the analysis of each missed release, then the type of each wet
        measured step without one (only now are the filled steps known to be
        wet). Both share one RAIN_FILL_BUDGET (30 s) and run sequentially,
        newest first; the first failure ends that part of the round and the
        rest wait for the next release, so a failed analysis also postpones
        the types. Each analysis reads only its member, about 4-7 % of the
        archive; each type is one small HymecNG file.

        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + RAIN_FILL_BUDGET.total_seconds()
        done = await self._async_fill(
            steps_to_fill(state, base),
            self._fetch_analysis,
            lambda step_end, value: record_measured(state, step_end, value),
            self.fill_latch,
            "RV analysis",
            lambda err, step_end: _describe_fill_failure(err, step_end),
            deadline,
        )
        if done and self._fetch_type is not None:
            await self._async_fill(
                self._types_to_fill(state, base),
                self._fetch_type,
                lambda step_end, label: record_type(state, step_end, label),
                self.type_fill_latch,
                "HymecNG type",
                lambda err, step_end: _describe_fill_failure(
                    err, step_end, "HymecNG", "step's precipitation type"
                ),
                deadline,
            )

    async def _async_fill(
        self,
        missing: list[datetime],
        fetch: Callable[[datetime], Awaitable[Any]],
        record: Callable[[datetime, Any], None],
        latch: FailureLatch,
        what: str,
        describe: Callable[[Exception, datetime], str],
        deadline: float,
    ) -> bool:
        """Fetch and record each of ``missing`` in turn until ``deadline``.

        Returns whether every one was recorded. Running out of time is not a
        failure; the first failed fetch ends the run, warned about once per
        run of failures through ``latch``.

        """
        if not missing:
            return True
        loop = asyncio.get_running_loop()
        for step_end in missing:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            budget = asyncio.timeout(remaining)
            try:
                async with budget:
                    value = await fetch(step_end)
            except Exception as err:  # noqa: BLE001 - every failure is retried later
                if budget.expired():
                    # Our own limit, not a failure: the rest waits for the
                    # next release.
                    _LOGGER.debug("Fill budget used up at the %s of %s", what, step_end)
                    return False
                _LOGGER.debug("Could not fill the %s of %s: %s", what, step_end, err)
                if latch.fail():
                    _LOGGER.warning(describe(err, step_end))
                return False
            _LOGGER.debug("Filled the %s of %s: %s", what, step_end, value)
            record(step_end, value)
        latch.ok()
        return True

    def _schedule_save(self, state: RainEventsState) -> None:
        """Persist the tracker: soon while it matters, else at shutdown.

        While something is at stake (an event, an unknown or wet step, a new
        ended event) the state is written RAIN_SAVE_DELAY after the release. On
        a dry day nothing is worth an SD-card write every 5 minutes: the long
        delay is pushed back by each release, and Home Assistant writes pending
        saves when it stops.

        """
        ended = (state.last_ended or {}).get("id")
        if at_stake(state) or ended != self._saved_ended:
            delay = RAIN_SAVE_DELAY
            self._saved_ended = ended
        else:
            delay = RAIN_IDLE_SAVE_DELAY
        self.store.async_delay_save(state.as_dict, delay.total_seconds())

    async def async_save(self) -> None:
        """Write the state now (entry unload), so a reload reads it back.

        Nothing is written before the state has been loaded.

        """
        if self.state is not None:
            await self.store.async_save(self.state.as_dict())
