"""Data update coordinator for the dwd precipitation integration."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import cached_property
from itertools import product as cartesian_product
from math import gcd
from typing import Any, ClassVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_UNAVAILABLE_WHEN_STALE
from .utils import get_previous_multiple

_LOGGER = logging.getLogger(__name__)


@dataclass
class ProductMetadata:
    """Parsed per-product metadata, ready for HA state attributes."""

    source_product: str | None
    source_timestamp: datetime | None  # always UTC-aware, or None
    lead_time_minutes: int | None = field(default=None)


@dataclass
class CoordinatorData:
    """Single-product coordinator payload."""

    data: float | list[float | None]
    metadata: ProductMetadata | list[ProductMetadata]


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

    # falls back to RELEASE_INTERVAL when not set.
    STALE_AFTER: ClassVar[timedelta] = timedelta()

    USE_LOCAL_TIME: ClassVar[bool] = False

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

    # def _requires_update(self, now: datetime) -> bool:
    #     """Return True if a newer release is available."""
    #     if self.curr_release is None:
    #         return True

    #     return self.curr_release < self.get_latest_release(now)

    def _data_is_stale(self, now: datetime) -> bool:
        """Return True if cached data has aged beyond the tolerance window."""
        if self.curr_release is None:
            return True

        tolerance = self.STALE_AFTER or self.RELEASE_INTERVAL
        threshold = self.curr_release + self.RELEASE_DELAY + tolerance

        return now > threshold

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

    def _start_fast_polling(self) -> None:
        """Begin 60-second retry polling if not already running."""
        if self._fast_poll_unsub is not None:
            return

        async def _trigger(_now) -> None:
            _LOGGER.debug("%s: fast-poll retry firing", self.PRODUCT_KEY)
            await self.async_refresh()

        self._fast_poll_unsub = async_track_time_interval(
            self.hass, _trigger, timedelta(seconds=60)
        )
        self.config_entry.async_on_unload(self._stop_fast_polling)

    @callback
    def _stop_fast_polling(self) -> None:
        """Cancel fast polling."""
        if self._fast_poll_unsub is not None:
            self._fast_poll_unsub()
            self._fast_poll_unsub = None

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
            return self.data

        try:
            data, metadata = await self._fetch_and_parse(latest_release)
        except Exception as err:
            unavailable_when_stale = self.config_entry.options.get(
                CONF_UNAVAILABLE_WHEN_STALE, True
            )
            if self.data is None or (unavailable_when_stale and self._data_is_stale(now)):
                self._stop_fast_polling()
                raise UpdateFailed(f"{self.PRODUCT_KEY}: {err}") from err

            # Data is still fresh enough — retry silently
            self._start_fast_polling()
            return self.data
        else:
            self.data = CoordinatorData(data, metadata)

        self._stop_fast_polling()
        self.curr_release = latest_release

        return CoordinatorData(data, metadata)
