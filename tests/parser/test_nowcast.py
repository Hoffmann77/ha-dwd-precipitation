"""Pure unit tests for the RV nowcast helpers (no HA/numpy dependency)."""

from __future__ import annotations

import pytest

from radar.nowcast import (
    HOUR1_LEADS,
    HOUR2_LEADS,
    LEADS,
    bucket_sum,
    detect_start_end,
)


def _series(**overrides):
    """Build a 25-entry series (leads 0..120) defaulting to 0.0."""
    values = [0.0] * len(LEADS)
    for lead, value in overrides.items():
        values[int(lead) // 5] = value
    return values


# --- bucket_sum ---------------------------------------------------------

def test_bucket_leads_are_disjoint_hours():
    assert HOUR1_LEADS == list(range(5, 61, 5))
    assert HOUR2_LEADS == list(range(65, 121, 5))
    assert set(HOUR1_LEADS).isdisjoint(HOUR2_LEADS)


def test_bucket_sum_adds_constituents():
    values = _series(**{"5": 0.5, "60": 1.5, "65": 2.0})
    assert bucket_sum(values, HOUR1_LEADS) == pytest.approx(2.0)
    assert bucket_sum(values, HOUR2_LEADS) == pytest.approx(2.0)


def test_bucket_sum_skips_none_but_all_none_is_none():
    values = _series(**{"5": 1.0})
    values[HOUR1_LEADS[1] // 5] = None  # one hole
    assert bucket_sum(values, HOUR1_LEADS) == pytest.approx(1.0)

    all_none = [None] * len(LEADS)
    assert bucket_sum(all_none, HOUR1_LEADS) is None


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
