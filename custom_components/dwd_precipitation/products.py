"""DWD radar products."""

from __future__ import annotations

import bz2
import logging
import tarfile
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from functools import cached_property
from io import BytesIO
from typing import ClassVar

import numpy as np

from .coordinator import (
    DEFAULT_OVERDUE_GRACE,
    BaseProductUpdateCoordinator,
    ProductMetadata,
)
from .utils import async_get
from .radar import (
    read_radolan_composite,
    get_radolan_grid_index,
    read_odim_composite_cell,
    read_odim_composite_window,
    read_odim_classification,
    get_rs_grid_index,
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
from .radar.area import area_max, compass, nearest_rain
from .const import (
    AREA_MIN_INTENSITY,
    AREA_NEAR_RADIUS_KM,
    AREA_SCAN_RADIUS_KM,
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


def _utc(dt: datetime | None) -> datetime | None:
    """Ensure a datetime is UTC-aware; returns None for None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _parse_odim_ts(date: str | None, time: str | None) -> datetime | None:
    """Parse ODIM date/time strings (YYYYMMDD / HHMMSS) into a UTC datetime."""
    if not date or not time:
        return None
    try:
        return datetime.strptime(f"{date}{time}", "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# The three non-overlapping RS hours: past, next and second-next.
RS_HOURLY_LEADS = (0, 60, 120)


def _read_tar_cells(
    content: bytes, prefix: str, leads, cell: tuple[int, int], label: str
) -> dict[int, tuple[float | None, dict] | None]:
    """Decode one grid cell from each requested member of a RADVOR tar.

    Returns ``{lead: (value, dataset_what)}``; ``value`` is ``None`` for nodata,
    and a member missing from the archive maps to ``None`` (logged).
    """
    row, col = cell
    out: dict[int, tuple[float | None, dict] | None] = {}
    with tarfile.open(fileobj=BytesIO(content), mode="r") as tf:
        for lead in leads:
            member_name = f"{prefix}_{lead:03d}-hd5"
            try:
                f = tf.extractfile(member_name)
            except KeyError:
                f = None
            if f is None:
                _LOGGER.warning("%s tar member not found: %s", label, member_name)
                out[lead] = None
                continue

            val, what = read_odim_composite_cell(
                BytesIO(f.read()), row, col, expected_shape=RS_GRID_SHAPE
            )
            val = float(val)
            out[lead] = (None if np.isnan(val) else val, what)
    return out


def _read_tar_windows(
    content: bytes, prefix: str, leads, cell: tuple[int, int], radius: int, label: str
) -> dict[int, tuple[np.ndarray, tuple[int, int], dict] | None]:
    """Decode a square of cells around ``cell`` from each member of a RADVOR tar.

    Returns ``{lead: (window, (crow, ccol), dataset_what)}`` with NaN for
    nodata; a member missing from the archive maps to ``None`` (logged).
    """
    row, col = cell
    out: dict[int, tuple[np.ndarray, tuple[int, int], dict] | None] = {}
    with tarfile.open(fileobj=BytesIO(content), mode="r") as tf:
        for lead in leads:
            member_name = f"{prefix}_{lead:03d}-hd5"
            try:
                f = tf.extractfile(member_name)
            except KeyError:
                f = None
            if f is None:
                _LOGGER.warning("%s tar member not found: %s", label, member_name)
                out[lead] = None
                continue

            window, what, center = read_odim_composite_window(
                BytesIO(f.read()), row, col, radius, expected_shape=RS_GRID_SHAPE
            )
            out[lead] = (window, center, what)
    return out


def _odim_window(what: dict) -> tuple[datetime | None, datetime | None]:
    """Return the (start, end) validity window of an ODIM /dataset/what."""
    return (
        _parse_odim_ts(what.get("startdate"), what.get("starttime")),
        _parse_odim_ts(what.get("enddate"), what.get("endtime")),
    )


def _peak_hour_payload(
    sums: list[float | None],
    windows: list[tuple[datetime | None, datetime | None]],
    series_leads: list[int],
    source_product: str | None,
    source_timestamp: datetime | None,
) -> tuple[float | None, ProductMetadata]:
    """Build the "Peak hourly precipitation next 2h" value and metadata.

    ``sums`` (rolling 60-minute totals, mm) and ``windows`` are aligned to
    LEADS; ``series_leads`` picks the points exposed as ``rolling_1h``. RS and
    RV both land here, so the two sources cannot drift apart in shape.
    """
    def _iso(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt is not None else None

    rolling_1h = [
        {
            "lead": lead,
            "start": _iso(windows[lead // LEAD_STEP][0]),
            "end": _iso(windows[lead // LEAD_STEP][1]),
            "value": sums[lead // LEAD_STEP],
        }
        for lead in series_leads
    ]

    peak, peak_lead = peak_rolling_hour(sums, FUTURE_HOUR_LEADS)
    # A dry forecast has no wettest hour, so it gets no window either.
    start, end = windows[peak_lead // LEAD_STEP] if peak else (None, None)
    return peak, ProductMetadata(
        source_product=source_product,
        source_timestamp=source_timestamp,
        lead_time_minutes=peak_lead if peak else None,
        data_start=start,
        data_end=end,
        rolling_1h=rolling_1h,
    )


class RadvorRS(BaseProductUpdateCoordinator):
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

    @cached_property
    def index(self) -> tuple[int, int]:
        """Return (row, col) in the RS composite grid."""
        return get_rs_grid_index(*self.coords)

    @property
    def full_rolling_series(self) -> bool:
        """Whether this entry decodes every member for the rolling-hour series."""
        return self.config_entry.options.get(
            CONF_FULL_ROLLING_SERIES, DEFAULT_FULL_ROLLING_SERIES
        )

    def _get_url(self, ts: datetime) -> str:
        """Return the URL for the tar archive."""
        return (
            f"{DWD_COMPOSITE_URL}/rs/composite_rs_{ts.strftime('%Y%m%d_%H%M')}.tar"
        )

    async def _fetch_and_parse(self, ts: datetime) -> tuple[list, list]:
        """Fetch one tar archive and decode it off the event loop."""
        response = await async_get(self._get_url(ts), self.async_client)
        return await self.hass.async_add_executor_job(self._parse, response.content, ts)

    def _parse(self, content: bytes, ts: datetime) -> tuple[list, list]:
        """Derive the RS entity payloads from the tar bytes (blocking)."""
        full = self.full_rolling_series
        cells = _read_tar_cells(
            content,
            f"composite_rs_{ts.strftime('%Y%m%d_%H%M')}",
            LEADS if full else RS_HOURLY_LEADS,
            self.index,
            "RS",
        )

        per_lead: dict[int, ProductMetadata | None] = {}
        for lead, cell in cells.items():
            if cell is None:
                per_lead[lead] = None
                continue
            data_start, data_end = _odim_window(cell[1])
            per_lead[lead] = ProductMetadata(
                source_product=cell[1].get("prodname") or cell[1].get("product"),
                source_timestamp=(
                    data_end - timedelta(minutes=lead) if data_end else None
                ),
                lead_time_minutes=lead,
                data_start=data_start,
                data_end=data_end,
            )

        data = [cells[lead][0] if cells[lead] else None for lead in RS_HOURLY_LEADS]
        metadata = [per_lead[lead] for lead in RS_HOURLY_LEADS]

        if not full:
            return data + [None], metadata + [None]

        sums = [
            round(cells[lead][0], MM_DECIMALS)
            if cells[lead] and cells[lead][0] is not None
            else None
            for lead in LEADS
        ]
        windows = [
            (m.data_start, m.data_end) if (m := per_lead[lead]) else (None, None)
            for lead in LEADS
        ]
        base = next((m for m in per_lead.values() if m is not None), None)
        peak, peak_meta = _peak_hour_payload(
            sums,
            windows,
            LEADS,
            base.source_product if base else None,
            base.source_timestamp if base else None,
        )
        return data + [peak], metadata + [peak_meta]


class RadvorRV(BaseProductUpdateCoordinator):
    """DWD RV precipitation nowcast (RADVOR, ODIM_H5 format).

    RV is published every 5 minutes as one tar of 25 ODIM_H5 members
    (leads 0..120 min, 5-min steps). Each member is a 5-minute rainfall
    accumulation (mm) on the same grid/projection as RS.

    From the per-cell 5-minute series this coordinator derives:

    * ``max_060`` / ``max_120`` — peak intensity (mm/h) over [T, T+60] /
      [T+60, T+120].
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

    @cached_property
    def index(self) -> tuple[int, int]:
        """Return (row, col) in the RV composite grid (identical to RS)."""
        return get_rs_grid_index(*self.coords)

    def _get_url(self, ts: datetime) -> str:
        """Return the URL for the tar archive."""
        return (
            f"{DWD_COMPOSITE_URL}/rv/composite_rv_{ts.strftime('%Y%m%d_%H%M')}.tar"
        )

    async def _fetch_and_parse(self, ts: datetime) -> tuple[dict, dict]:
        """Fetch one tar archive and decode it off the event loop."""
        response = await async_get(self._get_url(ts), self.async_client)
        return await self.hass.async_add_executor_job(self._parse, response.content, ts)

    def _parse(self, content: bytes, ts: datetime) -> tuple[dict, dict]:
        """Derive the RV entity payloads from the tar bytes (blocking)."""
        # The user configures the threshold as an intensity (mm/h); the
        # detection works on 5-minute accumulations, so convert back to mm/5min.
        threshold_mmh = self.config_entry.options.get(
            CONF_PRECIPITATION_THRESHOLD, DEFAULT_PRECIPITATION_THRESHOLD
        )
        threshold = threshold_mmh / STEPS_PER_HOUR
        area_threshold = max(threshold_mmh, AREA_MIN_INTENSITY) / STEPS_PER_HOUR

        # The cells around the location come out of the same inflate as the
        # location's own cell, so the neighbourhood costs no extra decoding.
        tar_windows = _read_tar_windows(
            content,
            f"composite_rv_{ts.strftime('%Y%m%d_%H%M')}",
            LEADS,
            self.index,
            int(AREA_SCAN_RADIUS_KM),
            "RV",
        )

        # Per-lead 5-minute cell values (mm) and window bounds, aligned to LEADS.
        values: list[float | None] = []
        starts: list[datetime | None] = []
        ends: list[datetime | None] = []
        base_ts: datetime | None = None
        # Same series for the neighbourhood: wettest cell within the near radius
        # (mm) and the closest rain within the scan radius (km, bearing).
        area_values: list[float | None] = []
        nearest: list[tuple[float, float | None] | None] = []

        for lead in LEADS:
            entry = tar_windows[lead]
            if entry is None:
                values.append(None)
                starts.append(None)
                ends.append(None)
                area_values.append(None)
                nearest.append(None)
                continue

            window, (crow, ccol), what = entry
            val = float(window[crow, ccol])
            data_start, data_end = _odim_window(what)
            values.append(None if np.isnan(val) else val)
            area_values.append(area_max(window, crow, ccol, AREA_NEAR_RADIUS_KM))
            nearest.append(
                nearest_rain(window, crow, ccol, area_threshold, AREA_SCAN_RADIUS_KM)
            )
            starts.append(data_start)
            ends.append(data_end)
            # Base run time T = end of the analysis window (lead 0).
            if lead == 0 and data_end is not None:
                base_ts = data_end

        end_algorithm = self.config_entry.options.get(
            CONF_PRECIPITATION_END_ALGORITHM, DEFAULT_PRECIPITATION_END_ALGORITHM
        )
        start_in, end_in = detect_start_end(values, threshold, end_algorithm)
        area_start_in, area_end_in = detect_start_end(
            area_values, area_threshold, end_algorithm
        )

        def _at(minutes: int | None) -> datetime | None:
            if minutes is None or base_ts is None:
                return None
            return base_ts + timedelta(minutes=minutes)

        def _samples(leads: list[int]) -> list[dict]:
            out = []
            for lead in leads:
                i = lead // LEAD_STEP
                value = values[i]
                area_value = area_values[i]
                near = nearest[i]
                out.append({
                    "lead": lead,
                    "start": starts[i].isoformat() if starts[i] else None,
                    "end": ends[i].isoformat() if ends[i] else None,
                    "value": value,
                    # 5-minute accumulation extrapolated to an hourly rate.
                    "intensity": (
                        round(value * STEPS_PER_HOUR, 2)
                        if value is not None
                        else None
                    ),
                    # Wettest cell within AREA_NEAR_RADIUS_KM, as mm/h.
                    "intensity_area": (
                        round(area_value * STEPS_PER_HOUR, 2)
                        if area_value is not None
                        else None
                    ),
                    # Closest rain within AREA_SCAN_RADIUS_KM (None = none).
                    "nearest_km": near[0] if near is not None else None,
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
            rolling_hour_sums(values), windows, FUTURE_HOUR_LEADS, "RV", base_ts
        )

        data = {
            "max_060": bucket_max_intensity(values, HOUR1_LEADS),
            "max_120": bucket_max_intensity(values, HOUR2_LEADS),
            "start_in": start_in,
            "start_at": _at(start_in),
            "end_in": end_in,
            "end_at": _at(end_in),
            "rain_within_2h": start_in is not None,
            "peak_1h": peak_1h,
            "area_start_in": area_start_in,
            "area_start_at": _at(area_start_in),
            "area_end_in": area_end_in,
            "area_end_at": _at(area_end_in),
            # Latest analysis (lead 0): where the closest rain is right now.
            "nearest_km": nearest[0][0] if nearest[0] is not None else None,
            "nearest_bearing": nearest[0][1] if nearest[0] is not None else None,
            "nearest_direction": compass(nearest[0][1]) if nearest[0] is not None else None,
        }
        metadata = {
            "max_060": hour1_meta,
            "max_120": hour2_meta,
            "start_in": timing_meta,
            "start_at": timing_meta,
            "end_in": timing_meta,
            "end_at": timing_meta,
            "rain_within_2h": rain_meta,
            "peak_1h": peak_meta,
            "area_start_in": timing_meta,
            "area_start_at": timing_meta,
            "area_end_in": timing_meta,
            "area_end_at": timing_meta,
            "nearest_km": ProductMetadata(
                source_product="RV",
                source_timestamp=base_ts,
                lead_time_minutes=0,
                data_start=starts[0],
                data_end=ends[0],
            ),
        }
        return data, metadata


class HymecNG(BaseProductUpdateCoordinator):
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

    @cached_property
    def index(self) -> tuple[int, int]:
        """Return (row, col) in the HymecNG grid (identical to RS/RV)."""
        return get_rs_grid_index(*self.coords)

    def _get_url(self, ts: datetime) -> str:
        """Return the URL for the single ODIM_H5 file."""
        return (
            f"{DWD_COMPOSITE_URL}/hymecng/"
            f"composite_HymecNG_{ts.strftime('%Y%m%d_%H%M')}_000-hd5"
        )

    async def _fetch_and_parse(self, ts: datetime) -> tuple[str | None, ProductMetadata]:
        """Fetch one ODIM_H5 file and decode it off the event loop."""
        response = await async_get(self._get_url(ts), self.async_client)
        return await self.hass.async_add_executor_job(self._parse, response.content)

    def _parse(self, content: bytes) -> tuple[str | None, ProductMetadata]:
        """Return the cell's precipitation-type label (blocking)."""
        raw, dataset_what, moment_what = read_odim_classification(
            BytesIO(content), expected_shape=RS_GRID_SHAPE
        )
        row, col = self.index
        value = int(raw[row, col])

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

        data_start = _parse_odim_ts(
            dataset_what.get("startdate"), dataset_what.get("starttime")
        )
        data_end = _parse_odim_ts(
            dataset_what.get("enddate"), dataset_what.get("endtime")
        )

        return precip_type, ProductMetadata(
            source_product=dataset_what.get("prodname") or dataset_what.get("product"),
            source_timestamp=data_end,
            data_start=data_start,
            data_end=data_end,
        )


class RadolanProduct(BaseProductUpdateCoordinator, ABC):
    """Abstract coordinator for bz2-compressed RADOLAN binary products.

    Concrete subclasses provide PRODUCT_KEY, timing constants, and get_url().
    precipitation → float, metadata → ProductMetadata

    """

    # National RADOLAN composite grid (rows, cols); validated on every parse.
    EXPECTED_SHAPE: ClassVar[tuple[int, int]] = (900, 900)

    @cached_property
    def index(self) -> tuple[int, int]:
        """Return the (row, col) of the RADOLAN 900×900 cell holding the location."""
        return get_radolan_grid_index(*self.coords, *self.EXPECTED_SHAPE)

    @abstractmethod
    def _get_url(self, ts: datetime) -> str:
        """Return the bz2 file URL for the given release timestamp."""

    async def _fetch_and_parse(self, ts: datetime) -> tuple[float | None, ProductMetadata]:
        """Fetch one bz2 RADOLAN file and decode it off the event loop."""
        response = await async_get(self._get_url(ts), self.async_client)
        return await self.hass.async_add_executor_job(self._parse, response.content)

    def _parse(self, content: bytes) -> tuple[float | None, ProductMetadata]:
        """Return (scalar_value, ProductMetadata) from the bz2 bytes (blocking).

        The value is ``None`` where the cell holds no data (radar outage, masked
        cell, outside coverage), as for RS/RV/HymecNG. The reader marks those
        cells with the ``nodataflag`` sentinel (-9999), not NaN, and passing it
        on showed -9999 mm and counted as a dry hour for the dry streak.
        """
        f = bz2.open(BytesIO(content))
        data, raw = read_radolan_composite(f)

        if data.shape != self.EXPECTED_SHAPE:
            raise ValueError(
                f"Unexpected RADOLAN grid shape {data.shape}, "
                f"expected {self.EXPECTED_SHAPE}"
            )

        dt_end = _utc(raw.get("datetime"))
        interval = raw.get("intervalseconds")
        data_start = dt_end - timedelta(seconds=interval) if (dt_end and interval) else None

        value = float(data[self.index])
        if value == raw.get("nodataflag", -9999) or value != value:  # sentinel or NaN
            value = None

        return value, ProductMetadata(
            source_product=raw.get("producttype"),
            source_timestamp=dt_end,
            data_start=data_start,
            data_end=dt_end,
        )


class RadolanRW(RadolanProduct):
    """DWD RADOLAN RW: 1-hour precipitation analysis."""

    PRODUCT_KEY = "rw"

    PRODUCT_LABEL = "RW hourly precipitation"

    RELEASE_INTERVAL = timedelta(hours=1)

    RELEASE_DELAY = timedelta(minutes=28)

    RELEASE_OFFSET = timedelta(minutes=50)

    # An hourly total that is an hour behind is misreported rather than merely
    # old, so give the missing file only the default few minutes.
    OVERDUE_GRACE = DEFAULT_OVERDUE_GRACE

    def _get_url(self, ts: datetime) -> str:
        """Return the bz2 URL."""
        return (
            f"{DWD_RADOLAN_URL}/rw/raa01-rw_10000-"
            f"{ts.strftime('%y%m%d%H%M')}-dwd---bin.bz2"
        )


class RadolanSF(RadolanProduct):
    """DWD RADOLAN SF: 24-hour precipitation analysis."""

    PRODUCT_KEY = "sf"

    PRODUCT_LABEL = "SF 24-hour precipitation"

    RELEASE_INTERVAL = timedelta(hours=1)

    RELEASE_DELAY = timedelta(minutes=28)

    RELEASE_OFFSET = timedelta(minutes=50)

    # Same reasoning as RW: the window it reports moves with the release.
    OVERDUE_GRACE = DEFAULT_OVERDUE_GRACE

    def _get_url(self, ts: datetime) -> str:
        """Return the bz2 URL."""
        return (
            f"{DWD_RADOLAN_URL}/sf/raa01-sf_10000-"
            f"{ts.strftime('%y%m%d%H%M')}-dwd---bin.bz2"
        )


class RadolanSFLastYesterday(RadolanSF):
    """DWD RADOLAN SF: yesterday's 24-hour total (daily, local time)."""

    PRODUCT_KEY = "sf_2350"

    PRODUCT_LABEL = "SF daily precipitation total"

    RELEASE_INTERVAL = timedelta(hours=24)

    RELEASE_DELAY = timedelta(minutes=28)

    RELEASE_OFFSET = timedelta(hours=23, minutes=50)

    USE_LOCAL_TIME = True

    # Only one release a day, so a retry storm would be pointless — let the
    # fast-poll backoff settle three times slower than the other products, and
    # give the file correspondingly longer to turn up before writing off a
    # total that will not be replaced until tomorrow either way.
    MAX_FAST_POLL_INTERVAL = timedelta(minutes=15)

    OVERDUE_GRACE = timedelta(minutes=30)
