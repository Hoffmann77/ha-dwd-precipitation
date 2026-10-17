"""Data update coordinator for the dwd precipitation integration."""

from __future__ import annotations

import hashlib
import logging
import random
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cached_property
from http import HTTPStatus
from itertools import product as cartesian_product
from math import gcd
from typing import Any, ClassVar

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_time_change,
    async_track_utc_time_change,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .options import DwdOptions
from .radar import OutsideGrid
from .radar.urls import product_url
from .release_grid import ReleaseGrid

_LOGGER = logging.getLogger(__name__)

# Fast-poll retry cadence: the first retry fires after FAST_POLL_START, and each
# further consecutive failure adds FAST_POLL_STEP, until the product's
# MAX_FAST_POLL_INTERVAL caps it.
FAST_POLL_START = timedelta(seconds=60)
FAST_POLL_STEP = timedelta(seconds=10)

# How long an overdue release is given to turn up before the cached value is
# written off (see BaseProductUpdateCoordinator.OVERDUE_GRACE).
DEFAULT_OVERDUE_GRACE = timedelta(minutes=6)

# Every install of this integration would otherwise fetch on the same second,
# so each coordinator takes a whole-second offset in [0, MAX_FETCH_JITTER] and
# adds it to RELEASE_DELAY. Adding it *there* rather than delaying the fetch on
# its own is what keeps the timing invariants intact: the scheduled fetches and
# the staleness deadline are both derived from the same delay, so they shift
# together and the gap between them is untouched. The offset is never negative,
# so a jittered fetch is never earlier than the calibrated publication lag and
# can only reduce 404s.
MAX_FETCH_JITTER = timedelta(seconds=30)

# Retries are jittered differently: a fresh +/-15% on every attempt, because
# the point there is to pull instances *out* of the lockstep a shared outage
# puts them in, which a fixed per-install offset would preserve.
RETRY_JITTER = 0.15


def fetch_jitter_for(entry_id: str, product_key: str) -> timedelta:
    """Return the fixed fetch offset of one product of one config entry.

    A whole number of seconds between 0 and MAX_FETCH_JITTER (30 s), added to
    the product's publication delay so that not every install fetches on the
    same second. Derived from the entry id and the product key instead of drawn
    at random, so an install keeps its fetch times across restarts and reloads,
    while installs (and one install's products) still spread out. A sha256
    digest, because Python's str hash() changes from process to process.

    """
    digest = hashlib.sha256(f"{entry_id}:{product_key}".encode()).digest()
    steps = int(MAX_FETCH_JITTER.total_seconds()) + 1

    return timedelta(seconds=int.from_bytes(digest[:8], "big") % steps)


def _apply_retry_jitter(delay: timedelta) -> timedelta:
    """Return the retry delay spread by +/-RETRY_JITTER.

    ``delay`` is the backoff ramp's next delay; the result is that delay times
    a random factor between 0.85 and 1.15. A fresh draw on every attempt, so
    installs that failed together during a shared DWD outage do not keep
    retrying together.

    """
    return delay * random.uniform(1 - RETRY_JITTER, 1 + RETRY_JITTER)


def _format_duration(delta: timedelta) -> str:
    """Return a short human-readable duration: "60 s", "5 min", "1 h 10 min".

    For the retry time in the error message a user reads in their log. Seconds
    are shown only below a minute; a negative duration shows as "0 s".

    """
    seconds = max(int(delta.total_seconds()), 0)

    if seconds < 60:
        return f"{seconds} s"

    minutes, _ = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min"

    hours, minutes = divmod(minutes, 60)

    return f"{hours} h" if minutes == 0 else f"{hours} h {minutes} min"


