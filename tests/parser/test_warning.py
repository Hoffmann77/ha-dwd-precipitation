"""Tests for the pure rain-warning logic in warning.py."""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.dwd_precipitation.warning import (
    WarningSettings,
    evaluate,
    intensity_level,
)

NOW = datetime(2026, 10, 8, 6, 0, 30, tzinfo=timezone.utc)


def _samples(intensities, area=None):
    """RV-like samples: index 0 is the analysis window that already ended."""
    base = NOW - timedelta(minutes=5)
    out = []
    for k, value in enumerate(intensities):
        sample = {
            "lead": 5 * k,
            "start": (base + timedelta(minutes=5 * k - 5)).isoformat(),
            "end": (base + timedelta(minutes=5 * k)).isoformat(),
            "intensity": value,
        }
        if area is not None:
            sample["intensity_area"] = area[k]
        out.append(sample)
    return out


def _pad(values):
    return values + [0.0] * (26 - len(values))


def test_no_forecast_returns_none():
    assert evaluate([], NOW) is None
    assert evaluate(None, NOW) is None


def test_dry():
    r = evaluate(_samples(_pad([])), NOW)
    assert r["state"] == "dry"
    assert r["rain_starts_in_min"] is None
    assert r["precipitation_type"] == ""


def test_noise_below_threshold_is_dry():
    assert evaluate(_samples(_pad([0, 0, 0, 0.1, 0.2])), NOW)["state"] == "dry"


def test_short_weak_blip_is_skipped():
    assert evaluate(_samples(_pad([0, 0, 0, 0.5])), NOW)["state"] == "dry"


def test_ten_minutes_counts_as_soon():
    r = evaluate(_samples(_pad([0, 0, 0, 0.5, 0.6])), NOW, lead_time=30)
    assert r["state"] == "soon"
    assert r["rain_starts_in_min"] == 5
    assert r["next_length"] == 10
    assert r["next_intensity_level"] == "leicht"


def test_short_but_strong_counts():
    r = evaluate(_samples(_pad([0, 0, 0, 2.0])), NOW)
    assert r["state"] == "soon"
    assert r["next_length"] == 5


def test_blip_now_is_skipped_for_later_event():
    r = evaluate(_samples(_pad([0, 0, 0.5, 0, 0, 1, 1, 1])), NOW)
    assert r["state"] == "soon"
    assert r["rain_starts_in_min"] == 15


def test_raining_now():
    r = evaluate(_samples(_pad([0, 0, 0.5, 0.5])), NOW)
    assert r["state"] == "rain"
    assert r["rain_starts_in_min"] == 0
    assert r["current_remaining_min"] == 10
    assert r["current_open_end"] is False


def test_lead_time_decides_between_soon_and_dry():
    s = _samples(_pad([0] * 8 + [2, 2, 2]))
    assert evaluate(s, NOW, lead_time=60)["state"] == "soon"
    assert evaluate(s, NOW, lead_time=15)["state"] == "dry"


def test_open_event_at_horizon():
    r = evaluate(_samples([0] * 24 + [0.4, 0.4]), NOW, lead_time=120)
    assert r["state"] == "soon"
    assert r["next_open_end"] is True


def test_area_intensity_warns_earlier_and_falls_back():
    own = _pad([0, 0, 0, 0, 0, 2, 2, 2])
    area = _pad([0, 0, 0, 0, 2, 2, 2, 2])
    assert evaluate(_samples(own), NOW)["rain_starts_in_min"] == 15
    assert evaluate(_samples(own, area), NOW)["rain_starts_in_min"] == 10
    assert evaluate(_samples(own, area), NOW, use_area=False)["rain_starts_in_min"] == 15


def test_type_prefers_own_cell_then_nearby():
    s = _samples(_pad([0, 0, 0, 2, 2]))
    r = evaluate(s, NOW, type_here="snow", type_nearby="rain")
    assert (r["precipitation_type"], r["precipitation_type_source"]) == ("snow", "radar")
    r = evaluate(s, NOW, type_here="no_precipitation", type_nearby="rain")
    assert (r["precipitation_type"], r["precipitation_type_source"]) == ("rain", "radar_nearby")
    r = evaluate(s, NOW, type_here=None, type_nearby=None)
    assert r["precipitation_type"] == ""


def test_forecast_age():
    r = evaluate(_samples(_pad([])), NOW)
    assert r["forecast_age_min"] == 5


@pytest.mark.parametrize(
    ("peak", "level"), [(0.5, "leicht"), (2.5, "mäßig"), (10, "stark"), (50, "sehr stark")]
)
def test_intensity_level(peak, level):
    assert intensity_level(peak) == level


def test_settings_notify_listeners():
    settings = WarningSettings()
    calls = []
    remove = settings.add_listener(lambda: calls.append(settings.lead_time))
    settings.set_lead_time(30)
    remove()
    settings.set_lead_time(45)
    assert calls == [30]
