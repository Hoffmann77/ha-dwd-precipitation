"""DWD radar products."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
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
from .radar import read_odim_classification_at, read_odim_composite_at
from .radar.nowcast import (
    FUTURE_HOUR_LEADS,
    HOUR1_LEADS,
    HOUR2_LEADS,
    LEAD_STEP,
    LEADS,
    PAST_STEPS,
    STEPS_PER_HOUR,
    bucket_max_intensity,
    round_mm,
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
    """Parse ODIM date/time strings (YYYYMMDD / HHMMSS) into a UTC datetime.

    ODIM_H5 states times as two attributes, e.g. ``startdate`` "20261017" and
    ``starttime`` "120000"; they are always UTC. None when either is missing or
    malformed, so one bad attribute costs only that timestamp, not the release.

    """
    if not date or not time:
        return None
    try:
        return datetime.strptime(f"{date}{time}", "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _nan_to_none(value: float) -> float | None:
    """Return a cell reading as a float, None for nodata (NaN).

    The readers mark "no data for this cell" (outside coverage, a radar outage)
    as NaN; None makes the entity show it as unknown instead of a number.

    """
    value = float(value)
    return None if np.isnan(value) else value


# The three non-overlapping RS hours: past, next and second-next.
_RS_HOURS = {KEY_LAST_60: 0, KEY_NEXT_60: 60, KEY_NEXT_60_120: 120}
RS_HOURLY_LEADS = tuple(_RS_HOURS.values())


# A 206 answer is one window of a RADVOR tar, at most a few members of under
# 1 MB each; anything near this cap is not what was asked for.
RANGE_MAX_BYTES = 8 * 1024 * 1024

# One RADVOR step: the releases are 5 minutes apart, and so are the steps.
_STEP = timedelta(minutes=LEAD_STEP)


def _decode_cells(
    members: dict[str, bytes],
    prefix: str,
    leads,
    location: tuple[float, float],
    label: str,
) -> dict[int, tuple[float | None, dict] | None]:
    """Return the cell holding ``location`` in each requested RADVOR member.

    ``members`` maps member names to their bytes, ``prefix`` is the release's
    name stem and ``leads`` the forecast minutes wanted; ``label`` ("RS", "RV")
    only names the product in the log. Maps each lead to (value, dataset_what),
    with value None for no data. A member missing from the archive maps to None
    and is logged; the other leads are still decoded. Blocking.

    """
    out: dict[int, tuple[float | None, dict] | None] = {}
    for lead, name in zip(leads, member_names(prefix, leads)):
        if (member := members.get(name)) is None:
            _LOGGER.warning("%s tar member not found: %s", label, name)
            out[lead] = None
            continue

        val, what = read_odim_composite_at(BytesIO(member), *location)
        out[lead] = (_nan_to_none(val), what)
    return out



def _odim_window(what: dict) -> tuple[datetime | None, datetime | None]:
    """Return the (start, end) validity window of an ODIM /dataset/what.

    The period the grid's amount covers, in UTC: for RS's lead 60, say, the
    hour from the release time to 60 minutes after it. Either end is None when
    the file does not say.

    """
    return (
        _parse_odim_ts(what.get("startdate"), what.get("starttime")),
        _parse_odim_ts(what.get("enddate"), what.get("endtime")),
    )


def _odim_metadata(what: dict, lead: int | None = None) -> ProductMetadata:
    """Return the metadata of one ODIM grid from its /dataset/what.

    The product name, the release (source timestamp), the lead, the validity
    window and the radars the composite was built from. The window ends at the
    release time plus ``lead``, so the release is the window end minus the
    lead; without a lead (RADOLAN, HymecNG) it is the window end.

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
        radars=what.get("nodes"),
    )


