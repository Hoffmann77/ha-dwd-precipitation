"""DWD radar products."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from functools import cached_property
from typing import Any
from io import BytesIO

import aiohttp
import numpy as np
from homeassistant.helpers.storage import Store

from .coordinator import (
    DEFAULT_OVERDUE_GRACE,
    BaseProductUpdateCoordinator,
    ProductMetadata,
)
from .utils import FailureLatch, async_get, iso
from .radar.tar_range import fetch_tar_members, member_names, members_from_archive
from .radar import (
    read_odim_composite_cell,
    read_odim_classification_cell,
    RS_GRID_SHAPE,
)
from .radar.nowcast import (
    FUTURE_HOUR_LEADS,
    HOUR1_LEADS,
    HOUR2_LEADS,
    LEAD_STEP,
    LEADS,
    STEPS_PER_HOUR,
    bucket_max_intensity,
    MM_DECIMALS,
    detect_start_end,
    peak_rolling_hour,
    rolling_hour_sums,
)
from .rain_events import (
    RainEventsState,
    at_stake,
    record_measured,
    steps_to_fill,
    update as update_rain_events,
    wet_step_milli,
)
from .const import (
    DOMAIN,
    CONF_DRY_STREAK_SOURCE,
    DEFAULT_DRY_STREAK_SOURCE,
    DRY_STREAK_SOURCE_RW,
    DRY_STREAK_SOURCES,
    RW_SLIDING_KEY,
    CONF_RAIN_EVENTS,
    DEFAULT_RAIN_EVENTS,
    CONF_RAIN_EVENT_THRESHOLD,
    DEFAULT_RAIN_EVENT_THRESHOLD,
    CONF_FULL_ROLLING_SERIES,
    DEFAULT_FULL_ROLLING_SERIES,
    CONF_PRECIPITATION_THRESHOLD,
    DEFAULT_PRECIPITATION_THRESHOLD,
    CONF_PRECIPITATION_END_ALGORITHM,
    DEFAULT_PRECIPITATION_END_ALGORITHM,
    PRECIP_TYPE_BY_INDEX,
    DWD_RADOLAN_URL,
    DWD_COMPOSITE_URL,
)

_LOGGER = logging.getLogger(__name__)


def _parse_odim_ts(date: str | None, time: str | None) -> datetime | None:
    """Parse ODIM date/time strings (YYYYMMDD / HHMMSS) into a UTC datetime."""
    if not date or not time:
        return None
    try:
        return datetime.strptime(f"{date}{time}", "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _nan_to_none(value: float) -> float | None:
    """Return a cell reading as a float, None for nodata (NaN)."""
    value = float(value)
    return None if np.isnan(value) else value


def _mm(value: float | None) -> float | None:
    """Round an amount to the ODIM resolution; the float32 carries noise below it."""
    return round(value, MM_DECIMALS) if value is not None else None


def _radvor_prefix(product: str, ts: datetime) -> str:
    """Return the name stem of a RADVOR release (``composite_rs_<ts>``).

    The tar is ``<stem>.tar``, its members ``<stem>_<lead>-hd5``.
    """
    return f"composite_{product}_{ts:%Y%m%d_%H%M}"


# The three non-overlapping RS hours: past, next and second-next.
RS_HOURLY_LEADS = (0, 60, 120)


# A 206 answer is one window of a RADVOR tar, at most a few members of under
# 1 MB each; anything near this cap is not what was asked for.
RANGE_MAX_BYTES = 8 * 1024 * 1024

RAIN_EVENTS_STORE_VERSION = 1

# One background round of filling missed analyses takes this long, at most.
RAIN_FILL_BUDGET = timedelta(seconds=30)

# How soon the rain_events state is written: promptly while an event or an
# unknown step is at stake, otherwise not before shutdown (see
# RadvorRV._schedule_rain_save).
RAIN_SAVE_DELAY = timedelta(seconds=10)
RAIN_IDLE_SAVE_DELAY = timedelta(hours=12)


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


def dry_streak_coordinator_key(options) -> str:
    """Return the key of the coordinator the dry streak counts.

    The option's values are product keys, except that RW counts its 10-minute
    runs. An unknown stored value counts as the default. RadolanRW10.is_needed
    and the sensor setup both ask this, so the coordinator the sensor binds to
    is always one that was built.
    """
    source = options.get(CONF_DRY_STREAK_SOURCE, DEFAULT_DRY_STREAK_SOURCE)
    if source not in DRY_STREAK_SOURCES:
        source = DEFAULT_DRY_STREAK_SOURCE
    return RW_SLIDING_KEY if source == DRY_STREAK_SOURCE_RW else source


def rain_events_enabled(options) -> bool:
    """Whether the entry tracks rain events (the "Rain events" sensor)."""
    return bool(options.get(CONF_RAIN_EVENTS, DEFAULT_RAIN_EVENTS))


def rain_events_store_key(entry_id: str) -> str:
    """Return the Store key of one config entry's rain_events state."""
    return f"{DOMAIN}.{entry_id}.rain_events"