def _describe_fetch_error(
    err: Exception, release: datetime, next_retry: timedelta
) -> str:
    """Return the message a user sees in their log for a failed update.

    ``err`` is what the fetch raised, ``release`` the release it tried and
    ``next_retry`` the delay until the next attempt. Home Assistant logs the
    message once per run of failures, so it is the only explanation the user
    gets: it says what DWD did (not published yet, an HTTP error, unreachable,
    a file this version cannot read, or a location off the grid), whether their
    setup is to blame (almost never: usually DWD is publishing late) and when
    the next retry is. Plain ASCII, so every log viewer shows it correctly.

    """
    release_str = release.strftime("%Y-%m-%d %H:%M UTC")

    if isinstance(err, aiohttp.ClientResponseError):
        if err.status == HTTPStatus.NOT_FOUND:
            cause = (
                f"DWD has not published the {release_str} release yet (HTTP 404). "
                "DWD OpenData is late; nothing is wrong with your setup."
            )
        else:
            cause = (
                f"DWD OpenData returned HTTP {err.status} ({err.message}) for the "
                f"{release_str} release."
            )
    elif isinstance(err, aiohttp.ClientConnectionError):
        cause = (
            f"Could not reach DWD OpenData for the {release_str} release ({err}). "
            "Check this machine's internet access."
        )
    elif isinstance(err, OutsideGrid):
        # The setup check is a coarse box, so a location near its edge can
        # pass it and still be off the grid DWD's file describes.
        cause = (
            f"The configured location is not on the grid of the {release_str} "
            f"release ({err}): DWD's radar does not cover it. Set the "
            "integration up again with a location inside Germany."
        )
    else:
        # Not a transport error: DWD served something this version cannot
        # read. That is a format change or a bug, not a late file, and only a
        # report gets it fixed; the traceback goes to the debug log.
        cause = (
            f"Could not read the {release_str} release "
            f"({type(err).__name__}: {err}). This is likely a change on DWD's "
            "side or a bug in the integration; please report it if it keeps "
            "happening."
        )

    return f"{cause} Retrying in {_format_duration(next_retry)}."


@dataclass
class ProductMetadata:
    """Parsed per-product metadata, ready for HA state attributes."""

    source_product: str | None
    source_timestamp: datetime | None  # always UTC-aware, or None (product reference time)
    lead_time_minutes: int | None = None
    data_start: datetime | None = None  # accumulation/validity window start (UTC), or None
    data_end: datetime | None = None    # accumulation/validity window end (UTC), or None
    # Optional constituent 5-minute points (the RV forecast series), each a dict
    # of {"lead", "start", "end", "value", "intensity"} — surfaced as an entity
    # state attribute.
    samples: list[dict[str, Any]] | None = None
    # Optional rolling-hour series (RV's 5-minute steps summed by the hour): one
    # point per 5-minute lead, each a dict of {"lead", "start", "end", "value"}
    # where value is a 60-minute total (mm).
    rolling_1h: list[dict[str, Any]] | None = None


@dataclass
class CoordinatorData:
    """One release of a product: its values and their metadata, by sub-key.

    Every product keys both dicts the same way (const.KEY_*: RS ``last_60``,
    ``next_60``, ...; RADOLAN ``amount``; HymecNG ``precipitation_type``; RV's
    own keys), and every entity description names the sub-key it shows. A
    value may come without metadata (RV's ``rain_events``), and either may be
    None (no data for the cell).

    """

    data: dict[str, Any]
    metadata: dict[str, ProductMetadata | None]


# What a product's fetch returns: CoordinatorData's two dicts.
type Payload = tuple[dict[str, Any], dict[str, ProductMetadata | None]]