def _peak_hour_payload(
    sums: list[float | None],
    windows: list[tuple[datetime | None, datetime | None]],
    series_leads: list[int],
    base: ProductMetadata | None,
) -> tuple[float | None, ProductMetadata]:
    """Return the "Peak hourly precipitation next 120 min" value and metadata.

    ``sums`` and ``windows`` hold the rolling hours (totals in mm, and their
    windows) by lead; ``series_leads`` picks the points shown as
    ``rolling_1h``, ``base`` names the product and release. The value is the
    wettest future hour, with its window as data_start/data_end and its end
    lead as the lead time. A dry forecast has no peak window.

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
        radars=base.radars if base else None,
    )


def _next_120(
    hour1: float | None,
    hour2: float | None,
    meta1: ProductMetadata | None,
    meta2: ProductMetadata | None,
) -> tuple[float | None, ProductMetadata | None]:
    """Return RS's 120-minute forecast total: its two forecast hours added.

    ``hour1``/``hour2`` are the amounts of the next hour and the one after,
    ``meta1``/``meta2`` their metadata; the total's window runs from the
    first's start to the second's end. Half a forecast is not a 120-minute
    total, so a missing hour makes the whole value None rather than counting as
    dry.

    """
    if hour1 is None or hour2 is None or meta1 is None or meta2 is None:
        return None, None

    return round_mm(hour1 + hour2), ProductMetadata(
        source_product=meta1.source_product,
        source_timestamp=meta1.source_timestamp,
        lead_time_minutes=120,
        data_start=meta1.data_start,
        data_end=meta2.data_end,
        radars=meta1.radars,
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
        """Return (data, metadata) from the file's bytes.

        Each product implements it: read the cell holding the location from
        ``content`` (the downloaded file of release ``ts``) and build the
        payload. Blocking: runs in the executor, never on the event loop.

        """

    async def _fetch_and_parse(self, ts: datetime) -> Payload:
        """Download the release's file and decode it in the executor.

        A product whose files another product reads too (SHARES_FILES, the
        RADOLAN products) goes through the entry's DownloadCache, so each file
        is downloaded once. A failed download raises, and the coordinator
        retries.

        """
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
        """Return release ``ts``'s name stem (``composite_rs_<ts>``).

        The tar is named after it, and so is each member, with the lead
        appended (see radar/urls.py).

        """
        return radvor_prefix(self.PRODUCT_KEY, ts)

    @cached_property
    def _range_latch(self) -> FailureLatch:
        """Return the latch tracking whether range reads are falling back.

        So the warning about whole-archive downloads is logged once per run of
        them, and the recovery once. One per coordinator, created on first use.

        """
        return FailureLatch()

    async def _async_read_members(self, ts: datetime, leads) -> dict[str, bytes]:
        """Fetch only the requested members of release ``ts``, by range reads.

        ``leads`` are the forecast minutes wanted, e.g. (0, 60, 120). Returns
        the members' bytes by name. Falls back to the whole archive on anything
        unexpected (see radar/tar_range.py), unpacked in the executor; a
        missing release still raises, like any fetch. A fallback is logged once
        per run of them: values are unaffected, but each update then downloads
        several times the data.

        """
        url, prefix = self._get_url(ts), self._prefix(ts)

        async def fetch(target: str, headers):
            """Download ``target`` with the given headers (a Range request).

            The fetch the range reader uses; a 206 answer may not exceed
            RANGE_MAX_BYTES.

            """
            return await async_get(
                target, self.async_client, headers=headers,
                partial_max_bytes=RANGE_MAX_BYTES,
            )

        async def extract(content: bytes, wanted) -> dict[str, bytes]:
            """Take the wanted members out of a whole archive, in the executor.

            Used when range reads fall back to the whole file, so walking a
            multi-MB tar does not block the event loop.

            """
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

    Every member is the sum of RV's twelve 5-minute steps in its hour (exactly
    in almost every cell, ADR 0009), so the peak hour and its series come from
    RV, which decodes those steps anyway.

    """

    PRODUCT_KEY = "rs"

    PRODUCT_LABEL = "RS precipitation nowcast"

    COVERAGE_KEYS = (KEY_LAST_60, KEY_NEXT_60, KEY_NEXT_60_120)

    RELEASE_INTERVAL = timedelta(minutes=5)

    RELEASE_DELAY = timedelta(minutes=4, seconds=10)

    RELEASE_OFFSET = timedelta()

    # 6 min outlasts one whole 5-min cycle: each grid is a 60-minute
    # accumulation, so a value one release old is still a fair answer to
    # "how much fell in the last hour".
    OVERDUE_GRACE = DEFAULT_OVERDUE_GRACE

    async def _fetch_and_parse(self, ts: datetime) -> Payload:
        """Read the three hours' members by range, then decode them.

        Leads 0, 60 and 120 (the past hour, the next and the one after) are all
        the sensors show, about a fifth of the archive. Decoding runs in the
        executor.

        """
        members = await self._async_read_members(ts, RS_HOURLY_LEADS)
        return await self.hass.async_add_executor_job(self._parse_members, members, ts)

    def _parse_members(self, members: dict[str, bytes], ts: datetime) -> Payload:
        """Return the RS payload (the three hours and their sum) from the members.

        Keys ``last_60``, ``next_60`` and ``next_60_120`` hold the leads 0, 60
        and 120 (mm, rounded to 0.001), ``next_120`` the two forecast hours
        added. A missing member gives None for its hour. Blocking: runs in the
        executor.

        """
        cells = _decode_cells(members, self._prefix(ts), RS_HOURLY_LEADS, self.coords, "RS")

        data: dict[str, Any] = {}
        metadata: dict[str, ProductMetadata | None] = {}
        for key, lead in _RS_HOURS.items():
            cell = cells[lead]
            data[key] = round_mm(cell[0]) if cell else None
            metadata[key] = _odim_metadata(cell[1], lead) if cell else None

        data[KEY_NEXT_120], metadata[KEY_NEXT_120] = _next_120(
            data[KEY_NEXT_60],
            data[KEY_NEXT_60_120],
            metadata[KEY_NEXT_60],
            metadata[KEY_NEXT_60_120],
        )
        return data, metadata


