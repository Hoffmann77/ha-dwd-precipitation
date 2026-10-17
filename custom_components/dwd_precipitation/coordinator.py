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
    """Return the stable fetch offset for one product of one config entry.

    Derived from the entry id rather than drawn at random, so an install keeps
    the same offset across restarts and reloads: the schedule a user observes
    in their logs stays the one they observed last week, and changing an
    unrelated option does not quietly move their fetch times. Spread across the
    population is just as uniform either way.

    hashlib rather than hash() or random.seed(): str hashing is salted per
    process, and only a digest is contractually stable across interpreter runs.
    The product key is mixed in so one install's products do not all sit at the
    same offset.
    """
    digest = hashlib.sha256(f"{entry_id}:{product_key}".encode()).digest()
    steps = int(MAX_FETCH_JITTER.total_seconds()) + 1

    return timedelta(seconds=int.from_bytes(digest[:8], "big") % steps)


def _apply_retry_jitter(delay: timedelta) -> timedelta:
    """Return the retry delay spread by +/-RETRY_JITTER."""
    return delay * random.uniform(1 - RETRY_JITTER, 1 + RETRY_JITTER)


def _format_duration(delta: timedelta) -> str:
    """Return a short human-readable duration: "60 s", "5 min", "1 h 10 min"."""
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
    """Return a human-readable explanation of a failed product update.

    Home Assistant logs this as ``Error fetching <name> data: <message>``, where
    ``<name>`` already identifies the location and product (e.g. "Zuhause RS
    precipitation nowcast" — see PRODUCT_LABEL),
    and only logs it once per run of failures — so this one message is all the
    reader gets. That reader is someone scanning their log wondering what they
    broke, so it answers three things: what DWD did, whether it is their fault,
    and what happens next, in as few words as will carry that. Almost every
    occurrence is DWD publishing late, so it must not read like a user error.

    Kept to plain ASCII: log viewers and Windows consoles mangle typographic
    punctuation.
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
    # Optional RS rolling-hour series: one point per 5-minute lead, each a dict
    # of {"lead", "start", "end", "value"} where value is a 60-minute total (mm).
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
        """Whether an entry with these options uses this product at all.

        Every product is, except those that exist for one option; skipping
        them saves the requests (see async_setup_entry).
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
        """Initialize the coordinator."""
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

        RELEASE_DELAY is what DWD does — the calibrated lag between a product's
        nominal time and the file appearing, checked by
        scripts/check_release_delay.py. This is what *we* do, and everything
        that has to agree on when a release is ours to fetch uses it: the
        schedule, the release lookup, and the staleness deadline alike.
        """
        return self.RELEASE_DELAY + self._fetch_jitter

    def _now(self) -> datetime:
        """Return the current time in this product's own time reference.

        USE_LOCAL_TIME products sit on a local wall-clock release grid, so
        everything that asks "which release is ours by now" has to ask in the
        same reference. One helper rather than the ternary at each site: the
        cost of getting this wrong is a product fetched hours off its schedule
        (see grid), and a missed branch is the way that happens.
        """
        return dt_util.now() if self.USE_LOCAL_TIME else dt_util.utcnow()

    @property
    def grid(self) -> ReleaseGrid:
        """Return this product's release grid, in its own time reference.

        A USE_LOCAL_TIME product's grid is on Home Assistant's local clock, so
        its releases are 23 or 25 hours apart on DST changeover days (see
        ReleaseGrid). Built on each use, so a change of HA's time zone applies.
        """
        return ReleaseGrid(
            self.RELEASE_INTERVAL,
            self.RELEASE_OFFSET,
            dt_util.get_default_time_zone() if self.USE_LOCAL_TIME else UTC,
        )

    def _get_latest_release(self, now: datetime) -> datetime:
        """Return the newest release that is ours to fetch by ``now``."""
        return self.grid.at_or_before(now - self.release_delay)

    def _stale_deadline(self) -> datetime | None:
        """Return when the cached value is written off, or None if it is fresh.

        The clock starts when the release *after* the cached one should have
        been on OpenData, and runs for OVERDUE_GRACE. So the question the
        deadline answers is "how long may we go on trying for a release that is
        already due", which is a property of the retrying and has nothing to do
        with how often the product is published.

        That framing is what keeps the deadline away from the fetch schedule.
        Anchor the tolerance on the cached release instead and it has to be
        expressed in release intervals, so it expires exactly when some later
        fetch is due — and the value is written off at the very instant of the
        attempt that might have restored it, with event-loop latency deciding
        which of the two happens first. Anchored here, the deadline only lands
        on a fetch instant if OVERDUE_GRACE is a whole multiple of
        RELEASE_INTERVAL, which is a rule a test can hold us to.
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
        """Return True if the overdue release has gone unfetched for too long."""
        deadline = self._stale_deadline()

        return deadline is None or now > deadline

    @cached_property
    def options(self) -> DwdOptions:
        """Return the entry's options (a snapshot: a change reloads the entry)."""
        return DwdOptions.from_options(self.config_entry.options)

    @property
    def unavailable_when_stale(self) -> bool:
        """Return whether a value past its deadline should be hidden."""
        return self.options.unavailable_when_stale

    def _data_is_reportable(self, now: datetime) -> bool:
        """Return True if what we hold may still be shown to the user.

        The one place the "do we still report this" policy lives. Both sides of
        it read from here: entities for their availability, and the failure path
        of _async_update_data to decide whether a failed fetch is worth an
        UpdateFailed. They are exact complements, so writing them out separately
        is an invitation for the entity to report a value the coordinator has
        already given up on.
        """
        if self.data is None:
            return False

        return not (self.unavailable_when_stale and self._data_is_stale(now))

    @property
    def data_is_reportable(self) -> bool:
        """Return whether the cached value may be shown right now."""
        return self._data_is_reportable(self._now())

    @callback
    def _cancel_stale_check(self) -> None:
        """Cancel the pending deadline callback."""
        if self._stale_unsub is not None:
            self._stale_unsub()
            self._stale_unsub = None

    @callback
    def _schedule_stale_check(self) -> None:
        """Wake the entities up when the cached value falls due.

        Availability is derived from the clock, but Home Assistant only re-reads
        it when the entity writes state. During an outage the fast-poll ramp
        provides that on its own; after a success nothing else would, so arm one
        callback on the deadline. It never competes with a fetch: the deadline
        cannot fall on a fetch instant (see _stale_deadline), and any fetch that
        happens first re-arms it.
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
        """Make the entities look at the clock again once the deadline passes."""
        self._stale_unsub = None
        _LOGGER.debug("%s: cached value reached its deadline", self.PRODUCT_KEY)
        self.async_update_listeners()

    @callback
    def async_track_releases(self) -> list[CALLBACK_TYPE]:
        """Register the time-change trackers that drive this product's fetches.

        The coordinator registers its own schedule rather than handing the
        pieces to async_setup_entry, because both halves of it — the release
        grid, and the time reference that grid is expressed in — are knowledge
        this class already owns. Splitting them apart is what once had sf_2350
        registered in UTC while its grid was local wall-clock, fetching it an
        offset's worth of hours late every day.
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
        """Refresh because a new release should now be on OpenData."""
        await self.async_refresh()

    @cached_property
    def track_time_change_args(self) -> list[dict]:
        """Return minimal time-change args covering every release timestamp.

        Each entry is passed as **kwargs to async_track_utc_time_change, or to
        async_track_time_change for a USE_LOCAL_TIME product (the grid is in
        the product's own time reference, see async_track_releases), so that
        the coordinator is refreshed exactly when new data becomes available.

        Grouping strategy — fewest tracker registrations with no spurious firings:
          1. Group by second, express hour and minute as lists. Valid whenever
             all releases sharing a second form a full cartesian product of their
             hours x minutes (true for any whole-minute interval).
          2. Fall back to grouping by (minute, second) with hour as a list —
             always correct since timestamps in a group share identical
             (minute, second).

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
        """Return the retry delay for the next fast-poll attempt."""
        delay = FAST_POLL_START + self._fast_poll_failures * FAST_POLL_STEP

        return min(delay, self.MAX_FAST_POLL_INTERVAL)

    @callback
    def _schedule_fast_poll(self) -> timedelta:
        """Arm the next fast-poll retry, backing off on consecutive failures.

        The ramp spans release boundaries: only a successful fetch resets it, so
        a prolonged outage settles at MAX_FAST_POLL_INTERVAL instead of being
        pulled back to FAST_POLL_START every time a new release falls due.
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
        """Re-attempt the fetch a failure armed this retry for."""
        self._fast_poll_unsub = None
        _LOGGER.debug("%s: fast-poll retry firing", self.PRODUCT_KEY)
        await self.async_refresh()

    @callback
    def _cancel_fast_poll(self) -> None:
        """Cancel the pending retry, leaving the backoff ramp where it is.

        Separate from _stop_fast_polling because re-arming must not reset the
        ramp: only a success does that.
        """
        if self._fast_poll_unsub is not None:
            self._fast_poll_unsub()
            self._fast_poll_unsub = None

    @callback
    def _stop_fast_polling(self) -> None:
        """Cancel fast polling and reset the backoff ramp."""
        self._cancel_fast_poll()
        self._fast_poll_failures = 0

    # ------------------------------------------------------------------
    # Abstract interface — subclasses implement these
    # ------------------------------------------------------------------

    def _get_url(self, ts: datetime) -> str:
        """Return the URL of release ``ts`` (see radar/urls.py)."""
        return product_url(self.PRODUCT_KEY, ts)

    @abstractmethod
    async def _fetch_and_parse(self, ts: datetime) -> Payload:
        """Fetch and parse the product for release timestamp ts.

        Return (data, metadata), two dicts keyed by the same sub-keys (see
        CoordinatorData). Must raise on any failure — the
        base class owns the stale/retry logic in _async_update_data. Must
        have no side effects: the totals' backfill fetches past releases
        through it (async_fetch_release). What a newly adopted release should
        also do belongs in _async_on_new_release.

        Only the download belongs on the event loop: hand the decoding to
        ``hass.async_add_executor_job``. Decompressing a radar grid takes
        milliseconds per file even on a fast machine, which every other
        integration and automation would otherwise wait out.
        """

    async def _async_on_new_release(
        self, release: datetime, data: Any, metadata: Any
    ) -> None:
        """React to a release this coordinator is about to adopt.

        Called once per release, after a successful fetch and before the data
        is published; may add to ``data``. Must not raise: a failure here must
        not cost the product its update. Nothing by default.
        """

    async def async_fetch_release(self, release: datetime) -> CoordinatorData:
        """Fetch and decode any ``release`` without adopting it.

        For the totals' backfill: the coordinator's own state, schedule and
        retry ramp are untouched, and _async_on_new_release is not called.
        Raises like _fetch_and_parse.
        """
        data, metadata = await self._fetch_and_parse(release)
        return CoordinatorData(data, metadata)

    # ------------------------------------------------------------------
    # Template method — do not override in subclasses
    # ------------------------------------------------------------------

    @callback
    def _record_success(self, release: datetime) -> None:
        """Adopt a freshly fetched release as the cached one.

        One method rather than three statements at each success site: the
        deadline callback is derived from curr_release, so it can only be armed
        after the assignment, and that ordering is easier to hold in one place
        than to remember at every caller.
        """
        self._stop_fast_polling()
        self.curr_release = release
        self._schedule_stale_check()

    async def _async_update_data(self) -> CoordinatorData:
        """HA coordinator hook — owns the full update lifecycle."""
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