class BaseProductUpdateCoordinator(DataUpdateCoordinator[CoordinatorData], ABC):
    """Abstract per-product data update coordinator.

    Each concrete subclass represents one DWD product and owns its own
    update schedule. Subclasses must define PRODUCT_KEY and the timing
    ClassVars, and implement _fetch_and_parse() (products.py has bases for
    one-file-per-release products and for RADVOR tars). The URL defaults to
    the product key's pattern in radar/urls.py; the cell holding ``coords``
    is found on the grid each file describes (radar/grid.py).

    """

    PRODUCT_KEY: ClassVar[str] = ""

    # Plain-language name for this product, used in Home Assistant's own
    # coordinator log lines ("Error fetching <entry> <label> data: ..."), so it
    # has to read naturally with "data" appended. Falls back to PRODUCT_KEY.
    PRODUCT_LABEL: ClassVar[str] = ""

    RELEASE_INTERVAL: ClassVar[timedelta] = timedelta(minutes=15)

    RELEASE_DELAY: ClassVar[timedelta] = timedelta(minutes=5)

    RELEASE_OFFSET: ClassVar[timedelta] = timedelta()

    # How long a release that has fallen due is given to turn up before the
    # cached value is written off. Measured from the moment that release should
    # have been on OpenData, so it says how late DWD is allowed to be rather
    # than how old the held value may get. It must never be a whole multiple of
    # RELEASE_INTERVAL: that would put the deadline exactly on a later fetch
    # instant (there is a test for this). See _stale_deadline.
    OVERDUE_GRACE: ClassVar[timedelta] = DEFAULT_OVERDUE_GRACE

    # Per-instance fetch offset, set in __init__. Defaults to zero so that a
    # coordinator built without it (tests) keeps the exact nominal schedule.
    _fetch_jitter: timedelta = timedelta()

    USE_LOCAL_TIME: ClassVar[bool] = False

    @classmethod
    def is_needed(cls, options: DwdOptions) -> bool:
        """Return whether an entry with these options uses this product at all.

        Asked by async_setup_entry before the coordinator is built. True for
        every product except one that exists for a single option (RW's
        10-minute runs, for a dry streak counting RW); setup does not build the
        others, which saves their requests.

        """
        return True

    # Upper bound for the fast-poll retry interval (see _fast_poll_delay).
    MAX_FAST_POLL_INTERVAL: ClassVar[timedelta] = timedelta(minutes=5)

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_client,
        lat: float,
        lon: float,
    ) -> None:
        """Set up the coordinator of one product for one entry's location.

        ``async_client`` is Home Assistant's shared aiohttp session,
        ``lat``/``lon`` the configured location. Home Assistant's own polling
        is off: fetches are triggered by the release schedule
        (async_track_releases) and the retry ramp. Nothing is fetched here;
        setup calls async_refresh. Unloading the entry cancels the pending
        timers.

        """
        super().__init__(
            hass,
            _LOGGER,
            name=f"{entry.data[CONF_NAME]} {self.PRODUCT_LABEL or self.PRODUCT_KEY}",
            update_interval=None,  # event-driven via track_time_change_args
        )
        self.config_entry = entry
        self.async_client = async_client
        self.coords = (lat, lon)
        self.curr_release: datetime | None = None
        self._fast_poll_unsub = None
        self._fast_poll_failures = 0
        self._stale_unsub = None
        self._fetch_jitter = fetch_jitter_for(entry.entry_id, self.PRODUCT_KEY)
        entry.async_on_unload(self._stop_fast_polling)
        entry.async_on_unload(self._cancel_stale_check)

    # ------------------------------------------------------------------
    # Concrete helpers
    # ------------------------------------------------------------------

    @cached_property
    def release_delay(self) -> timedelta:
        """Return RELEASE_DELAY plus this instance's fetch jitter.

        RELEASE_DELAY is how long after a release's nominal time DWD has the
        file on OpenData (scripts/check_release_delay.py checks it); this is
        when we fetch. The schedule, the release lookup and the staleness
        deadline all use it, so the jitter moves them together and keeps the
        margins between them.

        """
        return self.RELEASE_DELAY + self._fetch_jitter

    def _now(self) -> datetime:
        """Return the current time in this product's own time reference.

        Local time for a USE_LOCAL_TIME product (sf_2350, released at 23:50
        local time), UTC for the others. Every "which release is ours by now"
        question goes through here: asked in the wrong reference, it fetches a
        product hours off its schedule.

        """
        return dt_util.now() if self.USE_LOCAL_TIME else dt_util.utcnow()

    @property
    def grid(self) -> ReleaseGrid:
        """Return this product's release grid, in its own time reference.

        The grid knows when releases are due: every RELEASE_INTERVAL, at
        RELEASE_OFFSET past. A USE_LOCAL_TIME product's grid is on Home
        Assistant's local clock, so its releases are 23 or 25 hours apart on
        DST changeover days (see ReleaseGrid). Built on each use, so a change
        of HA's time zone applies.

        """
        return ReleaseGrid(
            self.RELEASE_INTERVAL,
            self.RELEASE_OFFSET,
            dt_util.get_default_time_zone() if self.USE_LOCAL_TIME else UTC,
        )

    def _get_latest_release(self, now: datetime) -> datetime:
        """Return the newest release that is ours to fetch by ``now``.

        The newest release on the grid that is at least release_delay old, i.e.
        whose file DWD should have published by now. It comes back in UTC.

        """
        return self.grid.at_or_before(now - self.release_delay)

    def _stale_deadline(self) -> datetime | None:
        """Return when the cached value is written off (None: nothing cached).

        The clock starts when the release after the cached one should have been
        on OpenData, and runs for OVERDUE_GRACE: how long DWD is given to
        publish a release that is due. Past the deadline the entities turn
        unavailable if the user chose that (unavailable_when_stale). Anchored
        there, the deadline never falls on a scheduled fetch, which a deadline
        counted from the cached release would (ADR 0007).

        """
        if self.curr_release is None:
            return None

        # On the product's own clock (see grid): adding 24 h to a UTC
        # timestamp would put the autumn deadline before the file it waits
        # for can exist.
        return (
            self.grid.next_after(self.curr_release)
            + self.release_delay
            + self.OVERDUE_GRACE
        )

    def _data_is_stale(self, now: datetime) -> bool:
        """Return True if the overdue release has gone unfetched for too long.

        That is, ``now`` is past _stale_deadline. Also True when nothing is
        cached yet.

        """
        deadline = self._stale_deadline()

        return deadline is None or now > deadline

    @cached_property
    def options(self) -> DwdOptions:
        """Return the entry's options.

        A typed snapshot (DwdOptions) with the defaults filled in. A snapshot
        is enough: saving the options reloads the entry, which builds new
        coordinators.

        """
        return DwdOptions.from_options(self.config_entry.options)

    @property
    def unavailable_when_stale(self) -> bool:
        """Return whether a value past its deadline should be hidden.

        The user's choice (Advanced options). When off, an old value stays
        shown until a new release arrives; when on, the entities turn
        unavailable at the staleness deadline.

        """
        return self.options.unavailable_when_stale

    def _data_is_reportable(self, now: datetime) -> bool:
        """Return True if what we hold may still be shown to the user.

        False when nothing is held, or when the value is past its deadline and
        the user wants stale values hidden. This is the one place it is
        decided. Entities read it for their availability, and a failed fetch
        raises UpdateFailed only when it is False, so an entity never shows a
        value the coordinator has given up on.

        """
        if self.data is None:
            return False

        return not (self.unavailable_when_stale and self._data_is_stale(now))

    @property
    def data_is_reportable(self) -> bool:
        """Return whether the cached value may be shown right now.

        _data_is_reportable at the current time, in the product's own time
        reference. What every entity's availability is based on.

        """
        return self._data_is_reportable(self._now())

    @callback
    def _cancel_stale_check(self) -> None:
        """Cancel the pending deadline callback.

        Called before arming a new one, and when the entry is unloaded. Does
        nothing when none is pending.

        """
        if self._stale_unsub is not None:
            self._stale_unsub()
            self._stale_unsub = None

    @callback
    def _schedule_stale_check(self) -> None:
        """Arm a callback at the cached value's deadline.

        Home Assistant reads availability only when an entity writes its state.
        During an outage the retries make it do so; after a success nothing
        else would, so this callback makes the entities look again when the
        value falls due. Re-armed after every successful fetch.

        """
        self._cancel_stale_check()

        deadline = self._stale_deadline()
        if deadline is None:
            return

        self._stale_unsub = async_track_point_in_time(
            self.hass, self._stale_reached, deadline
        )

    @callback
    def _stale_reached(self, _now) -> None:
        """Make the entities look at the clock again once the deadline passes.

        Notifies the coordinator's listeners without fetching anything; their
        availability then turns off if unavailable_when_stale is set.

        """
        self._stale_unsub = None
        _LOGGER.debug("%s: cached value reached its deadline", self.PRODUCT_KEY)
        self.async_update_listeners()

    @callback
    def async_track_releases(self) -> list[CALLBACK_TYPE]:
        """Register the timers that fetch each release when it is due.

        Called once by async_setup_entry, after the first refresh. Each timer
        fires at a release time plus release_delay and refreshes the
        coordinator. Local-time timers for a USE_LOCAL_TIME product, UTC timers
        for the others. The coordinator registers them itself because it owns
        both the grid and the clock it is read in: registered apart, sf_2350
        was once fetched hours late (ADR 0007). Returns the unsubscribe
        callbacks, which the entry also calls on unload.

        """
        track = (
            async_track_time_change
            if self.USE_LOCAL_TIME
            else async_track_utc_time_change
        )

        unsubs = [
            track(self.hass, self._async_release_due, **args)
            for args in self.track_time_change_args
        ]
        for unsub in unsubs:
            self.config_entry.async_on_unload(unsub)

        return unsubs

    async def _async_release_due(self, _now) -> None:
        """Refresh because a new release should now be on OpenData.

        Called by the timers async_track_releases registers; the refresh
        fetches it (see _async_update_data).

        """
        await self.async_refresh()

    @cached_property
    def track_time_change_args(self) -> list[dict]:
        """Return the fewest time-change arguments that fire at every release.

        Each dict (``hour``, ``minute``, ``second``, as values or lists) is
        passed to Home Assistant's time-change tracker, which fires whenever
        the clock matches it. The fetch times of a day (each release plus
        release_delay) are grouped by second, with hours and minutes as lists,
        when every combination is a fetch time (true for any whole-minute
        interval); otherwise by minute and second, with the hours as a list.
        Either way no tracker fires off schedule.

        """
        release_interval = self.RELEASE_INTERVAL
        release_delay = self.release_delay
        release_offset = self.RELEASE_OFFSET

        seconds_per_day = int(timedelta(days=1).total_seconds())
        interval_seconds = int(release_interval.total_seconds())

        if interval_seconds <= 0:
            raise ValueError("RELEASE_INTERVAL must be a positive duration.")
        if interval_seconds > seconds_per_day:
            raise ValueError("RELEASE_INTERVAL must not exceed 24 hours.")

        cycle_length = seconds_per_day // gcd(interval_seconds, seconds_per_day)
        base_seconds = int((release_offset + release_delay).total_seconds()) % seconds_per_day

        actual: set[tuple[int, int, int]] = set()
        for n in range(cycle_length):
            s = (base_seconds + n * interval_seconds) % seconds_per_day
            actual.add((s // 3600, (s % 3600) // 60, s % 60))

        # Strategy 1: group by second; hour and minute as lists
        by_second: dict[int, set[tuple[int, int]]] = defaultdict(set)
        for h, m, s in actual:
            by_second[s].add((h, m))

        result: list[dict] | None = []
        for second, hm_pairs in by_second.items():
            hours = sorted({hm[0] for hm in hm_pairs})
            minutes = sorted({hm[1] for hm in hm_pairs})
            if {(h, m) for h, m in cartesian_product(hours, minutes)} != hm_pairs:
                result = None
                break
            result.append({"hour": hours, "minute": minutes, "second": second})

        if result is not None:
            return result

        # Strategy 2: group by (minute, second); hour as list
        by_minute_second: dict[tuple[int, int], list[int]] = defaultdict(list)
        for h, m, s in actual:
            by_minute_second[(m, s)].append(h)

        return [
            {"hour": sorted(hours), "minute": minute, "second": second}
            for (minute, second), hours in by_minute_second.items()
        ]

    # ------------------------------------------------------------------
    # Fast-poll retry
    # ------------------------------------------------------------------

    def _fast_poll_delay(self) -> timedelta:
        """Return the retry delay for the next fast-poll attempt.

        FAST_POLL_START (60 s) plus FAST_POLL_STEP (10 s) per consecutive
        failure, capped at MAX_FAST_POLL_INTERVAL; before the jitter is
        applied.

        """
        delay = FAST_POLL_START + self._fast_poll_failures * FAST_POLL_STEP

        return min(delay, self.MAX_FAST_POLL_INTERVAL)

    @callback
    def _schedule_fast_poll(self) -> timedelta:
        """Arm the next retry after a failed fetch, backing off each time.

        Called on every failed fetch; returns the delay it chose, for the error
        message. Only a successful fetch resets the ramp, not a new release
        falling due, so a long DWD outage settles at MAX_FAST_POLL_INTERVAL
        instead of retrying every minute.

        """
        delay = _apply_retry_jitter(self._fast_poll_delay())
        self._fast_poll_failures += 1

        self._cancel_fast_poll()

        _LOGGER.debug(
            "%s: scheduling fast-poll retry in %ss (attempt %s)",
            self.PRODUCT_KEY,
            int(delay.total_seconds()),
            self._fast_poll_failures,
        )
        self._fast_poll_unsub = async_call_later(
            self.hass, delay, self._async_fast_poll_due
        )

        return delay

    async def _async_fast_poll_due(self, _now) -> None:
        """Retry the fetch that failed.

        Called by the timer _schedule_fast_poll arms. The refresh fetches the
        newest due release, which may be newer than the one that failed.

        """
        self._fast_poll_unsub = None
        _LOGGER.debug("%s: fast-poll retry firing", self.PRODUCT_KEY)
        await self.async_refresh()

    @callback
    def _cancel_fast_poll(self) -> None:
        """Cancel the pending retry, leaving the backoff ramp where it is.

        Separate from _stop_fast_polling because re-arming a retry must not
        reset the ramp: only a success does that.

        """
        if self._fast_poll_unsub is not None:
            self._fast_poll_unsub()
            self._fast_poll_unsub = None

    @callback
    def _stop_fast_polling(self) -> None:
        """Cancel fast polling and reset the backoff ramp.

        After a success, and when the entry is unloaded; the next failure
        starts again at FAST_POLL_START.

        """
        self._cancel_fast_poll()
        self._fast_poll_failures = 0

    # ------------------------------------------------------------------
    # Abstract interface — subclasses implement these
    # ------------------------------------------------------------------

    def _get_url(self, ts: datetime) -> str:
        """Return the URL of release ``ts`` (see radar/urls.py).

        Derived from PRODUCT_KEY, so a product only needs a pattern there.

        """
        return product_url(self.PRODUCT_KEY, ts)

    @abstractmethod
    async def _fetch_and_parse(self, ts: datetime) -> Payload:
        """Fetch and decode one release; return (data, metadata).

        Every product implements it. ``ts`` is the release's nominal time
        (UTC). The result is two dicts keyed by the same sub-keys (see
        CoordinatorData): the values for the location and their
        ProductMetadata. It raises on any failure; the base class handles
        retries. It is free of side effects, so the totals' backfill can fetch
        past releases through it. Decoding runs in the executor, never on the
        event loop.

        """

    async def _async_on_new_release(
        self, release: datetime, data: Any, metadata: Any
    ) -> None:
        """React to a release this coordinator is about to adopt.

        Called once per release, after a successful fetch and before the data
        is published; may add to ``data``. Must not raise: a failure here must
        not cost the product its update. Nothing by default; RV keeps its
        analysis for the rolling-hour series and feeds the rain-events tracker
        here.

        """

    async def async_fetch_release(self, release: datetime) -> CoordinatorData:
        """Fetch and decode any ``release`` without adopting it.

        For the totals' backfill, which adds releases missed during a downtime.
        The coordinator's own state, schedule and retry ramp are untouched, and
        _async_on_new_release is not called. Raises like _fetch_and_parse.

        """
        data, metadata = await self._fetch_and_parse(release)
        return CoordinatorData(data, metadata)

    # ------------------------------------------------------------------
    # Template method — do not override in subclasses
    # ------------------------------------------------------------------

    @callback
    def _record_success(self, release: datetime) -> None:
        """Adopt a freshly fetched release as the cached one.

        Resets the retry ramp, records the release, then arms the deadline
        callback, which can only come after the release is recorded, since it
        is computed from it.

        """
        self._stop_fast_polling()
        self.curr_release = release
        self._schedule_stale_check()

    async def _async_update_data(self) -> CoordinatorData:
        """Fetch the latest release if it is new; Home Assistant's update hook.

        Home Assistant calls it on every refresh (the release timers, the
        retries, setup) and publishes what it returns to the entities. A
        release already held is returned as it is. A new one is fetched and
        decoded; on success it is adopted. A failed fetch arms a retry and
        keeps the old value while it may still be shown; once it may not, it
        raises UpdateFailed with a message for the user.

        """
        now = self._now()
        latest_release = self._get_latest_release(now)

        if self.curr_release is not None and self.curr_release >= latest_release:
            self._stop_fast_polling()
            return self.data

        try:
            data, metadata = await self._fetch_and_parse(latest_release)
        except Exception as err:
            if self._fast_poll_failures == 0 and not isinstance(
                err, aiohttp.ClientError
            ):
                # Once per run of failures: what a report needs, and the only
                # trace of it while the cached value still covers the gap.
                _LOGGER.debug(
                    "%s: reading the %s release failed",
                    self.PRODUCT_KEY,
                    latest_release,
                    exc_info=True,
                )
            # Keep retrying regardless of availability: the backoff governs the
            # retry cadence, _data_is_reportable() governs what HA shows.
            next_retry = self._schedule_fast_poll()

            if not self._data_is_reportable(now):
                raise UpdateFailed(
                    _describe_fetch_error(err, latest_release, next_retry)
                ) from err

            # Data is still fresh enough — retry silently
            return self.data

        await self._async_on_new_release(latest_release, data, metadata)
        self._record_success(latest_release)

        return CoordinatorData(data, metadata)
