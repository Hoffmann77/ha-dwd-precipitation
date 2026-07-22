"""DWD radar products."""

from __future__ import annotations

import bz2
import logging
import tarfile
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from functools import cached_property, lru_cache
from io import BytesIO

import numpy as np

from .coordinator import BaseProductUpdateCoordinator, ProductMetadata
from .utils import async_get
from .radar import read_radolan_composite, get_radolan_grid, read_odim_composite, get_rs_grid_index
from .radar.nowcast import (
    HOUR1_LEADS,
    HOUR2_LEADS,
    LEAD_STEP,
    LEADS,
    STEPS_PER_HOUR,
    bucket_max_intensity,
    bucket_sum,
    detect_start_end,
)
from .const import (
    CONF_RAIN_THRESHOLD,
    DEFAULT_RAIN_THRESHOLD,
    DWD_RADOLAN_URL,
    DWD_COMPOSITE_URL,
)

_LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _radolan_wgs84_grid() -> np.ndarray:
    """Return the cached 900×900 RADOLAN WGS84 lon/lat grid.

    Shared across all RADOLAN products, which use an identical grid.
    """
    return get_radolan_grid(wgs84=True)


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


class RadvorRS(BaseProductUpdateCoordinator):
    """DWD RS precipitation nowcast (RADVOR, ODIM_H5 format).

    Returns three lead times (0 / 60 / 120 min) from a single tar archive.
    precipitation → list[float | None], metadata → list[ProductMetadata]
    """

    PRODUCT_KEY = "rs"

    RELEASE_INTERVAL = timedelta(minutes=5)

    RELEASE_DELAY = timedelta(minutes=4, seconds=10)

    RELEASE_OFFSET = timedelta()

    @cached_property
    def index(self) -> tuple[int, int]:
        """Return (row, col) in the RS composite grid."""
        return get_rs_grid_index(*self.coords)

    def _get_url(self, ts: datetime) -> str:
        """Return the URL for the tar archive."""
        return (
            f"{DWD_COMPOSITE_URL}/rs/composite_rs_{ts.strftime('%Y%m%d_%H%M')}.tar"
        )

    async def _fetch_and_parse(self, ts: datetime) -> tuple[list, list]:
        """Fetch one tar archive and extract 3 lead-time ACRR values."""
        response = await async_get(self._get_url(ts), self.async_client)

        tar_bytes = BytesIO(response.content)
        prefix = f"composite_rs_{ts.strftime('%Y%m%d_%H%M')}"
        row, col = self.index
        data: list = []
        metadata: list = []

        with tarfile.open(fileobj=tar_bytes, mode="r") as tf:
            for suffix in ("000", "060", "120"):
                member_name = f"{prefix}_{suffix}-hd5"
                try:
                    f = tf.extractfile(member_name)
                except KeyError:
                    f = None
                if f is None:
                    _LOGGER.warning("RS tar member not found: %s", member_name)
                    data.append(None)
                    metadata.append(None)
                    continue

                _data, _what = read_odim_composite(BytesIO(f.read()))
                val = float(_data[row, col])
                data.append(None if np.isnan(val) else val)

                lead = int(suffix)
                data_start = _parse_odim_ts(_what.get("startdate"), _what.get("starttime"))
                data_end = _parse_odim_ts(_what.get("enddate"), _what.get("endtime"))
                source_ts = data_end - timedelta(minutes=lead) if data_end else None
                metadata.append(ProductMetadata(
                    source_product=_what.get("prodname") or _what.get("product"),
                    source_timestamp=source_ts,
                    lead_time_minutes=lead,
                    data_start=data_start,
                    data_end=data_end,
                ))

        return data, metadata


