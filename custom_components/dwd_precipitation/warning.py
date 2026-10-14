"""Pure rain-warning logic: dry / soon / rain from the RV 5-minute series.

Turns the ``forecast_5min`` samples of the RV product into one warning state
plus the details a notification needs (start, length, intensity level, type).
It carries no Home Assistant dependency so it can be unit-tested in isolation;
the "Rain warning" sensor in sensor.py feeds it and re-runs it every minute,
because every value here is relative to *now*.

Noise handling: a forecast "event" (a run of wet 5-minute windows) only counts
when it lasts at least ``min_duration`` minutes or reaches ``min_peak`` mm/h.
A single faint 5-minute speck in the forecast is radar noise far more often
than rain, and used to cause false alarms.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

STATE_DRY = "dry"
STATE_SOON = "soon"
STATE_RAIN = "rain"
WARNING_STATES = [STATE_DRY, STATE_SOON, STATE_RAIN]

DEFAULT_LEAD_TIME = 60      # min; how early "soon" is reported
MIN_LEAD_TIME = 5
MAX_LEAD_TIME = 120         # RV reaches 2 hours ahead

DEFAULT_WARNING_THRESHOLD = 0.3   # mm/h; above this a window counts as wet
DEFAULT_MIN_DURATION = 10         # min; shorter events are treated as noise ...
DEFAULT_MIN_PEAK = 1.0            # mm/h; ... unless they reach this intensity

# HymecNG labels that describe actual precipitation.
WET_TYPES = (
    "drizzle", "rain", "freezing_drizzle", "freezing_rain", "sleet",
    "snow", "graupel", "hail", "large_hail",
)


@dataclass(frozen=True)
class _Window:
    start: int      # minutes from now (clamped at 0)
    end: int        # minutes from now
    intensity: float
    wet: bool


@dataclass(frozen=True)
class _Event:
    start: int
    end: int | None     # None = still wet at the end of the horizon
    peak: float
    amount: float       # mm
    now: bool           # wet in the window covering now


def _round(value: float) -> int:
    """Round half up, like Jinja's round(0) the template version used."""
    return math.floor(value + 0.5)


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def intensity_level(peak: float) -> str:
    """DWD intensity level (German, as used in the notification text)."""
    if peak < 2.5:
        return "leicht"
    if peak < 10:
        return "mäßig"
    if peak < 50:
        return "stark"
    return "sehr stark"


def evaluate(
    samples: list[dict] | None,
    now: datetime,
    *,
    lead_time: float = DEFAULT_LEAD_TIME,
    threshold: float = DEFAULT_WARNING_THRESHOLD,
    min_duration: float = DEFAULT_MIN_DURATION,
    min_peak: float = DEFAULT_MIN_PEAK,
    use_area: bool = True,
    type_here: str | None = None,
    type_nearby: str | None = None,
) -> dict[str, Any] | None:
    """Return the warning state and its details, or ``None`` without forecast.

    ``samples`` are the RV ``forecast_5min`` entries (``start``/``end`` as ISO
    strings or datetimes, ``intensity`` and optionally ``intensity_area`` in
    mm/h). With ``use_area`` the neighbourhood intensity is used where present.
    ``type_here`` is the HymecNG type on the own cell, ``type_nearby`` the type
    of the closest precipitation around it.
    """
    windows: list[_Window] = []
    for sample in samples or []:
        start, end = _parse_ts(sample.get("start")), _parse_ts(sample.get("end"))
        if start is None or end is None or end <= now:
            continue
        raw = sample.get("intensity_area") if use_area else None
        if raw is None:
            raw = sample.get("intensity")
        intensity = float(raw) if raw is not None else 0.0
        windows.append(_Window(
            start=max(_round((start - now).total_seconds() / 60), 0),
            end=_round((end - now).total_seconds() / 60),
            intensity=intensity,
            wet=intensity > threshold,
        ))

    if not windows:
        return None
    horizon = windows[-1].end

    # Contiguous wet runs.
    events: list[_Event] = []
    cur: dict[str, Any] | None = None
    for idx, w in enumerate(windows):
        if w.wet:
            if cur is None:
                cur = {"start": w.start, "peak": w.intensity,
                       "amount": w.intensity / 12, "now": idx == 0}
            else:
                cur["peak"] = max(cur["peak"], w.intensity)
                cur["amount"] += w.intensity / 12
        elif cur is not None:
            events.append(_Event(end=w.start, **cur))
            cur = None
    if cur is not None:
        events.append(_Event(end=None, **cur))

    # First relevant event; open events at the horizon always count.
    event = next(
        (
            e for e in events
            if e.end is None or (e.end - e.start) >= min_duration or e.peak >= min_peak
        ),
        None,
    )

    if event is not None and event.now:
        state = STATE_RAIN
    elif event is not None and event.start <= lead_time:
        state = STATE_SOON
    else:
        state = STATE_DRY

    if event is None:
        length = 0
        precip_type, source = "", ""
    else:
        length = (event.end if event.end is not None else horizon) - event.start
        if type_here in WET_TYPES:
            precip_type, source = type_here, "radar"
        elif type_nearby in WET_TYPES:
            precip_type, source = type_nearby, "radar_nearby"
        else:
            precip_type, source = "", ""

    first_end = _parse_ts((samples or [{}])[0].get("end"))
    return {
        "state": state,
        "rain_starts_in_min": event.start if event else None,
        "next_length": int(length),
        "next_open_end": event is not None and event.end is None,
        "current_open_end": state == STATE_RAIN and event.end is None,
        "current_remaining_min": (
            event.end if state == STATE_RAIN and event.end is not None else None
        ),
        "forecast_remaining_horizon_min": horizon,
        "next_peak_intensity": round(event.peak, 1) if event else 0.0,
        "next_amount_mm": round(event.amount, 1) if event else 0.0,
        "next_intensity_level": intensity_level(event.peak) if event else "",
        "precipitation_type": precip_type,
        "precipitation_type_source": source,
        "precipitation_type_radar": type_here,
        "forecast_age_min": (
            _round((now - first_end).total_seconds() / 60) if first_end else None
        ),
        "lead_time_min": int(lead_time),
    }


class WarningSettings:
    """Mutable, shared lead time for the rain warning (set by the number entity)."""

    def __init__(self, lead_time: float = DEFAULT_LEAD_TIME) -> None:
        self.lead_time = lead_time
        self._listeners: list = []

    def set_lead_time(self, value: float) -> None:
        self.lead_time = value
        for listener in list(self._listeners):
            listener()

    def add_listener(self, listener):
        """Register a callback; returns a function that removes it."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)
