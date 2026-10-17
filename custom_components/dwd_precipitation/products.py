"""DWD radar products."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from functools import cached_property
from typing import Any, ClassVar
from io import BytesIO

import numpy as np

from .coordinator import (
    DEFAULT_OVERDUE_GRACE,
    BaseProductUpdateCoordinator,
    Payload,
    ProductMetadata,
)
from .radar.isotime import iso
from .radar.urls import radvor_prefix
from .options import DwdOptions
from .utils import DownloadCache, FailureLatch, async_get
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
    PAST_STEPS,
    STEPS_PER_HOUR,
    bucket_max_intensity,
    MM_DECIMALS,
    detect_start_end,
    peak_rolling_hour,
    rolling_hour_sums,
)
from .radar.rain_events import RainEventsView
from .rain_events_tracker import RainEventsTracker
from .const import (
    KEY_AMOUNT,
    KEY_LAST_60,
    KEY_NEXT_60,
    KEY_NEXT_60_120,
    KEY_NEXT_120,
    KEY_PRECIPITATION_TYPE,
    PRECIP_TYPE_BY_INDEX,
    RW_SLIDING_KEY,
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


# The three non-overlapping RS hours: past, next and second-next.
_RS_HOURS = {KEY_LAST_60: 0, KEY_NEXT_60: 60, KEY_NEXT_60_120: 120}
RS_HOURLY_LEADS = tuple(_RS_HOURS.values())


# A 206 answer is one window of a RADVOR tar, at most a few members of under
# 1 MB each; anything near this cap is not what was asked for.
RANGE_MAX_BYTES = 8 * 1024 * 1024

# One RADVOR step: the releases are 5 minutes apart, and so are the steps.
_STEP = timedelta(minutes=LEAD_STEP)


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
    ``base`` names the product and release.
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
    start, end = (
        windows[peak_lead // LEAD_STEP]
        if peak and peak_lead is not None
        else (None, None)
    )
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

    # Whether another product of the entry reads the same files, so they go
    # through the entry's download_cache (set up by async_setup_entry).
    SHARES_FILES: ClassVar[bool] = False
    download_cache: DownloadCache | None = None

    @abstractmethod
    def _parse(self, content: bytes, ts: datetime) -> Payload:
        """Return (data, metadata) from the file's bytes (blocking)."""

    async def _fetch_and_parse(self, ts: datetime) -> Payload:
        """Fetch the release's file and decode it off the event loop."""
        url = self._get_url(ts)
        if self.SHARES_FILES and self.download_cache is not None:
            response = await self.download_cache.async_get(
                url, lambda: async_get(url, self.async_client)
            )
        else:
            response = await async_get(url, self.async_client)
        return await self.hass.async_add_executor_job(
            self._parse, response.content, ts
        )


