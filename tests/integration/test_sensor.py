"""Sensor extra_state_attributes / native_value tests — needs HA installed.

Uses lightweight stubs for the coordinator so the entity's pure presentation
logic is exercised without a running HomeAssistant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.dwd_precipitation import sensor as sensor_module
from custom_components.dwd_precipitation.const import (
    CONF_EXTRA_ATTRIBUTES,
    CONF_RAIN_THRESHOLD,
)
from custom_components.dwd_precipitation.coordinator import (
    CoordinatorData,
    ProductMetadata,
)
from custom_components.dwd_precipitation.dry_streak import (
    DryStreakExtraData,
    downtime_correction,
    fresh_anchor,
    scalar_reading,
)
from custom_components.dwd_precipitation.sensor import (
    DaysWithoutRainSensor,
    PrecipitationSensorEntity,
    PrecipitationSensorEntityDescription,
)

UTC = timezone.utc


def _make_sensor(metadata, data=1.0, extra=True) -> PrecipitationSensorEntity:
    desc = PrecipitationSensorEntityDescription(
        key="k", product_key="rs", access_fn=lambda m: m,
    )
    sensor = PrecipitationSensorEntity.__new__(PrecipitationSensorEntity)
    sensor.entity_description = desc
    sensor.coordinator = SimpleNamespace(
        config_entry=SimpleNamespace(options={CONF_EXTRA_ATTRIBUTES: extra}),
        data=CoordinatorData(data=data, metadata=metadata),
    )
    return sensor


def test_extra_attrs_disabled_returns_empty():
    meta = ProductMetadata(
        source_product="RS", source_timestamp=datetime(2026, 5, 18, 16, tzinfo=UTC),
    )
    assert _make_sensor(meta, extra=False).extra_state_attributes == {}


def test_extra_attrs_includes_window_when_present():
    meta = ProductMetadata(
        source_product="RS",
        source_timestamp=datetime(2026, 5, 18, 16, tzinfo=UTC),
        lead_time_minutes=60,
        data_start=datetime(2026, 5, 18, 16, tzinfo=UTC),
        data_end=datetime(2026, 5, 18, 17, tzinfo=UTC),
    )
    attrs = _make_sensor(meta).extra_state_attributes
    assert attrs["source_product"] == "RS"
    assert attrs["source_timestamp"] == "2026-05-18T16:00:00+00:00"
    assert attrs["lead_time_minutes"] == 60
    assert attrs["data_start"] == "2026-05-18T16:00:00+00:00"
    assert attrs["data_end"] == "2026-05-18T17:00:00+00:00"


def test_extra_attrs_omits_window_when_absent():
    meta = ProductMetadata(
        source_product="RW", source_timestamp=datetime(2025, 6, 1, 12, 50, tzinfo=UTC),
    )
    attrs = _make_sensor(meta).extra_state_attributes
    assert "data_start" not in attrs
    assert "data_end" not in attrs
    assert attrs["source_timestamp"] == "2025-06-01T12:50:00+00:00"


def test_native_value_uses_access_fn():
    meta = ProductMetadata(source_product="RS", source_timestamp=None)
    assert _make_sensor(meta, data=2.5).native_value == 2.5


# ===========================================================================
# DaysWithoutRainSensor
# ===========================================================================

def _make_days_sensor(
    dry_since=None, rs_list=None, meta_list=None, threshold=1.0
) -> DaysWithoutRainSensor:
    """Build a DaysWithoutRainSensor with a stubbed rs coordinator."""
    sensor = DaysWithoutRainSensor.__new__(DaysWithoutRainSensor)
    sensor._dry_since = dry_since
    data = None
    if rs_list is not None:
        data = CoordinatorData(data=rs_list, metadata=meta_list)
    sensor.coordinator = SimpleNamespace(
        config_entry=SimpleNamespace(options={CONF_RAIN_THRESHOLD: threshold}),
        data=data,
    )
    return sensor


def test_days_value_and_hours(monkeypatch):
    anchor = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)  # 2.5 days / 60 h later
    monkeypatch.setattr(sensor_module.dt_util, "utcnow", lambda: now)

    sensor = _make_days_sensor(dry_since=anchor)

    assert sensor.native_value == pytest.approx(2.5, abs=1e-6)
    attrs = sensor.extra_state_attributes
    assert attrs["hours_without_rain"] == pytest.approx(60.0)
    assert attrs["dry_since"] == anchor.isoformat()


def test_days_none_anchor_is_unknown():
    sensor = _make_days_sensor(dry_since=None)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {"hours_without_rain": None}


def test_days_future_anchor_clamped_to_zero(monkeypatch):
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(sensor_module.dt_util, "utcnow", lambda: now)
    sensor = _make_days_sensor(dry_since=now + timedelta(hours=1))
    assert sensor.native_value == 0.0
    assert sensor.extra_state_attributes["hours_without_rain"] == 0.0


def test_process_resets_anchor_when_raining():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    meta = [ProductMetadata(source_product="RS", source_timestamp=now)]
    sensor = _make_days_sensor(
        dry_since=datetime(2026, 7, 1, tzinfo=UTC),
        rs_list=[2.0, None, None],
        meta_list=meta,
        threshold=1.0,
    )
    sensor._process()
    assert sensor._dry_since == now


def test_process_keeps_anchor_when_dry():
    old = datetime(2026, 7, 1, tzinfo=UTC)
    sensor = _make_days_sensor(
        dry_since=old, rs_list=[0.2, None, None], meta_list=[None, None, None]
    )
    sensor._process()
    assert sensor._dry_since == old


def test_process_ignores_missing_and_nan_reading():
    old = datetime(2026, 7, 1, tzinfo=UTC)
    for value in (None, float("nan")):
        sensor = _make_days_sensor(
            dry_since=old, rs_list=[value, None, None], meta_list=[None, None, None]
        )
        sensor._process()
        assert sensor._dry_since == old


def test_scalar_reading_handles_missing_coordinator():
    assert scalar_reading(None) == (None, None, None)
    assert scalar_reading(SimpleNamespace(data=None)) == (None, None, None)


def test_downtime_correction_rw_rain_resets():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    rw_end = datetime(2026, 7, 3, 11, 50, tzinfo=UTC)
    rw = (2.0, datetime(2026, 7, 3, 10, 50, tzinfo=UTC), rw_end)
    sf = (5.0, datetime(2026, 7, 2, 11, 50, tzinfo=UTC), rw_end)
    assert downtime_correction(1.0, rw, sf, now) == rw_end


def test_downtime_correction_sf_only_caps_at_window_start():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    sf_start = datetime(2026, 7, 2, 11, 50, tzinfo=UTC)
    rw = (0.0, datetime(2026, 7, 3, 10, 50, tzinfo=UTC), now)
    sf = (5.0, sf_start, now)
    assert downtime_correction(1.0, rw, sf, now) == sf_start


def test_downtime_correction_no_rain_returns_none():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    rw = (0.0, now, now)
    sf = (0.1, now, now)
    assert downtime_correction(1.0, rw, sf, now) is None


def test_fresh_anchor_prefers_sf_dry_window():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    sf_start = datetime(2026, 7, 2, 11, 50, tzinfo=UTC)
    rw_start = datetime(2026, 7, 3, 10, 50, tzinfo=UTC)
    rw = (0.0, rw_start, now)
    sf = (0.0, sf_start, now)
    assert fresh_anchor(1.0, rw, sf, now) == sf_start


def test_fresh_anchor_falls_back_to_now_when_recently_wet():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    rw = (5.0, datetime(2026, 7, 3, 10, 50, tzinfo=UTC), now)
    sf = (5.0, datetime(2026, 7, 2, 11, 50, tzinfo=UTC), now)
    assert fresh_anchor(1.0, rw, sf, now) == now


def test_dry_streak_extra_data_roundtrip():
    anchor = datetime(2026, 7, 1, 8, 30, tzinfo=UTC)
    restored = DryStreakExtraData.from_dict(DryStreakExtraData(anchor).as_dict())
    assert restored.dry_since == anchor
    assert DryStreakExtraData.from_dict({"dry_since": None}).dry_since is None
