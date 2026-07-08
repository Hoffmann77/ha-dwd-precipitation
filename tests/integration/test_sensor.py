"""Sensor extra_state_attributes / native_value tests — needs HA installed.

Uses lightweight stubs for the coordinator so the entity's pure presentation
logic is exercised without a running HomeAssistant.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from custom_components.dwd_precipitation.const import CONF_EXTRA_ATTRIBUTES
from custom_components.dwd_precipitation.coordinator import (
    CoordinatorData,
    ProductMetadata,
)
from custom_components.dwd_precipitation.sensor import (
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