class RadvorProduct(BaseProductUpdateCoordinator, ABC):
    """A RADVOR nowcast (RS, RV): one tar of 25 ODIM_H5 members per release.

    The tar is ``<prefix>.tar`` under the product's key, its members
    ``<prefix>_<lead>-hd5``. RS reads three members by range, RV the whole
    archive.
    """

    def _prefix(self, ts: datetime) -> str:
        """Return release ``ts``'s name stem (``composite_rs_<ts>``)."""
        return radvor_prefix(self.PRODUCT_KEY, ts)

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

    Only the three members the sensors show are read, by range (~20 % of the
    archive). data and metadata are keyed by:

    * ``last_60`` / ``next_60`` / ``next_60_120`` — the non-overlapping hours:
      leads 0 / 60 / 120.
    * ``next_120`` — the whole 120-minute forecast: leads 60 + 120, so it is
      exactly the sum of the two forecast sensors. ``None`` unless both are
      present.

    Every member is the sum of RV's twelve 5-minute steps in its hour, so the
    peak hour and its series come from RV, which decodes those steps anyway.
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

    async def _fetch_and_parse(self, ts: datetime) -> Payload:
        """Read the three hours' members by range, then decode them off the loop."""
        members = await self._async_read_members(ts, RS_HOURLY_LEADS)
        return await self.hass.async_add_executor_job(self._parse_members, members, ts)

    def _parse_members(self, members: dict[str, bytes], ts: datetime) -> Payload:
        """Derive the RS entity payloads from its members' bytes (blocking)."""
        cells = _decode_cells(members, self._prefix(ts), RS_HOURLY_LEADS, self.index, "RS")

        data: dict[str, Any] = {}
        metadata: dict[str, ProductMetadata | None] = {}
        for key, lead in _RS_HOURS.items():
            cell = cells[lead]
            data[key] = cell[0] if cell else None
            metadata[key] = _odim_metadata(cell[1], lead) if cell else None

        data[KEY_NEXT_120], metadata[KEY_NEXT_120] = _next_120(
            data[KEY_NEXT_60],
            data[KEY_NEXT_60_120],
            metadata[KEY_NEXT_60],
            metadata[KEY_NEXT_60_120],
        )
        return data, metadata


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
      metadata carries those 13 rolling hours as ``rolling_1h``; with the
      ``full_rolling_series`` option, the 12 hours that started before T as
      well, from the analyses of the releases adopted in the past hour.
    """

    PRODUCT_KEY = "rv"

    PRODUCT_LABEL = "RV precipitation forecast"

    RELEASE_INTERVAL = timedelta(minutes=5)

    RELEASE_DELAY = timedelta(minutes=4, seconds=10)

    RELEASE_OFFSET = timedelta()

    # A 2-hour forecast does not turn wrong in five minutes, so keep trying
    # across one whole missed release before dropping the entities.
    OVERDUE_GRACE = DEFAULT_OVERDUE_GRACE

    # The entry's rain-events tracker; None when the option is off (or a test
    # builds the coordinator without one).
    _rain_tracker: RainEventsTracker | None = None

    def __init__(self, hass, entry, async_client, lat, lon) -> None:
        """Initialize the coordinator and, if the entry tracks them, rain events."""
        super().__init__(hass, entry, async_client, lat, lon)
        # The analysis (mm, None for no data) of each release adopted in the
        # past hour, by release time; kept for the full rolling-hour series.
        self._analyses: dict[datetime, float | None] = {}
        if self.options.rain_events:
            self._rain_tracker = RainEventsTracker(
                hass,
                entry,
                self.options.rain_event_threshold,
                self._async_fetch_analysis,
                self._publish_rain_view,
            )

    async def _async_on_new_release(
        self, release: datetime, data: dict, metadata: dict
    ) -> None:
        """Keep the analysis for the full series; feed the rain-events tracker."""
        if self.options.full_rolling_series:
            self._analyses[release] = data["amount_000"]
            oldest = release - PAST_STEPS * _STEP
            self._analyses = {t: v for t, v in self._analyses.items() if t >= oldest}
        if self._rain_tracker is not None:
            data["rain_events"] = await self._rain_tracker.async_track(release, metadata)

    def _past_hour(self, release: datetime) -> list[float | None] | None:
        """Return the analyses of the PAST_STEPS releases before ``release``.

        Oldest first, and only if every one was adopted: right after a restart,
        or after a release DWD did not publish in time, there is no past hour
        until those releases are in again (up to an hour). The steps are not
        fetched to fill the gap; the series simply starts at T until then.
        """
        steps = [release - k * _STEP for k in range(PAST_STEPS, 0, -1)]
        if any(step not in self._analyses for step in steps):
            return None
        return [self._analyses[step] for step in steps]

    async def _fetch_and_parse(self, ts: datetime) -> Payload:
        """Fetch the whole archive (all 25 members are used) and decode it off the loop."""
        response = await async_get(self._get_url(ts), self.async_client)
        past = self._past_hour(ts) if self.options.full_rolling_series else None
        return await self.hass.async_add_executor_job(
            self._parse, response.content, ts, past
        )

    def _publish_rain_view(self, view: RainEventsView) -> None:
        """Publish a view the tracker finished after the RV update (a fill)."""
        if self.data is not None:
            self.data.data["rain_events"] = view
            self.async_update_listeners()

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

    def _parse(
        self, content: bytes, ts: datetime, past: list[float | None] | None = None
    ) -> Payload:
        """Derive the RV entity payloads from the tar bytes (blocking).

        ``past`` is the analyses of the releases before ``ts`` (see
        _past_hour); with it the rolling-hour series starts an hour earlier.
        """
        prefix = self._prefix(ts)
        names = member_names(prefix, LEADS)
        cells = _decode_cells(
            members_from_archive(content, names), prefix, LEADS, self.index, "RV"
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
        threshold = self.options.precipitation_threshold / STEPS_PER_HOUR
        end_algorithm = self.options.precipitation_end_algorithm
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

        # Rolling hour ending at T+L = the twelve 5-minute steps ending at
        # T+L-55..T+L. Wholly in this release from L = 60; with the past hour,
        # every lead, the earlier steps being the analyses before T.
        series_leads = LEADS if past is not None else FUTURE_HOUR_LEADS
        windows: list[tuple[datetime | None, datetime | None]] = [
            (None, None)
        ] * len(LEADS)
        for lead in series_leads:
            first = lead // LEAD_STEP - PAST_STEPS  # the window's first step here
            start = starts[first] if first >= 0 else None
            end = ends[lead // LEAD_STEP]
            if start is None and end is not None:
                start = end - timedelta(minutes=60)
            windows[lead // LEAD_STEP] = (start, end)
        peak_1h, peak_meta = _peak_hour_payload(
            rolling_hour_sums(values, past), windows, series_leads, timing_meta
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
        metadata: dict[str, ProductMetadata | None] = {
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

    data[``precipitation_type``] is the class label (None outside coverage).
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

    def _parse(self, content: bytes, ts: datetime) -> Payload:
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

        return (
            {KEY_PRECIPITATION_TYPE: precip_type},
            {KEY_PRECIPITATION_TYPE: _odim_metadata(dataset_what)},
        )


class RadolanProduct(WholeFileProduct, ABC):
    """Abstract coordinator for the RADOLAN analyses (RW, SF), read as HDF5.

    DWD publishes RADOLAN both in its legacy binary format (.bz2, national
    900x900 grid) and as ODIM_H5 on the DE1200 grid RS/RV/HymecNG use. The
    binary format was announced to be switched off, so the HDF5 edition is
    read: one cell via read_odim_composite_cell, located with
    get_rs_grid_index like every other product. It is the same analysis on
    another grid (area means agree to 1 %), so a location may land on a
    slightly different cell than it did on the old grid.

    Concrete subclasses provide PRODUCT_KEY and the timing constants; the
    URL follows from the key (radar/urls.py).
    data[``amount``] is the cell's mm (None for no data).
    """

    # rw/rw_10min and sf/sf_2350 read the same files (small, ~30 KB).
    SHARES_FILES = True

    def _parse(self, content: bytes, ts: datetime) -> Payload:
        """Return the cell's amount and its ProductMetadata (blocking).

        The value is ``None`` where the cell holds no data (radar outage, masked
        cell, outside coverage), as for RS/RV/HymecNG: the reader returns NaN
        for the ODIM ``nodata`` sentinel.
        """
        value, what = read_odim_composite_cell(
            BytesIO(content), *self.index, expected_shape=RS_GRID_SHAPE
        )
        return {KEY_AMOUNT: _nan_to_none(value)}, {KEY_AMOUNT: _odim_metadata(what)}


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
    def is_needed(cls, options: DwdOptions) -> bool:
        """Whether the dry streak counts RW, the only user of the sliding hour."""
        return options.dry_streak_coordinator_key == cls.PRODUCT_KEY

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
