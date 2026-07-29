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

# Algorithms for deriving the "precipitation end" from the forecast series:
#
# * ``END_ALGO_EPISODE`` — the end of the *first* contiguous rain episode: the
#   first dry 5-minute window at or after onset. Answers "when does the rain
#   that is about to fall let up?".
# * ``END_ALGO_CLEARING`` — when no further rain is forecast anywhere in the
#   2-hour horizon: the boundary after the *last* rainy window. Answers "when
#   is it clear for good (within the forecast horizon)?".
#
# For a single uninterrupted episode the two agree; they differ when rain
# arrives in separate waves — episode reports the first lull, clearing looks
# through it to the final wave.
END_ALGO_EPISODE = "episode"
END_ALGO_CLEARING = "clearing"
DEFAULT_END_ALGO = END_ALGO_EPISODE


def _is_rain(value: float | None, threshold: float) -> bool:
    """Return True when a 5-minute accumulation counts as precipitation."""
    return value is not None and value > threshold


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


def _end_episode(
    future: list[float | None], threshold: float, episode_start_k: int
) -> int | None:
    """First dry window at or after ``episode_start_k`` (end of first episode)."""
    for k in range(episode_start_k, len(future)):
        if not _is_rain(future[k], threshold):
            return k * LEAD_STEP
    return None


def _end_clearing(
    future: list[float | None], threshold: float, episode_start_k: int
) -> int | None:
    """Boundary after the last rainy window at or after ``episode_start_k``.

    ``None`` when the last rainy window is the horizon edge (rain never clears
    within the forecast).
    """
    last_rain_k: int | None = None
    for k in range(episode_start_k, len(future)):
        if _is_rain(future[k], threshold):
            last_rain_k = k

    if last_rain_k is None:
        # Currently raining (episode_start_k == 0) but no future rain: it stops
        # at T. Otherwise the caller would not have supplied an episode start.
        return 0
    if last_rain_k == len(future) - 1:
        return None
    return (last_rain_k + 1) * LEAD_STEP


def detect_start_end(
    values: list[float | None],
    threshold: float,
    end_algorithm: str = DEFAULT_END_ALGO,
) -> tuple[int | None, int | None]:
    """Return ``(start_in, end_in)`` in minutes from now (``T``).

    ``values`` is aligned to :data:`LEADS`. Semantics:

    * ``start_in`` — minutes until precipitation begins. ``0`` if it is already
      raining (analysis window, index 0). ``None`` if no precipitation occurs
      within the 2-hour horizon.
    * ``end_in`` — minutes until precipitation ends, per ``end_algorithm``:

      - :data:`END_ALGO_EPISODE` (default): the current/next precipitation
        episode ends (first dry window after onset).
      - :data:`END_ALGO_CLEARING`: no further rain is forecast within the
        horizon (the boundary after the last rainy window).

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

    if episode_start_k is None:
        return start_in, None

    if end_algorithm == END_ALGO_CLEARING:
        end_in = _end_clearing(future, threshold, episode_start_k)
    else:
        end_in = _end_episode(future, threshold, episode_start_k)

    return start_in, end_in