@dataclass(frozen=True)
class _RvSeries:
    """One RV release at the location: each lead's 5-minute amount and window."""

    values: list[float | None]  # mm, aligned to LEADS; None for no data
    starts: list[datetime | None]
    ends: list[datetime | None]
    base: datetime | None  # T, the end of the analysis window (lead 0)
    radars: tuple[str, ...] | None = None  # the analysis's radar nodes

    @classmethod
    def from_cells(cls, cells: dict[int, tuple[float | None, dict] | None]) -> _RvSeries:
        """Build the series from _decode_cells' output.

        Amounts are rounded to the ODIM resolution (0.001 mm); a lead without
        data keeps None and no window. The release time T is taken from the
        analysis's window end, the radars from its nodes.

        """
        values: list[float | None] = []
        starts: list[datetime | None] = []
        ends: list[datetime | None] = []
        for lead in LEADS:
            cell = cells[lead]
            start, end = _odim_window(cell[1]) if cell else (None, None)
            values.append(round_mm(cell[0]) if cell else None)
            starts.append(start)
            ends.append(end)
        analysis = cells[0]
        radars = analysis[1].get("nodes") if analysis else None
        return cls(values, starts, ends, base=ends[0], radars=radars)

    def at(self, minutes: int | None) -> datetime | None:
        """Return T + ``minutes``; None without either.

        Turns "starts in 15 minutes" into the time it starts, counted from the
        release time.

        """
        if minutes is None or self.base is None:
            return None
        return self.base + timedelta(minutes=minutes)

    def metadata(
        self,
        leads: list[int] | None = None,
        lead_minutes: int | None = None,
        samples: list[dict] | None = None,
    ) -> ProductMetadata:
        """Return the metadata of a value over ``leads``.

        Its window spans from the first lead's start to the last lead's end,
        and ``lead_minutes`` is its lead time; ``samples`` attaches the
        5-minute series. Without leads it names the release only.

        """
        return ProductMetadata(
            source_product="RV",
            source_timestamp=self.base,
            lead_time_minutes=lead_minutes,
            data_start=self.starts[leads[0] // LEAD_STEP] if leads else None,
            data_end=self.ends[leads[-1] // LEAD_STEP] if leads else None,
            samples=samples,
            radars=self.radars,
        )

    def samples(self) -> list[dict]:
        """Return every step: its window, amount (mm) and hourly rate (mm/h).

        One dict per lead (``lead``, ``start``, ``end``, ``value``,
        ``intensity``), the 25-point series the "Precipitation expected" binary
        sensor exposes as ``forecast_5min``.

        """
        return [
            {
                "lead": lead,
                "start": iso(start),
                "end": iso(end),
                "value": value,
                "intensity": round(value * STEPS_PER_HOUR, 2) if value is not None else None,
            }
            for lead, value, start, end in zip(LEADS, self.values, self.starts, self.ends)
        ]

    def hour_windows(self, leads: list[int]) -> list[tuple[datetime | None, datetime | None]]:
        """Return the rolling hour ending at each of ``leads``, aligned to LEADS.

        The hour ending at T+L is the twelve steps ending at T+L-55..T+L; its
        start is the first step's start. For a lead under 60 the first of them
        is in an earlier release, so the start is the end minus an hour. Leads
        not asked for stay (None, None).

        """
        windows: list[tuple[datetime | None, datetime | None]] = [(None, None)] * len(LEADS)
        for lead in leads:
            first = lead // LEAD_STEP - PAST_STEPS  # the hour's first step here
            start = self.starts[first] if first >= 0 else None
            end = self.ends[lead // LEAD_STEP]
            if start is None and end is not None:
                start = end - timedelta(minutes=60)
            windows[lead // LEAD_STEP] = (start, end)
        return windows


# What each part of RV's payload returns: (value, metadata) by sub-key.
type _Parts = dict[str, tuple[Any, ProductMetadata | None]]


def _rv_intensities(series: _RvSeries) -> _Parts:
    """Return the current intensity and the peak intensities ahead.

    The analysis (the 5 minutes ending at T, the only measured step) as an
    hourly rate and as its raw amount, and the peak rates over the first hour,
    the second and both. Each comes with metadata covering the leads it was
    taken from.

    """
    # The analysis (lead 0) is the 5 minutes ending at T: the only measured step
    # in the release, reported as an hourly rate like the peaks. Both are at the
    # ODIM resolution; x12 keeps it exact.
    values = series.values
    now = values[0]
    now_meta = series.metadata([0], 0)
    hour1, hour2, both = HOUR1_LEADS, HOUR2_LEADS, HOUR1_LEADS + HOUR2_LEADS
    return {
        "intensity_000": (round_mm(now * STEPS_PER_HOUR) if now is not None else None, now_meta),
        "amount_000": (now, now_meta),
        "max_060": (bucket_max_intensity(values, hour1), series.metadata(hour1, 60)),
        "max_120": (bucket_max_intensity(values, hour2), series.metadata(hour2, 120)),
        "max_000_120": (bucket_max_intensity(values, both), series.metadata(both, 120)),
    }


def _rv_timing(series: _RvSeries, threshold_mmh: float, end_algorithm: str) -> _Parts:
    """Return when precipitation starts and ends, and whether any is expected.

    ``threshold_mmh`` is the configured wet limit as an intensity, compared
    with the 5-minute amounts (divided by 12). Start and end come as minutes
    from T and as times; ``end_algorithm`` picks how the end is found. The
    flag's metadata carries the whole forecast series.

    """
    # The threshold is configured as an intensity (mm/h); the detection works
    # on 5-minute amounts.
    start_in, end_in = detect_start_end(
        series.values, threshold_mmh / STEPS_PER_HOUR, end_algorithm
    )
    timing = series.metadata()
    return {
        "start_in": (start_in, timing),
        "start_at": (series.at(start_in), timing),
        "end_in": (end_in, timing),
        "end_at": (series.at(end_in), timing),
        # The rain-expected flag owns the raw forecast curve: the full 25-point
        # 5-minute series, which the binary sensor surfaces.
        "rain_within_2h": (start_in is not None, series.metadata(LEADS, samples=series.samples())),
    }


def _rv_peak_hour(series: _RvSeries, past: list[float | None] | None) -> _Parts:
    """Return the wettest rolling hour ahead, with the series it is picked from.

    The rolling hours are RV's 5-minute steps summed by the hour. The series
    has the 13 hours wholly in the forecast, or all 25 when the past hour's
    analyses are known (``past``).

    """
    # Wholly in this release from lead 60; with the past hour, every lead.
    leads = LEADS if past is not None else FUTURE_HOUR_LEADS
    peak, meta = _peak_hour_payload(
        rolling_hour_sums(series.values, past), series.hour_windows(leads), leads, series.metadata()
    )
    return {"peak_1h": (peak, meta)}


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
      twelve 5-minute steps (matching the RS member for that window). Its
      metadata carries those 13 rolling hours as ``rolling_1h``; with the
      ``full_rolling_series`` option, the 12 hours that started before T as
      well, from the analyses of the releases adopted in the past hour.

    """

    PRODUCT_KEY = "rv"

    PRODUCT_LABEL = "RV precipitation forecast"

    # The analysis: the forecast leads rarely lose a cell, since the nowcast
    # moves data in from the neighbouring area.
    COVERAGE_KEYS = ("amount_000",)

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
        """Set up the coordinator and, if the entry tracks them, rain events.

        Also starts the buffer of recent analyses that the full rolling-hour
        series needs (empty after every start or reload). The rain-events
        tracker is built only with the rain_events option on.

        """
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

    @property
    def rain_tracker(self) -> RainEventsTracker | None:
        """Return the entry's rain-events tracker; None with the option off."""
        return self._rain_tracker

    async def _async_on_new_release(
        self, release: datetime, data: dict, metadata: dict
    ) -> None:
        """Keep the analysis for the full series; feed the rain-events tracker.

        Called once per adopted release, before the data is published. With
        full_rolling_series on, the release's analysis is kept and analyses
        older than an hour are dropped. With rain events on, the tracker's view
        is added to the payload for the Rain events sensor.

        """
        if self.options.full_rolling_series:
            self._analyses[release] = data["amount_000"]
            oldest = release - PAST_STEPS * _STEP
            self._analyses = {t: v for t, v in self._analyses.items() if t >= oldest}
        if self._rain_tracker is not None:
            data["rain_events"] = await self._rain_tracker.async_track(release, metadata)

    def _past_hour(self, release: datetime) -> list[float | None] | None:
        """Return the analyses of the PAST_STEPS releases before ``release``.

        The 11 measured 5-minute steps before T, oldest first, that the rolling
        hours ending before T+60 need. Only if every one was adopted: after a
        restart or a release DWD did not publish in time, this is None and the
        series starts at T for up to an hour. Missing steps are not fetched.

        """
        steps = [release - k * _STEP for k in range(PAST_STEPS, 0, -1)]
        if any(step not in self._analyses for step in steps):
            return None
        return [self._analyses[step] for step in steps]

    async def _fetch_and_parse(self, ts: datetime) -> Payload:
        """Download the whole archive and decode it in the executor.

        Every one of the 25 members is used, so range reads would save nothing.
        With full_rolling_series on, the past hour's analyses are handed to
        _parse as well.

        """
        response = await async_get(self._get_url(ts), self.async_client)
        past = self._past_hour(ts) if self.options.full_rolling_series else None
        return await self.hass.async_add_executor_job(
            self._parse, response.content, ts, past
        )

    def _publish_rain_view(self, view: RainEventsView) -> None:
        """Publish a rain-events view the tracker finished later.

        When a background fill completes after the RV update, its view replaces
        the one shown and the entities are told to update. Nothing happens
        before RV has data.

        """
        if self.data is not None:
            self.data.data["rain_events"] = view
            self.async_update_listeners()

    async def _async_fetch_analysis(self, step_end: datetime) -> float | None:
        """Return the analysis (lead 0) of release ``step_end``; None for nodata.

        For the rain-events tracker to fill measured steps it missed (during a
        restart, say). Reads that one member by range, a few percent of the
        archive.

        """
        members = await self._async_read_members(step_end, [0])
        return await self.hass.async_add_executor_job(
            self._parse_analysis, members, self._prefix(step_end), step_end
        )

    def _parse_analysis(
        self, members: dict[str, bytes], prefix: str, step_end: datetime
    ) -> float | None:
        """Decode the analysis member of a missed release (blocking).

        Returns its amount for the location (mm, rounded; None for no data).
        Raises if the member is missing or covers another window than the step
        asked for, so a wrong file is never recorded as that step.

        """
        cell = _decode_cells(members, prefix, [0], self.coords, "RV")[0]
        if cell is None:
            raise ValueError(f"{prefix} has no analysis member")
        _, end = _odim_window(cell[1])
        if end != step_end:
            raise ValueError(f"{prefix} analysis ends at {end}, not {step_end}")
        return round_mm(cell[0])

    def _parse(
        self, content: bytes, ts: datetime, past: list[float | None] | None = None
    ) -> Payload:
        """Return the RV payload from the tar's bytes (blocking).

        Decodes all 25 members at the location into one series, then derives
        every RV value from it: the intensities, the start/end timing and the
        peak hour. ``past`` holds the analyses of the releases before ``ts``
        (see _past_hour); with it the rolling-hour series starts an hour
        earlier.

        """
        prefix = self._prefix(ts)
        members = members_from_archive(content, member_names(prefix, LEADS))
        series = _RvSeries.from_cells(
            _decode_cells(members, prefix, LEADS, self.coords, "RV")
        )
        options = self.options
        parts = {
            **_rv_intensities(series),
            **_rv_timing(
                series,
                options.precipitation_threshold,
                options.precipitation_end_algorithm,
            ),
            **_rv_peak_hour(series, past),
        }
        return (
            {key: value for key, (value, _) in parts.items()},
            {key: meta for key, (_, meta) in parts.items()},
        )


class HymecNG(WholeFileProduct):
    """DWD HymecNG precipitation-type composite (ODIM_H5 classification).

    Published every 5 minutes as one ODIM_H5 file (no tar) on the same
    1200×1100 grid/projection as RS/RV. Each cell is a precipitation *type*
    class index (rain, snow, freezing rain, hail, …) at 2 m above ground,
    rather than an amount.

    data[``precipitation_type``] is the class label (None outside coverage).
    With rain events on, every adopted release's label also goes to the
    entry's rain-events tracker, as the type of the measured step ending then.

    """

    PRODUCT_KEY = "hymecng"

    PRODUCT_LABEL = "HymecNG precipitation type"

    COVERAGE_KEYS = (KEY_PRECIPITATION_TYPE,)

    RELEASE_INTERVAL = timedelta(minutes=5)

    # DWD publishes each file ~2 min after its nominal time; wait a little longer
    # so the coordinator does not fetch before it appears (checked by
    # scripts/check_release_delay.py).
    RELEASE_DELAY = timedelta(minutes=3)

    RELEASE_OFFSET = timedelta()

    # Precipitation type changes slowly enough that a value one release old
    # is still informative.
    OVERDUE_GRACE = DEFAULT_OVERDUE_GRACE

    # The entry's rain-events tracker (RV's), set by attach_rain_tracker; None
    # when the rain_events option is off.
    _rain_tracker: RainEventsTracker | None = None

    def attach_rain_tracker(self, tracker: RainEventsTracker) -> None:
        """Feed ``tracker`` the type of every release, and lend it a fetch.

        Called at setup, before the first refresh, when the entry tracks rain
        events. The tracker can then fill the type of a wet step this
        coordinator missed.

        """
        self._rain_tracker = tracker
        tracker.attach_types(self._async_fetch_type)

    async def _async_on_new_release(
        self, release: datetime, data: dict, metadata: dict
    ) -> None:
        """Hand the release's type to the rain-events tracker, if there is one.

        The type is that of the moment ``release``, so it belongs to the
        measured step ending then. The tracker never raises.

        """
        if self._rain_tracker is not None:
            await self._rain_tracker.async_record_type(
                release, data[KEY_PRECIPITATION_TYPE]
            )

    async def _async_fetch_type(self, release: datetime) -> str | None:
        """Return the type label of a past ``release`` (None without one).

        For the rain-events tracker to fill a step's type it missed. Raises if
        the file is for another moment, so a wrong file is never recorded as
        that step's type.

        """
        fetched = await self.async_fetch_release(release)
        meta = fetched.metadata[KEY_PRECIPITATION_TYPE]
        moment = meta.source_timestamp if meta is not None else None
        if moment != release:
            raise ValueError(f"HymecNG file of {release} is for {moment}")
        return fetched.data[KEY_PRECIPITATION_TYPE]

    def _parse(self, content: bytes, ts: datetime) -> Payload:
        """Return the cell's precipitation-type label (blocking).

        The label is one of PRECIP_TYPE_BY_INDEX ("rain", "snow", ...).
        "nodata" (outside coverage) gives None, "undetect" (scanned, nothing
        there) gives no_precipitation; an unknown class index is logged and
        gives None.

        """
        value, dataset_what, moment_what = read_odim_classification_at(
            BytesIO(content), *self.coords
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
    read: the cell holding the location on the grid the file describes, like
    every other product. It is the same analysis on another grid (area means
    agree to 1 %), so a location may land on a slightly different cell than it
    did on the old grid.

    Concrete subclasses provide PRODUCT_KEY and the timing constants; the
    URL follows from the key (radar/urls.py).
    data[``amount``] is the cell's mm (None for no data).

    """

    # rw/rw_10min and sf/sf_2350 read the same files (small, ~30 KB).
    SHARES_FILES = True

    COVERAGE_KEYS = (KEY_AMOUNT,)

    def _parse(self, content: bytes, ts: datetime) -> Payload:
        """Return the cell's amount (mm) and its metadata (blocking).

        The amount is rounded to 0.001 mm; the metadata carries the analysis
        window (the hour for RW, the 24 hours for SF). The value is None where
        the cell holds no data (radar outage, masked cell, outside coverage),
        as for every product.

        """
        value, what = read_odim_composite_at(BytesIO(content), *self.coords)
        return {KEY_AMOUNT: round_mm(_nan_to_none(value))}, {KEY_AMOUNT: _odim_metadata(what)}


class RadolanRW(RadolanProduct):
    """DWD RADOLAN RW: 1-hour precipitation analysis, one clock hour per release.

    DWD runs RW every 10 minutes (see RadolanRW10); this reads the run ending
    on the hour, so each value is a clock hour (11:00-12:00), the one
    "Precipitation previous hour" shows and the hourly total adds up. Up to
    2026.10.1 it read the HH:50 run, the minute SF is still published at;
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
        """Return whether the dry streak counts RW, the only user of this product.

        The 10-minute runs exist only so the dry streak can reset sooner;
        otherwise the coordinator is not built, and its requests are saved.

        """
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
