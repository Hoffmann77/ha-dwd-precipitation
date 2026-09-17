"""Data update coordinator for the dwd precipitation integration."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cached_property
from http import HTTPStatus
from itertools import product as cartesian_product
from math import gcd
from typing import Any, ClassVar

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_UNAVAILABLE_WHEN_STALE
from .utils import get_previous_multiple

_LOGGER = logging.getLogger(__name__)

# Fast-poll retry cadence: the first retry fires after FAST_POLL_START, and each
# further consecutive failure adds FAST_POLL_STEP, until the product's
# MAX_FAST_POLL_INTERVAL caps it.
FAST_POLL_START = timedelta(seconds=60)
FAST_POLL_STEP = timedelta(seconds=10)

# How long an overdue release is given to turn up before the cached value is
# written off (see BaseProductUpdateCoordinator.OVERDUE_GRACE).
DEFAULT_OVERDUE_GRACE = timedelta(minutes=6)

def _describe_fetch_error(err: Exception, release: datetime) -> str:
    """Return a human-readable explanation of a failed product update.

    Home Assistant logs this as ``Error fetching <name> data: <message>``,
    where ``<name>`` already identifies the location and product (e.g.
    "Zuhause rs"), so this message only needs to explain *why* the update
    failed — without repeating the product key or dumping a raw exception.
    """
    release_str = release.strftime("%Y-%m-%d %H:%M UTC")

    if isinstance(err, aiohttp.ClientResponseError):
        if err.status == HTTPStatus.NOT_FOUND:
            return (
                f"DWD has not published the {release_str} release yet "
                "(HTTP 404). This is normal near release time; it will be "
                "retried automatically."
            )
        return (
            f"DWD OpenData returned HTTP {err.status} ({err.message}) for the "
            f"{release_str} release."
        )

    if isinstance(err, aiohttp.ClientConnectionError):
        return (
            f"Could not reach DWD OpenData for the {release_str} release: {err}"
        )

    return f"Could not process the {release_str} release: {err}"


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


@dataclass
class CoordinatorData:
    """Single-product coordinator payload.

    ``data``/``metadata`` are a scalar+``ProductMetadata`` for RADOLAN products,
    parallel lists for RS, or parallel dicts keyed by entity sub-key for RV.
    """

    data: float | list[float | None] | dict[str, Any]
    metadata: ProductMetadata | list[ProductMetadata] | dict[str, ProductMetadata]


class BaseProductUpdateCoordinator(DataUpdateCoordinator[CoordinatorData], ABC):
    """Abstract per-product data update coordinator.

    Each concrete subclass represents one DWD product and owns its own
    update schedule. Subclasses must define PRODUCT_KEY, timing ClassVars,
    and implement index() and _fetch_and_parse().

    """

    PRODUCT_KEY: ClassVar[str] = ""

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

    USE_LOCAL_TIME: ClassVar[bool] = False

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
            name=f"{entry.data[CONF_NAME]} {self.PRODUCT_KEY}",
            update_interval=None,  # event-driven via track_time_change_args
        )
        self.config_entry = entry
        self.async_client = async_client
        self.coords = (lat, lon)
        self.curr_release: datetime | None = None
        self._fast_poll_unsub = None
        self._fast_poll_failures = 0
        self._stale_unsub = None
        entry.async_on_unload(self._stop_fast_polling)
        entry.async_on_unload(self._cancel_stale_check)

    # ------------------------------------------------------------------
    # Concrete helpers
    # ------------------------------------------------------------------

    def _get_latest_release(self, now: datetime) -> datetime:
        """Return the most recent valid release timestamp."""
        prev = get_previous_multiple(
            now - self.RELEASE_DELAY,
            self.RELEASE_INTERVAL,
            self.RELEASE_OFFSET,
        )

        return dt_util.as_utc(prev)

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

        return (
            self._next_release_after(self.curr_release)
            + self.RELEASE_DELAY
            + self.OVERDUE_GRACE
        )

    def _next_release_after(self, release: datetime) -> datetime:
        """Return the first scheduled release after the given one.

        Done in the product's own time reference rather than by adding
        RELEASE_INTERVAL to a UTC timestamp: for USE_LOCAL_TIME products the
        release grid is a local wall-clock one, so consecutive releases are 23
        or 25 hours apart on the two DST changeover days. Adding 24 h there
        would put the deadline an hour off — on the autumn one, before the file
        it is waiting for could even exist.
        """
        reference = dt_util.as_local(release) if self.USE_LOCAL_TIME else release

        return dt_util.as_utc(reference + self.RELEASE_INTERVAL)

    def _data_is_stale(self, now: datetime) -> bool:
        """Return True if the overdue release has gone unfetched for too long."""
        deadline = self._stale_deadline()

        return deadline is None or now > deadline

    @property
    def data_is_stale(self) -> bool:
        """Return True if the cached value is past its deadline right now.

        Entities read this for their availability, so "stale" is a fact about
        the clock rather than the outcome of the last fetch. It stays true even
        if no further fetch is ever attempted.
        """
        now = dt_util.now() if self.USE_LOCAL_TIME else dt_util.utcnow()

        return self._data_is_stale(now)

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

        @callback
        def _expire(_now) -> None:
            self._stale_unsub = None
            _LOGGER.debug("%s: cached value reached its deadline", self.PRODUCT_KEY)
            self.async_update_listeners()

        self._stale_unsub = async_track_point_in_time(self.hass, _expire, deadline)

    @cached_property
    def track_time_change_args(self) -> list[dict]:
        """Return minimal UTC time-change args covering every release timestamp.

        Each entry is passed as **kwargs to async_track_utc_time_change so
        that the coordinator is refreshed exactly when new data becomes available.

        Grouping strategy — fewest tracker registrations with no spurious firings:
          1. Group by second, express hour and minute as lists. Valid whenever
             all releases sharing a second form a full cartesian product of their
             hours x minutes (true for any whole-minute interval).
          2. Fall back to grouping by (minute, second) with hour as a list —
             always correct since timestamps in a group share identical
             (minute, second).

        """
        release_interval = self.RELEASE_INTERVAL
        release_delay = self.RELEASE_DELAY
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
    def _schedule_fast_poll(self) -> None:
        """Arm the next fast-poll retry, backing off on consecutive failures.

        The ramp spans release boundaries: only a successful fetch resets it, so
        a prolonged outage settles at MAX_FAST_POLL_INTERVAL instead of being
        pulled back to FAST_POLL_START every time a new release falls due.
        """
        delay = self._fast_poll_delay()
        self._fast_poll_failures += 1

        if self._fast_poll_unsub is not None:
            self._fast_poll_unsub()
            self._fast_poll_unsub = None

        async def _trigger(_now) -> None:
            self._fast_poll_unsub = None
            _LOGGER.debug("%s: fast-poll retry firing", self.PRODUCT_KEY)
            await self.async_refresh()

        _LOGGER.debug(
            "%s: scheduling fast-poll retry in %ss (attempt %s)",
            self.PRODUCT_KEY,
            int(delay.total_seconds()),
            self._fast_poll_failures,
        )
        self._fast_poll_unsub = async_call_later(self.hass, delay, _trigger)

    @callback
    def _stop_fast_polling(self) -> None:
        """Cancel fast polling and reset the backoff ramp."""
        if self._fast_poll_unsub is not None:
            self._fast_poll_unsub()
            self._fast_poll_unsub = None

        self._fast_poll_failures = 0

    # ------------------------------------------------------------------
    # Abstract interface — subclasses implement these
    # ------------------------------------------------------------------

    @abstractmethod
    def index(self):
        """Grid cell index for this location. Override with @cached_property."""

    @abstractmethod
    async def _fetch_and_parse(self, ts: datetime) -> tuple[Any, Any]:
        """Fetch and parse the product for release timestamp ts.

        Return (precipitation, metadata). Must raise on any failure — the
        base class owns the stale/retry logic in _async_update_data.

        """

    # ------------------------------------------------------------------
    # Template method — do not override in subclasses
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> CoordinatorData:
        """HA coordinator hook — owns the full update lifecycle."""
        now = dt_util.now() if self.USE_LOCAL_TIME else dt_util.utcnow()
        latest_release = self._get_latest_release(now)

        if self.curr_release is not None and self.curr_release >= latest_release:
            self._stop_fast_polling()
            return self.data

        try:
            data, metadata = await self._fetch_and_parse(latest_release)
        except Exception as err:
            # Keep retrying regardless of availability: the backoff governs the
            # retry cadence, _data_is_stale() governs what HA shows.
            self._schedule_fast_poll()

            unavailable_when_stale = self.config_entry.options.get(
                CONF_UNAVAILABLE_WHEN_STALE, True
            )
            if self.data is None or (unavailable_when_stale and self._data_is_stale(now)):
                raise UpdateFailed(_describe_fetch_error(err, latest_release)) from err

            # Data is still fresh enough — retry silently
            return self.data

        self._stop_fast_polling()
        self.curr_release = latest_release
        self._schedule_stale_check()

        return CoordinatorData(data, metadata)