class RadvorRV(BaseProductUpdateCoordinator):
    """DWD RV precipitation nowcast (RADVOR, ODIM_H5 format).

    RV is published every 5 minutes as one tar of 25 ODIM_H5 members
    (leads 0..120 min, 5-min steps). Each member is a 5-minute rainfall
    accumulation (mm) on the same grid/projection as RS.

    From the per-cell 5-minute series this coordinator derives:

    * ``rv_060`` / ``rv_120`` — 1-hour totals over [T, T+60] / [T+60, T+120],
      mirroring the RS "+1 hour" / "+2 hours" entities for comparison.
    * ``max_060`` / ``max_120`` — peak intensity (mm/h) over the same two hours.
    * ``start_in`` / ``start_at`` / ``end_in`` / ``end_at`` — when precipitation
      begins / ends at the location (see radar.nowcast.detect_start_end).
    * ``rain_within_2h`` — whether any precipitation is forecast within the
      2-hour horizon (drives the "rain expected" binary sensor).

    precipitation → dict[str, value], metadata → dict[str, ProductMetadata]
    """

    PRODUCT_KEY = "rv"

    RELEASE_INTERVAL = timedelta(minutes=5)

    RELEASE_DELAY = timedelta(minutes=4, seconds=10)

    RELEASE_OFFSET = timedelta()

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
        """Fetch one tar archive and derive the RV entity payloads."""
        response = await async_get(self._get_url(ts), self.async_client)

        tar_bytes = BytesIO(response.content)
        prefix = f"composite_rv_{ts.strftime('%Y%m%d_%H%M')}"
        row, col = self.index

        # Per-lead 5-minute cell values (mm) and window bounds, aligned to LEADS.
        values: list[float | None] = []
        starts: list[datetime | None] = []
        ends: list[datetime | None] = []
        base_ts: datetime | None = None

        with tarfile.open(fileobj=tar_bytes, mode="r") as tf:
            for lead in LEADS:
                member_name = f"{prefix}_{lead:03d}-hd5"
                try:
                    f = tf.extractfile(member_name)
                except KeyError:
                    f = None
                if f is None:
                    _LOGGER.warning("RV tar member not found: %s", member_name)
                    values.append(None)
                    starts.append(None)
                    ends.append(None)
                    continue

                _data, _what = read_odim_composite(BytesIO(f.read()))
                val = float(_data[row, col])
                values.append(None if np.isnan(val) else val)

                data_start = _parse_odim_ts(_what.get("startdate"), _what.get("starttime"))
                data_end = _parse_odim_ts(_what.get("enddate"), _what.get("endtime"))
                starts.append(data_start)
                ends.append(data_end)
                # Base run time T = end of the analysis window (lead 0).
                if lead == 0 and data_end is not None:
                    base_ts = data_end

        # The user configures the threshold as an intensity (mm/h); the
        # detection works on 5-minute accumulations, so convert back to mm/5min.
        threshold_mmh = self.config_entry.options.get(
            CONF_RAIN_THRESHOLD, DEFAULT_RAIN_THRESHOLD
        )
        threshold = threshold_mmh / STEPS_PER_HOUR
        start_in, end_in = detect_start_end(values, threshold)

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
                    "start": starts[i].isoformat() if starts[i] else None,
                    "end": ends[i].isoformat() if ends[i] else None,
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
                samples=_samples(leads),
            )

        timing_meta = ProductMetadata(source_product="RV", source_timestamp=base_ts)
        # The hourly buckets and their max-intensity siblings share the same
        # constituent 5-minute samples, so reuse one metadata object per hour.
        hour1_meta = _bucket_meta(HOUR1_LEADS, 60)
        hour2_meta = _bucket_meta(HOUR2_LEADS, 120)

        data = {
            "rv_060": bucket_sum(values, HOUR1_LEADS),
            "rv_120": bucket_sum(values, HOUR2_LEADS),
            "max_060": bucket_max_intensity(values, HOUR1_LEADS),
            "max_120": bucket_max_intensity(values, HOUR2_LEADS),
            "start_in": start_in,
            "start_at": _at(start_in),
            "end_in": end_in,
            "end_at": _at(end_in),
            "rain_within_2h": start_in is not None,
        }
        metadata = {
            "rv_060": hour1_meta,
            "rv_120": hour2_meta,
            "max_060": hour1_meta,
            "max_120": hour2_meta,
            "start_in": timing_meta,
            "start_at": timing_meta,
            "end_in": timing_meta,
            "end_at": timing_meta,
            "rain_within_2h": timing_meta,
        }
        return data, metadata


class RadolanProduct(BaseProductUpdateCoordinator, ABC):
    """Abstract coordinator for bz2-compressed RADOLAN binary products.

    Concrete subclasses provide PRODUCT_KEY, timing constants, and get_url().
    precipitation → float, metadata → ProductMetadata

    """

    @cached_property
    def index(self) -> tuple[int, int]:
        """Return the nearest-cell (row, col) in the RADOLAN 900×900 WGS84 grid."""
        lat, lon = self.coords
        grid = _radolan_wgs84_grid()
        dist_sq = (grid[:, :, 1] - lat) ** 2 + (grid[:, :, 0] - lon) ** 2

        return np.unravel_index(np.argmin(dist_sq), dist_sq.shape)

    @abstractmethod
    def _get_url(self, ts: datetime) -> str:
        """Return the bz2 file URL for the given release timestamp."""

    async def _fetch_and_parse(self, ts: datetime) -> tuple[float, ProductMetadata]:
        """Fetch one bz2 RADOLAN file and return (scalar_value, ProductMetadata)."""
        response = await async_get(self._get_url(ts), self.async_client)
        f = bz2.open(BytesIO(response.content))
        data, raw = read_radolan_composite(f)

        dt_end = _utc(raw.get("datetime"))
        interval = raw.get("intervalseconds")
        data_start = dt_end - timedelta(seconds=interval) if (dt_end and interval) else None

        return float(data[self.index]), ProductMetadata(
            source_product=raw.get("producttype"),
            source_timestamp=dt_end,
            data_start=data_start,
            data_end=dt_end,
        )


class RadolanRW(RadolanProduct):
    """DWD RADOLAN RW: 1-hour precipitation analysis."""

    PRODUCT_KEY = "rw"

    RELEASE_INTERVAL = timedelta(hours=1)

    RELEASE_DELAY = timedelta(minutes=28)

    RELEASE_OFFSET = timedelta(minutes=50)

    def _get_url(self, ts: datetime) -> str:
        """Return the bz2 URL."""
        return (
            f"{DWD_RADOLAN_URL}/rw/raa01-rw_10000-"
            f"{ts.strftime('%y%m%d%H%M')}-dwd---bin.bz2"
        )


class RadolanSF(RadolanProduct):
    """DWD RADOLAN SF: 24-hour precipitation analysis."""

    PRODUCT_KEY = "sf"

    RELEASE_INTERVAL = timedelta(hours=1)

    RELEASE_DELAY = timedelta(minutes=28)

    RELEASE_OFFSET = timedelta(minutes=50)

    def _get_url(self, ts: datetime) -> str:
        """Return the bz2 URL."""
        return (
            f"{DWD_RADOLAN_URL}/sf/raa01-sf_10000-"
            f"{ts.strftime('%y%m%d%H%M')}-dwd---bin.bz2"
        )


class RadolanSFLastYesterday(RadolanSF):
    """DWD RADOLAN SF: yesterday's 24-hour total (daily, local time)."""

    PRODUCT_KEY = "sf_2350"

    RELEASE_INTERVAL = timedelta(hours=24)

    RELEASE_DELAY = timedelta(minutes=28)

    RELEASE_OFFSET = timedelta(hours=23, minutes=50)

    USE_LOCAL_TIME = True
