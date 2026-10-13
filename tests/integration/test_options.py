"""DwdOptions: one typed snapshot of an entry's options (needs HA for const)."""

from __future__ import annotations

from dataclasses import fields

import pytest

from custom_components.dwd_precipitation.options import (
    _FIELD_BY_KEY,
    DEFAULT_OPTIONS,
    DwdOptions,
)


def test_every_option_has_a_field_and_a_default():
    assert set(_FIELD_BY_KEY) == set(DEFAULT_OPTIONS)
    assert set(_FIELD_BY_KEY.values()) == {
        f.name for f in fields(DwdOptions) if f.name != "unknown_dry_streak_source"
    }


def test_an_entry_without_options_gets_the_defaults():
    options = DwdOptions.from_options({})
    for key, field in _FIELD_BY_KEY.items():
        assert getattr(options, field) == DEFAULT_OPTIONS[key]
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
