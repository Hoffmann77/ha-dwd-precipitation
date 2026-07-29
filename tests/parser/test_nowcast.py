"""Pure unit tests for the RV nowcast helpers (no HA/numpy dependency)."""

from __future__ import annotations

import pytest

from radar.nowcast import (
    END_ALGO_CLEARING,
    END_ALGO_EPISODE,
    HOUR1_LEADS,
    HOUR2_LEADS,
    LEADS,
    STEPS_PER_HOUR,
    bucket_max_intensity,
    detect_start_end,
)


def _series(**overrides):
    """Build a 25-entry series (leads 0..120) defaulting to 0.0."""
    values = [0.0] * len(LEADS)
    for lead, value in overrides.items():
        values[int(lead) // 5] = value
    return values


# --- bucket leads -------------------------------------------------------

def test_bucket_leads_are_disjoint_hours():
    assert HOUR1_LEADS == list(range(5, 61, 5))
    assert HOUR2_LEADS == list(range(65, 121, 5))
    assert set(HOUR1_LEADS).isdisjoint(HOUR2_LEADS)


# --- bucket_max_intensity ----------------------------------------------

def test_steps_per_hour_is_twelve():
    assert STEPS_PER_HOUR == 12


def test_bucket_max_intensity_extrapolates_peak_to_mm_per_hour():
    values = _series(**{"5": 0.5, "60": 1.5, "65": 2.0})
    # HOUR1 peak 1.5 mm/5min → 18 mm/h; HOUR2 peak 2.0 mm/5min → 24 mm/h.
    assert bucket_max_intensity(values, HOUR1_LEADS) == pytest.approx(18.0)
    assert bucket_max_intensity(values, HOUR2_LEADS) == pytest.approx(24.0)


def test_bucket_max_intensity_skips_none_but_all_none_is_none():
    values = _series(**{"5": 1.0})
    values[HOUR1_LEADS[1] // 5] = None  # one hole
    assert bucket_max_intensity(values, HOUR1_LEADS) == pytest.approx(12.0)

    all_none = [None] * len(LEADS)
    assert bucket_max_intensity(all_none, HOUR1_LEADS) is None


# --- detect_start_end ---------------------------------------------------

def test_never_rains():
    assert detect_start_end(_series(), 0.0) == (None, None)


def test_raining_now_and_stops():
    # rain in windows ending at lead 0/5/10 → last rain ends at T+10
    values = _series(**{"0": 1.0, "5": 1.0, "10": 1.0})
    assert detect_start_end(values, 0.0) == (0, 10)


def test_starts_later_and_stops():
    # dry now; rain in windows ending 30..45 → starts T+25, ends T+45
    values = _series(**{"30": 1.0, "35": 1.0, "40": 1.0, "45": 1.0})
    assert detect_start_end(values, 0.0) == (25, 45)


def test_rain_through_horizon_has_no_end():
    values = [1.0] * len(LEADS)
    assert detect_start_end(values, 0.0) == (0, None)


def test_starts_and_runs_to_horizon():
    values = _series()
    for lead in range(60, 121, 5):
        values[lead // 5] = 1.0
    # first future rain is lead 60 → 55 min out; never dry again → no end
    assert detect_start_end(values, 0.0) == (55, None)


def test_threshold_is_exclusive_and_configurable():
    values = _series(**{"5": 0.1, "10": 0.4})
    # threshold 0.1 → 0.1 does NOT count (strictly greater), 0.4 does
    assert detect_start_end(values, 0.1) == (5, 10)
    # threshold 0.0 → both count
    assert detect_start_end(values, 0.0) == (0, 10)


def test_none_values_are_not_rain():
    values = _series(**{"10": 1.0})
    values[1] = None  # lead 5 nodata
    # lead 5 None → not rain; only rain window ends at lead 10 → starts T+5, ends T+10
    assert detect_start_end(values, 0.0) == (5, 10)


def test_default_algorithm_is_episode():
    # Rain now and at lead 5, a lull, then rain again at lead 60.
    values = _series(**{"0": 1.0, "5": 1.0, "60": 1.0})
    # No explicit algorithm → episode: the first lull ends the episode at T+5.
    assert detect_start_end(values, 0.0) == (0, 5)
    assert detect_start_end(values, 0.0, END_ALGO_EPISODE) == (0, 5)


# --- detect_start_end: clearing algorithm --------------------------------

def test_clearing_matches_episode_for_single_episode():
    # A single uninterrupted episode: both algorithms agree.
    values = _series(**{"30": 1.0, "35": 1.0, "40": 1.0, "45": 1.0})
    assert detect_start_end(values, 0.0, END_ALGO_EPISODE) == (25, 45)
    assert detect_start_end(values, 0.0, END_ALGO_CLEARING) == (25, 45)


def test_clearing_looks_through_lull_to_last_wave():
    # Dry now; a wave at lead 10, a lull, then a second wave at lead 60.
    values = _series(**{"10": 1.0, "60": 1.0})
    # Episode ends at the first lull (T+10); clearing waits out the last wave.
    assert detect_start_end(values, 0.0, END_ALGO_EPISODE) == (5, 10)
    assert detect_start_end(values, 0.0, END_ALGO_CLEARING) == (5, 60)


def test_clearing_while_raining_now_with_later_wave():
    # Raining now and at lead 5, a lull, then rain again at lead 30.
    values = _series(**{"0": 1.0, "5": 1.0, "30": 1.0})
    assert detect_start_end(values, 0.0, END_ALGO_EPISODE) == (0, 5)
    assert detect_start_end(values, 0.0, END_ALGO_CLEARING) == (0, 30)


def test_clearing_rain_through_horizon_has_no_end():
    values = [1.0] * len(LEADS)
    assert detect_start_end(values, 0.0, END_ALGO_CLEARING) == (0, None)


def test_clearing_last_wave_at_horizon_edge_has_no_end():
    # A lull then rain that runs to the +120 edge → never clears in the horizon.
    values = _series(**{"10": 1.0, "115": 1.0, "120": 1.0})
    assert detect_start_end(values, 0.0, END_ALGO_CLEARING) == (5, None)


def test_clearing_never_rains():
    assert detect_start_end(_series(), 0.0, END_ALGO_CLEARING) == (None, None)
