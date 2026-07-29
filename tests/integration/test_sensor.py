"""Sensor extra_state_attributes / native_value tests — needs HA installed.

Uses lightweight stubs for the coordinator so the entity's pure presentation
logic is exercised without a running HomeAssistant.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from custom_components.dwd_precipitation.const import (
    CONF_EXTRA_ATTRIBUTES,
    START_END_MODE_DURATION,
    START_END_MODE_TIMESTAMP,
)
from custom_components.dwd_precipitation.coordinator import (
    CoordinatorData,
    ProductMetadata,
)
from homeassistant.components.sensor import SensorDeviceClass
from custom_components.dwd_precipitation.sensor import (
    PrecipitationSensorEntity,
    PrecipitationSensorEntityDescription,
    _rv_timing_sensors,
)

UTC = timezone.utc


def _make_sensor(metadata, data=1.0, extra=True) -> PrecipitationSensorEntity:
    desc = PrecipitationSensorEntityDescription(
        key="k", product_key="rs", access_fn=lambda m: m,
    )
    return _make_sensor_with_desc(desc, data=data, metadata=metadata, extra=extra)


def _make_sensor_with_desc(
    desc, data, metadata=None, extra=False
) -> PrecipitationSensorEntity:
    sensor = PrecipitationSensorEntity.__new__(PrecipitationSensorEntity)
    sensor.entity_description = desc
    sensor.coordinator = SimpleNamespace(
        config_entry=SimpleNamespace(options={CONF_EXTRA_ATTRIBUTES: extra}),
        data=CoordinatorData(data=data, metadata=metadata or {}),
    )
    return sensor


def _rv_timing_data():
    return {
        "start_in": 25,
        "start_at": datetime(2026, 7, 16, 20, 55, tzinfo=UTC),
        "end_in": 60,
        "end_at": datetime(2026, 7, 16, 21, 30, tzinfo=UTC),
    }


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


# --- merged start/end sensors ------------------------------------------

def test_timestamp_mode_state_is_time_with_minutes_attribute():
    start, end = _rv_timing_sensors(START_END_MODE_TIMESTAMP)
    assert start.device_class is SensorDeviceClass.TIMESTAMP
    assert start.key == "rv_precipitation_start"
    assert end.key == "rv_precipitation_end"

    sensor = _make_sensor_with_desc(start, data=_rv_timing_data(), extra=False)
    assert sensor.native_value == datetime(2026, 7, 16, 20, 55, tzinfo=UTC)
    # Companion value is exposed even though diagnostic attributes are disabled.
    assert sensor.extra_state_attributes == {"minutes_until": 25}


def test_duration_mode_state_is_minutes_with_time_attribute():
    start, _end = _rv_timing_sensors(START_END_MODE_DURATION)
    assert start.device_class is SensorDeviceClass.DURATION
    assert start.key == "rv_precipitation_start"

    sensor = _make_sensor_with_desc(start, data=_rv_timing_data(), extra=False)
    assert sensor.native_value == 25
    # The absolute time is serialized to an ISO string attribute.
    assert sensor.extra_state_attributes == {"at": "2026-07-16T20:55:00+00:00"}


def test_timing_keys_are_stable_across_modes():
    ts_keys = {d.key for d in _rv_timing_sensors(START_END_MODE_TIMESTAMP)}
    dur_keys = {d.key for d in _rv_timing_sensors(START_END_MODE_DURATION)}
    assert ts_keys == dur_keys == {"rv_precipitation_start", "rv_precipitation_end"}
