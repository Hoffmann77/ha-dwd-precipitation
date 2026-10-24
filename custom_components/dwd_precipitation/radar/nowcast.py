"""Pure nowcast helpers for the RADVOR (RV and RS) forecast series.

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

from typing import overload

LEAD_STEP = 5
MAX_LEAD = 120
LEADS = list(range(0, MAX_LEAD + 1, LEAD_STEP))  # [0, 5, ..., 120] → 25 entries

# Number of 5-minute steps per hour — the factor to turn a 5-minute
# accumulation (mm) into an intensity rate (mm/h).
STEPS_PER_HOUR = 60 // LEAD_STEP  # 12

# Lead lists for the two hourly comparison buckets (matching the RS product).
HOUR1_LEADS = list(range(LEAD_STEP, 60 + 1, LEAD_STEP))   # 5..60   → [T, T+60]
HOUR2_LEADS = list(range(60 + LEAD_STEP, 120 + 1, LEAD_STEP))  # 65..120 → [T+60, T+120]

# RS leads whose rolling 60-minute window lies wholly in the future. An RS
# member at lead L covers [T+L-60, T+L], so 60 is [T, T+60] and 120 is
# [T+60, T+120]; the leads below 60 still include observed rain.
FUTURE_HOUR_LEADS = list(range(60, MAX_LEAD + 1, LEAD_STEP))  # 60..120 → 13 windows

# The analyses of earlier releases the hour ending at T needs: [T-60, T] is
# the analysis of release T and of the 11 releases before it.
PAST_STEPS = STEPS_PER_HOUR - 1  # 11

# RS and RV store amounts in 0.001 mm steps (ODIM gain). Rolling-hour totals are
# rounded to it, so a sum of twelve float32 RV steps and the matching RS member
# compare equal instead of differing in the seventh decimal.
MM_DECIMALS = 3


@overload
def round_mm(value: float) -> float: ...
@overload
def round_mm(value: None) -> None: ...
def round_mm(value: float | None) -> float | None:
    """Round an amount (mm) to the ODIM resolution; None stays None.

    DWD stores RADVOR amounts in steps of 0.001 mm, so three decimals lose
    nothing and remove the noise float32 storage and float sums add (0.123
    instead of 0.12300000339746475). Always a float, so an empty sum (the int
    0) is published as 0.0 too.

    """
    return None if value is None else round(value + 0.0, MM_DECIMALS)

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
    """Return True when a 5-minute amount counts as precipitation.

    ``threshold`` is in mm per 5-minute step (the configured mm/h divided by
    12). Strictly above the threshold counts; a step without data never does.

    """
    return value is not None and value > threshold


def bucket_max_intensity(
    values: list[float | None], leads: list[int]
) -> float | None:
    """Return the peak intensity (mm/h) over the given leads.

    ``values`` are the RV amounts aligned to LEADS, ``leads`` the minutes to
    look at (HOUR1_LEADS for the next hour, say). Each 5-minute amount is
    scaled to an hourly rate (x12) and the largest is returned, rounded to
    0.001. Steps without data are skipped; None only when all are missing.

    """
    present = [
        value for lead in leads if (value := values[lead // LEAD_STEP]) is not None
    ]
    if not present:
        return None
    return round_mm(float(max(present)) * STEPS_PER_HOUR)


def rolling_hour_sums(
    values: list[float | None], past: list[float | None] | None = None
) -> list[float | None]:
    """Return rolling 60-minute totals (mm), like RS's members, from RV's steps.

    ``values`` are the 25 RV amounts of one release (the analysis, then 24
    forecast steps). Each lead's total adds the twelve 5-minute steps ending at
    it, and the result is aligned to LEADS, None where no total is built.

    Without ``past`` only the 13 hours wholly in the forecast (ending at +60 to
    +120) are built; with the analyses of the 11 releases before T, every lead
    is. A missing step counts as 0, as in RS, which is this sum in almost every
    cell (ADR 0009).

    """
    if past is not None and len(past) != PAST_STEPS:
        raise ValueError(f"past holds {len(past)} analyses, not {PAST_STEPS}")

    # Step i ends at T + (i - PAST_STEPS) * 5 min. Without a past, the padding
    # is never read: the future windows start at step PAST_STEPS + 1.
    steps = (past if past is not None else [None] * PAST_STEPS) + values
    sums: list[float | None] = [None] * len(LEADS)
    for lead in LEADS if past is not None else FUTURE_HOUR_LEADS:
        i = lead // LEAD_STEP
        present = [float(v) for v in steps[i:i + STEPS_PER_HOUR] if v is not None]
        if present:
            sums[i] = round_mm(sum(present))
    return sums


def peak_rolling_hour(values: list[float | None]) -> tuple[float | None, int | None]:
    """Return the wettest rolling hour wholly in the future, and its lead.

    ``values`` are rolling-hour totals aligned to LEADS (see
    rolling_hour_sums). Compares the totals ending at +60 to +120 minutes; a
    tie goes to the earlier hour, the one an automation must act on first.
    Missing totals are skipped; (None, None) when all are missing.

    """
    peak: float | None = None
    peak_lead: int | None = None
    for lead in FUTURE_HOUR_LEADS:
        value = values[lead // LEAD_STEP]
        if value is not None and (peak is None or value > peak):
            peak, peak_lead = float(value), lead
    return peak, peak_lead


def _end_episode(
    future: list[float | None], threshold: float, episode_start_k: int
) -> int | None:
    """Return when the first rain episode ends, in minutes from now.

    ``future`` holds the forecast steps (index k starts at T + 5k minutes) and
    ``episode_start_k`` the step the rain starts in. The end is the first dry
    step at or after it; None when it rains to the end of the forecast.

    """
    for k in range(episode_start_k, len(future)):
        if not _is_rain(future[k], threshold):
            return k * LEAD_STEP
    return None


def _end_clearing(
    future: list[float | None], threshold: float, episode_start_k: int
) -> int | None:
    """Return when rain stops for good within the forecast, in minutes from now.

    Looks through dry gaps to the last rainy step from ``episode_start_k`` on;
    the end is the boundary after it. None when the forecast's last step is
    still rainy, 0 when it rains now but no more rain is forecast.

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
    """Return in how many minutes precipitation starts and ends.

    ``values`` are one release's 25 RV amounts, ``threshold`` the wet limit in
    mm per 5 minutes. The start is 0 when it is raining now, and None when no
    rain is forecast within two hours. The end follows ``end_algorithm``: the
    end of the first episode ("episode"), or when no more rain is forecast at
    all ("clearing"); None when it does not end within the forecast.

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
