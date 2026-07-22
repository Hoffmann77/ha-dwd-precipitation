"""Pure nowcast helpers for the RV 5-minute forecast series.

These functions operate on a plain list of per-lead precipitation values and
carry no Home Assistant or numpy dependency, so they can be unit-tested in
isolation (the parser test tier).

The RV product provides 25 grids at 5-minute steps. For a single grid cell the
values are represented as a list ``values`` aligned to
``LEADS = [0, 5, 10, ..., 120]`` (minutes). Index 0 is the latest analysis
window ``[T-5, T]`` (``T`` = release base time); index ``k`` (k >= 1) is the
forecast window ``[T + (k-1)*5, T + k*5]``.
"""

from __future__ import annotations

LEAD_STEP = 5
MAX_LEAD = 120
LEADS = list(range(0, MAX_LEAD + 1, LEAD_STEP))  # [0, 5, ..., 120] → 25 entries

# Number of 5-minute steps per hour — the factor to turn a 5-minute
# accumulation (mm) into an intensity rate (mm/h).
STEPS_PER_HOUR = 60 // LEAD_STEP  # 12

# Lead lists for the two hourly comparison buckets (matching the RS product).
HOUR1_LEADS = list(range(LEAD_STEP, 60 + 1, LEAD_STEP))   # 5..60   → [T, T+60]
HOUR2_LEADS = list(range(60 + LEAD_STEP, 120 + 1, LEAD_STEP))  # 65..120 → [T+60, T+120]


def _is_rain(value: float | None, threshold: float) -> bool:
    """Return True when a 5-minute accumulation counts as precipitation."""
    return value is not None and value > threshold


def bucket_sum(values: list[float | None], leads: list[int]) -> float | None:
    """Sum the cell values for the given lead minutes.

    ``values`` is aligned to :data:`LEADS`. ``None`` entries (nodata) are
    skipped; the result is ``None`` only when *every* constituent is missing.
    """
    present = [
        values[lead // LEAD_STEP]
        for lead in leads
        if values[lead // LEAD_STEP] is not None
    ]
    if not present:
        return None
    return float(sum(present))


def bucket_max_intensity(
    values: list[float | None], leads: list[int]
) -> float | None:
    """Return the peak intensity (mm/h) over the given lead minutes.

    ``values`` is aligned to :data:`LEADS` and holds 5-minute accumulations
    (mm). Each is extrapolated to an hourly rate via :data:`STEPS_PER_HOUR`, and
    the maximum is returned. ``None`` entries (nodata) are skipped; the result is
    ``None`` only when *every* constituent is missing.
    """
    present = [
        values[lead // LEAD_STEP]
        for lead in leads
        if values[lead // LEAD_STEP] is not None
    ]
    if not present:
        return None
    return float(max(present)) * STEPS_PER_HOUR


def detect_start_end(
    values: list[float | None], threshold: float
) -> tuple[int | None, int | None]:
    """Return ``(start_in, end_in)`` in minutes from now (``T``).

    ``values`` is aligned to :data:`LEADS`. Semantics:

    * ``start_in`` — minutes until precipitation begins. ``0`` if it is already
      raining (analysis window, index 0). ``None`` if no precipitation occurs
      within the 2-hour horizon.
    * ``end_in`` — minutes until the current/next precipitation episode ends.
      ``None`` if precipitation never occurs, or if it persists through the end
      of the forecast horizon (i.e. the stop time is beyond +120 min).
    """
    currently_raining = _is_rain(values[0], threshold)
    future = values[1:]  # leads 5..120; future[k] window starts at T + k*5

    if currently_raining:
        start_in: int | None = 0
        episode_start_k = 0
    else:
        start_in = None
        episode_start_k = None
        for k, value in enumerate(future):
            if _is_rain(value, threshold):
                start_in = k * LEAD_STEP
                episode_start_k = k
                break

    end_in: int | None = None
    if episode_start_k is not None:
        for k in range(episode_start_k, len(future)):
            if not _is_rain(future[k], threshold):
                end_in = k * LEAD_STEP
                break

    return start_in, end_in