def rain_events_store(hass, entry_id: str) -> Store:
    """Return the Store of one config entry's rain_events state.

    The one place it is built, so a version bump (or a migration) reaches the
    tracker and the clean-up on option-off and entry removal alike.
    """
    return Store(hass, RAIN_EVENTS_STORE_VERSION, rain_events_store_key(entry_id))


def _tar_members(content: bytes, prefix: str, leads) -> dict[str, bytes]:
    """Return the requested members of a whole RADVOR tar, by name (blocking)."""
    return members_from_archive(content, member_names(prefix, leads))


def _decode_cells(
    members: dict[str, bytes], prefix: str, leads, cell: tuple[int, int], label: str
) -> dict[int, tuple[float | None, dict] | None]:
    """Decode one grid cell from each requested RADVOR member.

    Returns ``{lead: (value, dataset_what)}``; ``value`` is ``None`` for nodata,
    and a member missing from ``members`` maps to ``None`` (logged).
    """
    row, col = cell
    out: dict[int, tuple[float | None, dict] | None] = {}
    for lead, name in zip(leads, member_names(prefix, leads)):
        if (member := members.get(name)) is None:
            _LOGGER.warning("%s tar member not found: %s", label, name)
            out[lead] = None
            continue

        val, what = read_odim_composite_cell(
            BytesIO(member), row, col, expected_shape=RS_GRID_SHAPE
        )
        out[lead] = (_nan_to_none(val), what)
    return out



def _odim_window(what: dict) -> tuple[datetime | None, datetime | None]:
    """Return the (start, end) validity window of an ODIM /dataset/what."""
    return (
        _parse_odim_ts(what.get("startdate"), what.get("starttime")),
        _parse_odim_ts(what.get("enddate"), what.get("endtime")),
    )


def _odim_metadata(what: dict, lead: int | None = None) -> ProductMetadata:
    """Return the metadata of one ODIM grid from its /dataset/what.

    The window ends at the release time plus ``lead``, so the release (the
    source timestamp) is the window end minus the lead.
    """
    data_start, data_end = _odim_window(what)
    return ProductMetadata(
        source_product=what.get("prodname") or what.get("product"),
        source_timestamp=(
            data_end - timedelta(minutes=lead or 0) if data_end else None
        ),
        lead_time_minutes=lead,
        data_start=data_start,
        data_end=data_end,
    )


