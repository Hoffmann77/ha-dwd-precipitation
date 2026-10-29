"""DwdOptions: one typed snapshot of an entry's options (needs HA for const)."""

from __future__ import annotations

import pytest

from custom_components.dwd_precipitation.options import DEFAULT_OPTIONS, DwdOptions


def test_an_entry_without_options_gets_the_defaults():
    options = DwdOptions.from_options({})
    for key, default in DEFAULT_OPTIONS.items():
        assert getattr(options, key) == default
    assert options.unknown_dry_streak_source is None


def test_stored_values_win():
    options = DwdOptions.from_options(
        {"full_rolling_series": True, "rain_event_threshold": 0.4, "rain_events": 1}
    )
    assert options.full_rolling_series is True
    assert options.rain_event_threshold == 0.4
    assert options.rain_events is True


@pytest.mark.parametrize(
    ("source", "key"), [("rw", "rw_10min"), ("rs", "rs"), (None, "rw_10min")]
)
def test_the_dry_streak_counts_rws_ten_minute_runs(source, key):
    stored = {} if source is None else {"dry_streak_source": source}
    assert DwdOptions.from_options(stored).dry_streak_coordinator_key == key


def test_an_unknown_dry_streak_source_counts_as_the_default():
    options = DwdOptions.from_options({"dry_streak_source": "radar"})
    assert options.dry_streak_source == DEFAULT_OPTIONS["dry_streak_source"]
    assert options.unknown_dry_streak_source == "radar"
