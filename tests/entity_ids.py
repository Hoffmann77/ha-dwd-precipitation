"""Entity ids by key: what released versions gave, and what is new since.

The one record of them: the setup test checks a new install against it, and
the docs test checks that the docs' Upgrading page maps every renamed
entity's old id to its new one. Ids are the object id after ``<device>_``
(``sensor.home_<id>``). HA-free.
"""

from __future__ import annotations

# Entity ids 2026.10.0 gave a new install, by key.
RELEASED_2026_10_0_IDS = {
    "radvor_rs_000": "precipitation_now",
    "radvor_rs_060": "precipitation_next_1h",
    "radvor_rs_120": "precipitation_next_1_2h",
    "radvor_peak_1h_120": "peak_hourly_precipitation_next_2h",
    "radvor_rv_max_intensity_060": "peak_intensity_next_1h",
    "radvor_rv_max_intensity_120": "peak_intensity_next_1_2h",
    "radvor_rv_precipitation_start": "precipitation_start",
    "radvor_rv_precipitation_end": "precipitation_end",
    "radvor_rv_precipitation_expected_120": "precipitation_expected",
    "hymecng_precipitation_type": "precipitation_type",
    "radolan_rw": "precipitation_last_1h",
    "radolan_sf": "precipitation_last_24h",
    "radolan_sf_yesterday": "precipitation_yesterday",
    "radolan_rw_total": "precipitation_total_hourly",
    "radolan_sf_yesterday_total": "precipitation_total_daily",
    "timespan_without_precipitation": "timespan_without_precipitation",
}

# What a new install gets for the entities renamed since.
RENAMED_SINCE_2026_10_0 = {
    "radvor_rs_000": "precipitation_last_60_min",
    "radvor_rs_060": "precipitation_next_60_min",
    "radvor_rs_120": "precipitation_next_60_120_min",
    "radvor_peak_1h_120": "peak_hourly_precipitation_next_120_min",
    "radvor_rv_max_intensity_060": "peak_intensity_next_60_min",
    "radvor_rv_max_intensity_120": "peak_intensity_next_60_120_min",
    "radolan_rw": "precipitation_previous_hour",
    "hymecng_precipitation_type": "precipitation_type_now",
    "radolan_rw_total": "precipitation_total",
}

# Added since 2026.10.0.
NEW_SINCE_2026_10_0 = {
    "radvor_rv_intensity_000": "precipitation_intensity_now",
    "radvor_rs_000_120": "precipitation_next_120_min",
    "radvor_rv_max_intensity_000_120": "peak_intensity_next_120_min",
}

# Added since 2026.10.0: one pair per rain-warning subentry, on the warning's
# own device ("<location> <warning>"), so the object id after ``<device>_`` is
# the warning's slug plus this, by domain. No released id ends like these.
RAIN_WARNING_IDS = {
    "binary_sensor": "{warning}_rain_warning",
    "sensor": "{warning}_rain_warning_status",
}