def _peak_hour_payload(
    sums: list[float | None],
    windows: list[tuple[datetime | None, datetime | None]],
    series_leads: list[int],
    base: ProductMetadata | None,
) -> tuple[float | None, ProductMetadata]:
    """Build the "Peak hourly precipitation next 120 min" value and metadata.

    ``sums`` (rolling 60-minute totals, mm) and ``windows`` are aligned to
    LEADS; ``series_leads`` picks the points exposed as ``rolling_1h``;
    ``base`` names the product and release. RS and RV both land here, so the
    two sources cannot drift apart in shape.
    """
    rolling_1h = [
        {
            "lead": lead,
            "start": iso(windows[lead // LEAD_STEP][0]),
            "end": iso(windows[lead // LEAD_STEP][1]),
            "value": sums[lead // LEAD_STEP],
        }
        for lead in series_leads
    ]

    peak, peak_lead = peak_rolling_hour(sums)
    # A dry forecast has no wettest hour, so it gets no window either.
    start, end = windows[peak_lead // LEAD_STEP] if peak else (None, None)
    return peak, ProductMetadata(
        source_product=base.source_product if base else None,
        source_timestamp=base.source_timestamp if base else None,
        lead_time_minutes=peak_lead if peak else None,
        data_start=start,
        data_end=end,
        rolling_1h=rolling_1h,
    )


def _next_120(
    hour1: float | None,
    hour2: float | None,
    meta1: ProductMetadata | None,
    meta2: ProductMetadata | None,
) -> tuple[float | None, ProductMetadata | None]:
    """Return RS's 120-minute forecast total: its two forecast hours added.

    Half a forecast is not a 120-minute total, so a missing hour makes the
    whole value None rather than counting as dry.
    """
    if hour1 is None or hour2 is None or meta1 is None or meta2 is None:
        return None, None

    return round(hour1 + hour2, MM_DECIMALS), ProductMetadata(
        source_product=meta1.source_product,
        source_timestamp=meta1.source_timestamp,
        lead_time_minutes=120,
        data_start=meta1.data_start,
        data_end=meta2.data_end,
    )


class WholeFileProduct(BaseProductUpdateCoordinator, ABC):
    """A product published as one file per release, decoded whole.

    Fetching is the same for all of them: download ``_get_url(ts)`` on the
    event loop, decode it with ``_parse(content, ts)`` in the executor.
    """

    @abstractmethod
    def _get_url(self, ts: datetime) -> str:
        """Return the URL of release ``ts``."""

    @abstractmethod
    def _parse(self, content: bytes, ts: datetime) -> tuple[Any, Any]:
        """Return (data, metadata) from the file's bytes (blocking)."""

    async def _fetch_and_parse(self, ts: datetime) -> tuple[Any, Any]:
        """Fetch the release's file and decode it off the event loop."""
        response = await async_get(self._get_url(ts), self.async_client)
        return await self.hass.async_add_executor_job(
            self._parse, response.content, ts
        )


class RadvorProduct(WholeFileProduct, ABC):
    """A RADVOR nowcast (RS, RV): one tar of 25 ODIM_H5 members per release.

    The tar is ``<prefix>.tar`` under the product's key, its members
    ``<prefix>_<lead>-hd5``.
    """

    def _prefix(self, ts: datetime) -> str:
        """Return release ``ts``'s name stem (``composite_rs_<ts>``)."""
        return _radvor_prefix(self.PRODUCT_KEY, ts)

    def _get_url(self, ts: datetime) -> str:
        """Return the URL for the tar archive."""
        return f"{DWD_COMPOSITE_URL}/{self.PRODUCT_KEY}/{self._prefix(ts)}.tar"

    @cached_property
    def _range_latch(self) -> FailureLatch:
        """Whether range reads of this product are falling back right now."""
        return FailureLatch()

    async def _async_read_members(self, ts: datetime, leads) -> dict[str, bytes]:
        """Fetch only the requested members of release ``ts``, by range reads.

        Falls back to the whole archive on anything unexpected (see
        radar.tar_range), unpacked in the executor; a missing release still
        raises, like any fetch. A fallback is said once per run of them:
        values are unaffected, but every update then downloads several times
        the data, so a lasting change on DWD's side should not go unnoticed.
        """
        url, prefix = self._get_url(ts), self._prefix(ts)

        async def fetch(target: str, headers):
            return await async_get(
                target, self.async_client, headers=headers,
                partial_max_bytes=RANGE_MAX_BYTES,
            )

        async def extract(content: bytes, wanted) -> dict[str, bytes]:
            return await self.hass.async_add_executor_job(
                members_from_archive, content, wanted
            )

        result = await fetch_tar_members(
            fetch, url, member_names(prefix, LEADS), member_names(prefix, leads), extract
        )
        _LOGGER.debug(
            "Read %s member(s) of %s in %s request(s), %s bytes%s",
            len(result.members),
            url,
            result.requests,
            result.bytes_read,
            " (whole archive)" if result.whole else "",
        )
        if result.whole and self._range_latch.fail():
            _LOGGER.warning(
                "Reading whole DWD %s archives: partial (range) downloads of "
                "%s did not work. Values are not affected, but each update "
                "now downloads several times the data; this is said again "
                "only when range downloads work again",
                self.PRODUCT_LABEL,
                url,
            )
        elif not result.whole and self._range_latch.ok():
            _LOGGER.info(
                "Partial (range) downloads of DWD %s archives work again",
                self.PRODUCT_LABEL,
            )
        return result.members


class RadvorRS(RadvorProduct):
    """DWD RS precipitation nowcast (RADVOR, ODIM_H5 format).

    RS is published every 5 minutes as one tar of 25 ODIM_H5 members (leads
    0..120 min, 5-min steps). Each member is a *rolling 60-minute* accumulation
    (mm) ending at T+lead, so consecutive members overlap by 55 minutes.

    precipitation → list[float | None], metadata → list[ProductMetadata | None],
    both indexed:

    * ``0`` / ``1`` / ``2`` — the non-overlapping hours: leads 0 / 60 / 120.
    * ``3`` — the wettest rolling hour wholly in the future, with the full
      25-point rolling-hour series as ``rolling_1h`` on its metadata. Only
      filled with the ``full_rolling_series`` option on, since it needs all 25
      members decoded; otherwise ``None`` and RV provides the sensor (see
      RadvorRV).
    * ``4`` — the whole 120-minute forecast: leads 60 + 120, so it is exactly
      the sum of the two forecast sensors. ``None`` unless both are present.
    """

    PRODUCT_KEY = "rs"

    PRODUCT_LABEL = "RS precipitation nowcast"

    RELEASE_INTERVAL = timedelta(minutes=5)

    RELEASE_DELAY = timedelta(minutes=4, seconds=10)

    RELEASE_OFFSET = timedelta()

    # 6 min outlasts one whole 5-min cycle: each grid is a 60-minute
    # accumulation, so a value one release old is still a fair answer to
    # "how much fell in the last hour".
    OVERDUE_GRACE = DEFAULT_OVERDUE_GRACE

    @property
    def full_rolling_series(self) -> bool:
        """Whether this entry decodes every member for the rolling-hour series."""
        return self.config_entry.options.get(
            CONF_FULL_ROLLING_SERIES, DEFAULT_FULL_ROLLING_SERIES
        )

    async def _fetch_and_parse(self, ts: datetime) -> tuple[list, list]:
        """Fetch the members this entry decodes, then decode them off the loop.

        All 25 for the full rolling series, so the whole archive; otherwise
        only the three fixed hours, read by range (~20 % of the bytes).
        """
        if self.full_rolling_series:
            return await super()._fetch_and_parse(ts)
        members = await self._async_read_members(ts, RS_HOURLY_LEADS)
        return await self.hass.async_add_executor_job(self._parse_members, members, ts)

    def _parse(self, content: bytes, ts: datetime) -> tuple[list, list]:
        """Derive the RS entity payloads from a whole tar (blocking)."""
        return self._parse_members(_tar_members(content, self._prefix(ts), LEADS), ts)

    def _parse_members(
        self, members: dict[str, bytes], ts: datetime
    ) -> tuple[list, list]:
        """Derive the RS entity payloads from its members' bytes (blocking)."""
        full = self.full_rolling_series
        cells = _decode_cells(
            members,
            self._prefix(ts),
            LEADS if full else RS_HOURLY_LEADS,
            self.index,
            "RS",
        )

        per_lead = {
            lead: _odim_metadata(cell[1], lead) if cell else None
            for lead, cell in cells.items()
        }

        data = [cells[lead][0] if cells[lead] else None for lead in RS_HOURLY_LEADS]
        metadata = [per_lead[lead] for lead in RS_HOURLY_LEADS]
        next_120 = _next_120(data[1], data[2], metadata[1], metadata[2])

        if not full:
            return data + [None, next_120[0]], metadata + [None, next_120[1]]

        sums = [_mm(cells[lead][0]) if cells[lead] else None for lead in LEADS]
        windows = [
            (m.data_start, m.data_end) if (m := per_lead[lead]) else (None, None)
            for lead in LEADS
        ]
        base = next((m for m in per_lead.values() if m is not None), None)
        peak, peak_meta = _peak_hour_payload(sums, windows, LEADS, base)
        return data + [peak, next_120[0]], metadata + [peak_meta, next_120[1]]


class RadvorRV(RadvorProduct):
    """DWD RV precipitation nowcast (RADVOR, ODIM_H5 format).

    RV is published every 5 minutes as one tar of 25 ODIM_H5 members
    (leads 0..120 min, 5-min steps). Each member is a 5-minute rainfall
    accumulation (mm) on the same grid/projection as RS.

    From the per-cell 5-minute series this coordinator derives:

    * ``intensity_000`` / ``amount_000`` — the analysis (lead 0, the 5 minutes
      ending at T) as an hourly rate (mm/h) and as the raw amount (mm).
    * ``max_060`` / ``max_120`` / ``max_000_120`` — peak intensity (mm/h) over
      [T, T+60] / [T+60, T+120] / [T, T+120].
    * ``start_in`` / ``start_at`` / ``end_in`` / ``end_at`` — when precipitation
      begins / ends at the location (see radar.nowcast.detect_start_end).
    * ``rain_within_2h`` — whether any precipitation is forecast within the
      2-hour horizon (drives the "rain expected" binary sensor). Its metadata
      carries the full 25-point 5-minute forecast series as ``samples``.
    * ``peak_1h`` — the wettest rolling hour wholly in the future, summed from
      twelve 5-minute steps (identical to the RS member for that window). Its
      metadata carries those 13 rolling hours as ``rolling_1h``. Used unless
      the ``full_rolling_series`` option hands the sensor to RS.

    precipitation → dict[str, value], metadata → dict[str, ProductMetadata]
    """

    PRODUCT_KEY = "rv"

    PRODUCT_LABEL = "RV precipitation forecast"

    RELEASE_INTERVAL = timedelta(minutes=5)

    RELEASE_DELAY = timedelta(minutes=4, seconds=10)

    RELEASE_OFFSET = timedelta()

    # A 2-hour forecast does not turn wrong in five minutes, so keep trying
    # across one whole missed release before dropping the entities.
    OVERDUE_GRACE = DEFAULT_OVERDUE_GRACE

    # rain_events persistence; None leaves the tracker off: the option is off,
    # or a test builds the coordinator without HA.
    _rain_store: Store | None = None
    _rain_state: RainEventsState | None = None
    _rain_saved_ended: str | None = None
    # The background fill-and-track round, if one was started; and the last
    # view this run published, shown while a round is still running.
    _rain_fill_task: asyncio.Task | None = None
    _rain_view: dict | None = None

    def __init__(self, hass, entry, async_client, lat, lon) -> None:
        """Initialize the coordinator and, if tracked, its rain_events store."""
        super().__init__(hass, entry, async_client, lat, lon)
        if rain_events_enabled(entry.options):
            self._rain_store = rain_events_store(hass, entry.entry_id)

    @cached_property
    def _rain_fill_latch(self) -> FailureLatch:
        """Whether filling missed analyses is failing right now."""
        return FailureLatch()

    @cached_property
    def _rain_latch(self) -> FailureLatch:
        """Whether the rain_events tracker is failing right now."""
        return FailureLatch()

    async def _async_on_new_release(
        self, release: datetime, data: dict, metadata: dict
    ) -> None:
        """Feed the release to the rain_events tracker, if the entry has one."""
        if self._rain_store is not None:
            data["rain_events"] = await self._async_rain_events(release, metadata)

    # ------------------------------------------------------------------
    # rain_events: fill the missed analyses, track, persist
    # ------------------------------------------------------------------

    async def _async_rain_events(
        self, release: datetime, metadata: dict
    ) -> dict | None:
        """Update the rain_events tracker with this release; None if it failed.

        The release's 25-point series (``rain_within_2h`` samples) is the
        analysis followed by the 24 forecast steps.

        The missed analyses must be filled *before* the tracker sees the
        release: updating first and recomputing after the fill can swap event
        ids and lose ``forecast_at_onset`` when it rained during a downtime.
        A fill takes seconds, though, and this runs inside the RV refresh
        that setup waits for. So when there is anything to fill, the tracker
        update moves to a background task that fills, updates and publishes
        the view; until then the sensor keeps the view it showed before (none
        right after a restart). Every later release queues behind a running
        fill, so releases always reach the tracker in order.

        A failure here must not cost the RV sensors their update, so it is
        logged (once per run of failures) and the attribute is left out.
        """
        try:
            series = metadata["rain_within_2h"]
            base = series.source_timestamp or release
            values = [s["value"] for s in series.samples]
            state = await self._async_rain_state()
        except Exception:
            self._rain_failed()
            return None
        milli = wet_step_milli(
            self.config_entry.options.get(
                CONF_RAIN_EVENT_THRESHOLD, DEFAULT_RAIN_EVENT_THRESHOLD
            )
        )
        running = self._rain_fill_task is not None and not self._rain_fill_task.done()
        if running or steps_to_fill(state, base):
            self._rain_fill_task = self.config_entry.async_create_background_task(
                self.hass,
                self._async_fill_and_track(
                    self._rain_fill_task if running else None, state, base, values, milli
                ),
                "dwd_precipitation rain_events fill",
            )
            return self._rain_view
        return self._track_rain(state, base, values, milli)

    def _track_rain(
        self,
        state: RainEventsState,
        base: datetime,
        values: list[float | None],
        milli: int,
    ) -> dict | None:
        """Feed release ``base`` to the tracker (filled already); None on failure."""
        try:
            view = update_rain_events(state, base, values[0], values[1:], milli)
        except Exception:
            self._rain_failed()
            return None
        self._rain_latch.ok()
        self._schedule_rain_save(state)
        self._rain_view = view
        return view

    def _rain_failed(self) -> None:
        """Log a tracker failure once per run of failures."""
        if self._rain_latch.fail():
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
            self._rain_failed()
            return
        view = self._track_rain(state, base, values, milli)
        # A newer release queued behind this one publishes its own view.
        if (
            view is not None
            and self.data is not None
            and self._rain_fill_task is asyncio.current_task()
        ):
            self.data.data["rain_events"] = view
            self.async_update_listeners()

    async def _async_rain_state(self) -> RainEventsState:
        """Return the tracker state, loading it from the store on first use."""
        if self._rain_state is None:
            raw = await self._rain_store.async_load()
            try:
                self._rain_state = RainEventsState.from_dict(raw) if raw else RainEventsState()
            except (KeyError, TypeError, ValueError) as err:
                _LOGGER.warning(
                    "Discarding the saved rain_events state, which could not be "
                    "read (%s). Event ids start over; nothing else is affected",
                    err,
                )
                self._rain_state = RainEventsState()
            self._rain_saved_ended = (self._rain_state.last_ended or {}).get("id")
        return self._rain_state

    async def _async_fill_missed(self, state: RainEventsState, base: datetime) -> None:
        """Fetch the analysis of each missed release still in the window.

        Sequential, newest first, within RAIN_FILL_BUDGET; the first failure
        ends the round and the rest wait for the next release. Each fill reads
        only the analysis member, ~4-7 % of the archive. Runs in the
        background round, never in the refresh (see _async_rain_events).
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
                    value = await self._async_fetch_analysis(step_end)
            except Exception as err:  # noqa: BLE001 - every failure is retried later
                if budget.expired():
                    # Our own limit, not a failure: the rest waits for the
                    # next release.
                    _LOGGER.debug(
                        "Fill budget used up at the RV analysis of %s", step_end
                    )
                    return
                _LOGGER.debug("Could not fill the RV analysis of %s: %s", step_end, err)
                if self._rain_fill_latch.fail():
                    _LOGGER.warning(_describe_fill_failure(err, step_end))
                return
            _LOGGER.debug("Filled the RV analysis of %s: %s", step_end, value)
            record_measured(state, step_end, value)
        self._rain_fill_latch.ok()

    async def _async_fetch_analysis(self, step_end: datetime) -> float | None:
        """Return the analysis (lead 0) of release ``step_end``; None for nodata."""
        members = await self._async_read_members(step_end, [0])
        return await self.hass.async_add_executor_job(
            self._parse_analysis, members, self._prefix(step_end), step_end
        )

    def _parse_analysis(
        self, members: dict[str, bytes], prefix: str, step_end: datetime
    ) -> float | None:
        """Decode the analysis member of a missed release (blocking)."""
        cell = _decode_cells(members, prefix, [0], self.index, "RV")[0]
        if cell is None:
            raise ValueError(f"{prefix} has no analysis member")
        _, end = _odim_window(cell[1])
        if end != step_end:
            raise ValueError(f"{prefix} analysis ends at {end}, not {step_end}")
        return _mm(cell[0])

    def _schedule_rain_save(self, state: RainEventsState) -> None:
        """Persist the tracker: soon while it matters, else at shutdown.

        Every release changes the state, but on a dry day nothing in it is
        worth an SD-card write every 5 minutes: losing it in a crash costs
        one fill round after the restart. The long delay keeps being pushed
        back by each release, and Home Assistant writes pending saves when
        it stops.
        """
        ended = (state.last_ended or {}).get("id")
        if at_stake(state) or ended != self._rain_saved_ended:
            delay = RAIN_SAVE_DELAY
            self._rain_saved_ended = ended
        else:
            delay = RAIN_IDLE_SAVE_DELAY
        self._rain_store.async_delay_save(state.as_dict, delay.total_seconds())

    async def async_save_rain_events(self) -> None:
        """Write the tracker now (entry unload), so a reload reads it back."""
        if self._rain_store is not None and self._rain_state is not None:
            await self._rain_store.async_save(self._rain_state.as_dict())

    def _parse(self, content: bytes, ts: datetime) -> tuple[dict, dict]:
        """Derive the RV entity payloads from the tar bytes (blocking)."""
        prefix = self._prefix(ts)
        cells = _decode_cells(
            _tar_members(content, prefix, LEADS), prefix, LEADS, self.index, "RV"
        )

        # Per-lead 5-minute cell values (mm) and window bounds, aligned to LEADS.
        values: list[float | None] = []
        starts: list[datetime | None] = []
        ends: list[datetime | None] = []
        base_ts: datetime | None = None

        for lead in LEADS:
            cell = cells[lead]
            if cell is None:
                values.append(None)
                starts.append(None)
                ends.append(None)
                continue

            data_start, data_end = _odim_window(cell[1])
            values.append(_mm(cell[0]))
            starts.append(data_start)
            ends.append(data_end)
            # Base run time T = end of the analysis window (lead 0).
            if lead == 0 and data_end is not None:
                base_ts = data_end

        # The user configures the threshold as an intensity (mm/h); the
        # detection works on 5-minute accumulations, so convert back to mm/5min.
        threshold_mmh = self.config_entry.options.get(
            CONF_PRECIPITATION_THRESHOLD, DEFAULT_PRECIPITATION_THRESHOLD
        )
        threshold = threshold_mmh / STEPS_PER_HOUR
        end_algorithm = self.config_entry.options.get(
            CONF_PRECIPITATION_END_ALGORITHM, DEFAULT_PRECIPITATION_END_ALGORITHM
        )
        start_in, end_in = detect_start_end(values, threshold, end_algorithm)

        def _at(minutes: int | None) -> datetime | None:
            if minutes is None or base_ts is None:
                return None
            return base_ts + timedelta(minutes=minutes)

        def _samples(leads: list[int]) -> list[dict]:
            out = []
            for lead in leads:
                i = lead // LEAD_STEP
                value = values[i]
                out.append({
                    "lead": lead,
                    "start": iso(starts[i]),
                    "end": iso(ends[i]),
                    "value": value,
                    # 5-minute accumulation extrapolated to an hourly rate.
                    "intensity": (
                        round(value * STEPS_PER_HOUR, 2)
                        if value is not None
                        else None
                    ),
                })
            return out

        def _bucket_meta(leads: list[int], lead_minutes: int) -> ProductMetadata:
            return ProductMetadata(
                source_product="RV",
                source_timestamp=base_ts,
                lead_time_minutes=lead_minutes,
                data_start=starts[leads[0] // LEAD_STEP],
                data_end=ends[leads[-1] // LEAD_STEP],
            )

        timing_meta = ProductMetadata(source_product="RV", source_timestamp=base_ts)
        hour1_meta = _bucket_meta(HOUR1_LEADS, 60)
        hour2_meta = _bucket_meta(HOUR2_LEADS, 120)
        both_meta = _bucket_meta(HOUR1_LEADS + HOUR2_LEADS, 120)
        # The rain-expected flag owns the raw forecast curve: the full 25-point
        # 5-minute series is attached here so the binary sensor can surface it.
        rain_meta = ProductMetadata(
            source_product="RV",
            source_timestamp=base_ts,
            data_start=starts[0],
            data_end=ends[-1],
            samples=_samples(LEADS),
        )

        # Rolling hour ending at T+L = the twelve 5-minute steps L-55..L.
        windows = [(None, None)] * len(LEADS)
        for lead in FUTURE_HOUR_LEADS:
            start = starts[(lead - 60 + LEAD_STEP) // LEAD_STEP]
            end = ends[lead // LEAD_STEP]
            if start is None and end is not None:
                start = end - timedelta(minutes=60)
            windows[lead // LEAD_STEP] = (start, end)
        peak_1h, peak_meta = _peak_hour_payload(
            rolling_hour_sums(values), windows, FUTURE_HOUR_LEADS, timing_meta
        )

        # The analysis (lead 0) is the 5 minutes ending at T: the only measured
        # step in the release, reported as an hourly rate like the peaks. Both
        # are rounded to the ODIM resolution; x12 keeps it exact.
        now_mm = values[0]
        now_meta = ProductMetadata(
            source_product="RV",
            source_timestamp=base_ts,
            lead_time_minutes=0,
            data_start=starts[0],
            data_end=ends[0],
        )

        data = {
            "intensity_000": (
                round(now_mm * STEPS_PER_HOUR, MM_DECIMALS)
                if now_mm is not None
                else None
            ),
            "amount_000": now_mm,
            "max_060": bucket_max_intensity(values, HOUR1_LEADS),
            "max_120": bucket_max_intensity(values, HOUR2_LEADS),
            "max_000_120": bucket_max_intensity(values, HOUR1_LEADS + HOUR2_LEADS),
            "start_in": start_in,
            "start_at": _at(start_in),
            "end_in": end_in,
            "end_at": _at(end_in),
            "rain_within_2h": start_in is not None,
            "peak_1h": peak_1h,
        }
        metadata = {
            "intensity_000": now_meta,
            "amount_000": now_meta,
            "max_060": hour1_meta,
            "max_120": hour2_meta,
            "max_000_120": both_meta,
            "start_in": timing_meta,
            "start_at": timing_meta,
            "end_in": timing_meta,
            "end_at": timing_meta,
            "rain_within_2h": rain_meta,
            "peak_1h": peak_meta,
        }
        return data, metadata


class HymecNG(WholeFileProduct):
    """DWD HymecNG precipitation-type composite (ODIM_H5 classification).

    Published every 5 minutes as one ODIM_H5 file (no tar) on the same
    1200×1100 grid/projection as RS/RV. Each cell is a precipitation *type*
    class index (rain, snow, freezing rain, hail, …) at 2 m above ground,
    rather than an amount.

    precipitation → str | None (the class label), metadata → ProductMetadata.
    """

    PRODUCT_KEY = "hymecng"

    PRODUCT_LABEL = "HymecNG precipitation type"

    RELEASE_INTERVAL = timedelta(minutes=5)

    # DWD publishes each file ~2 min after its nominal time; wait a little longer
    # so the coordinator does not fetch before it appears (checked by
    # scripts/check_release_delay.py).
    RELEASE_DELAY = timedelta(minutes=3)

    RELEASE_OFFSET = timedelta()

    # Precipitation type changes slowly enough that a value one release old
    # is still informative.
    OVERDUE_GRACE = DEFAULT_OVERDUE_GRACE

    def _get_url(self, ts: datetime) -> str:
        """Return the URL for the single ODIM_H5 file."""
        return (
            f"{DWD_COMPOSITE_URL}/hymecng/"
            f"composite_HymecNG_{ts.strftime('%Y%m%d_%H%M')}_000-hd5"
        )

    def _parse(
        self, content: bytes, ts: datetime
    ) -> tuple[str | None, ProductMetadata]:
        """Return the cell's precipitation-type label (blocking)."""
        value, dataset_what, moment_what = read_odim_classification_cell(
            BytesIO(content), *self.index, expected_shape=RS_GRID_SHAPE
        )

        nodata = int(round(float(moment_what.get("nodata", 255))))
        undetect = int(round(float(moment_what.get("undetect", 254))))

        if value == nodata:
            precip_type: str | None = None          # outside radar coverage
        elif value == undetect:
            precip_type = PRECIP_TYPE_BY_INDEX[0]    # scanned, no precipitation
        elif 0 <= value < len(PRECIP_TYPE_BY_INDEX):
            precip_type = PRECIP_TYPE_BY_INDEX[value]
        else:
            _LOGGER.warning("HymecNG: unexpected class index %s", value)
            precip_type = None

        return precip_type, _odim_metadata(dataset_what)


class RadolanProduct(WholeFileProduct, ABC):
    """Abstract coordinator for the RADOLAN analyses (RW, SF), read as HDF5.

    DWD publishes RADOLAN both in its legacy binary format (.bz2, national
    900x900 grid) and as ODIM_H5 on the DE1200 grid RS/RV/HymecNG use. The
    binary format was announced to be switched off, so the HDF5 edition is
    read: one cell via read_odim_composite_cell, located with
    get_rs_grid_index like every other product. It is the same analysis on
    another grid (area means agree to 1 %), so a location may land on a
    slightly different cell than it did on the old grid.

    Concrete subclasses provide PRODUCT_KEY, timing constants, and _get_url().
    precipitation -> float, metadata -> ProductMetadata
    """

    def _parse(
        self, content: bytes, ts: datetime
    ) -> tuple[float | None, ProductMetadata]:
        """Return (scalar_value, ProductMetadata) from the HDF5 bytes (blocking).

        The value is ``None`` where the cell holds no data (radar outage, masked
        cell, outside coverage), as for RS/RV/HymecNG: the reader returns NaN
        for the ODIM ``nodata`` sentinel.
        """
        value, what = read_odim_composite_cell(
            BytesIO(content), *self.index, expected_shape=RS_GRID_SHAPE
        )
        return _nan_to_none(value), _odim_metadata(what)


def _radolan_url(product: str, ts: datetime) -> str:
    """Return the URL of a RADOLAN analysis in its HDF5 edition."""
    return (
        f"{DWD_RADOLAN_URL}/{product}/raa01-{product}_10000-"
        f"{ts.strftime('%y%m%d%H%M')}-dwd---bin.hdf5"
    )


class RadolanRW(RadolanProduct):
    """DWD RADOLAN RW: 1-hour precipitation analysis, one clock hour per release.

    DWD runs RW every 10 minutes (see RadolanRW10); this reads the run ending
    on the hour, so each value is a clock hour (11:00-12:00), the one
    "Precipitation previous hour" shows and the hourly total adds up. Up to
    2026.10.0 it read the HH:50 run, the minute SF is still published at;
    nothing ties RW to it, and the :00 run is gauge-adjusted as strongly and
    published as quickly (~25.5 min after the hour, 48 runs, 2026-10-13).
    """

    PRODUCT_KEY = "rw"

    PRODUCT_LABEL = "RW hourly precipitation"

    RELEASE_INTERVAL = timedelta(hours=1)

    RELEASE_DELAY = timedelta(minutes=28)

    RELEASE_OFFSET = timedelta()

    # An hourly total that is an hour behind is misreported rather than merely
    # old, so give the missing file only the default few minutes.
    OVERDUE_GRACE = DEFAULT_OVERDUE_GRACE

    def _get_url(self, ts: datetime) -> str:
        """Return the HDF5 URL."""
        return _radolan_url("rw", ts)



class RadolanRW10(RadolanRW):
    """DWD RADOLAN RW's 10-minute runs: a sliding hour ending at each :x0.

    Same file family as RW (its hourly runs are among them), so it reuses RW's
    URL and parsing; only the grid is every 10 minutes. Every run minute is
    gauge-adjusted alike, measured against radar-only RS over 285 runs
    (scripts/compare_rw_runs.py). Only built for a dry streak counting RW.
    """

    PRODUCT_KEY = RW_SLIDING_KEY

    PRODUCT_LABEL = "RW hourly precipitation every 10 min"

    RELEASE_INTERVAL = timedelta(minutes=10)

    # Observed ~25.7 min after each run's end, every run minute alike (288
    # runs, 2026-10-13), like the hourly runs it includes.
    RELEASE_DELAY = timedelta(minutes=28)

    RELEASE_OFFSET = timedelta()

    OVERDUE_GRACE = DEFAULT_OVERDUE_GRACE

    @classmethod
    def is_needed(cls, options) -> bool:
        """Whether the dry streak counts RW, the only user of the sliding hour."""
        return dry_streak_coordinator_key(options) == cls.PRODUCT_KEY

class RadolanSF(RadolanProduct):
    """DWD RADOLAN SF: 24-hour precipitation analysis."""

    PRODUCT_KEY = "sf"

    PRODUCT_LABEL = "SF 24-hour precipitation"

    RELEASE_INTERVAL = timedelta(hours=1)

    # The HDF5 edition appears ~29.3 min after the window ends (48 files,
    # 2026-10-10..12), ~2.5 min after the legacy binary one; 31 keeps the
    # same ~2 min margin RW has.
    RELEASE_DELAY = timedelta(minutes=31)

    RELEASE_OFFSET = timedelta(minutes=50)

    # Same reasoning as RW: the window it reports moves with the release.
    OVERDUE_GRACE = DEFAULT_OVERDUE_GRACE

    def _get_url(self, ts: datetime) -> str:
        """Return the HDF5 URL."""
        return _radolan_url("sf", ts)


class RadolanSFLastYesterday(RadolanSF):
    """DWD RADOLAN SF: yesterday's 24-hour total (daily, local time)."""

    PRODUCT_KEY = "sf_2350"

    PRODUCT_LABEL = "SF daily precipitation total"

    RELEASE_INTERVAL = timedelta(hours=24)

    RELEASE_DELAY = timedelta(minutes=31)

    RELEASE_OFFSET = timedelta(hours=23, minutes=50)

    USE_LOCAL_TIME = True

    # Only one release a day, so a retry storm would be pointless — let the
    # fast-poll backoff settle three times slower than the other products, and
    # give the file correspondingly longer to turn up before writing off a
    # total that will not be replaced until tomorrow either way.
    MAX_FAST_POLL_INTERVAL = timedelta(minutes=15)

    OVERDUE_GRACE = timedelta(minutes=30)
