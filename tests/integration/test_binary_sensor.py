"""Binary sensor tests — exercise is_on / attributes with a stubbed coordinator.

Needs the ha-test dependency group installed (binary_sensor.py imports HA).
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from custom_components.dwd_precipitation.const import CONF_EXTRA_ATTRIBUTES
from custom_components.dwd_precipitation.coordinator import (
    CoordinatorData,
    ProductMetadata,
)
from custom_components.dwd_precipitation.binary_sensor import (
    BINARY_SENSORS,
    DwdBinarySensorEntity,
)

UTC = timezone.utc


def _make_binary(data, metadata=None, extra=False) -> DwdBinarySensorEntity:
    entity = DwdBinarySensorEntity.__new__(DwdBinarySensorEntity)
    entity.entity_description = BINARY_SENSORS[0]
    entity.coordinator = SimpleNamespace(
        config_entry=SimpleNamespace(options={CONF_EXTRA_ATTRIBUTES: extra}),
        data=None
        if data is None
        else CoordinatorData(data=data, metadata=metadata or {}),
    )
    return entity


def test_on_when_rain_within_2h_with_start_time_attributes():
    data = {
        "rain_within_2h": True,
        "start_in": 25,
        "start_at": datetime(2026, 7, 16, 20, 55, tzinfo=UTC),
    }
    entity = _make_binary(data)
    assert entity.is_on is True
    attrs = entity.extra_state_attributes
    assert attrs["minutes_until"] == 25
    assert attrs["at"] == "2026-07-16T20:55:00+00:00"


def test_off_when_no_rain():
    data = {"rain_within_2h": False, "start_in": None, "start_at": None}
    entity = _make_binary(data)
    assert entity.is_on is False
    attrs = entity.extra_state_attributes
    assert attrs["minutes_until"] is None
    assert attrs["at"] is None


def test_none_when_no_data():
    entity = _make_binary(None)
    assert entity.is_on is None
    assert entity.extra_state_attributes == {}


def test_raw_forecast_exposed_by_default():
    data = {"rain_within_2h": True, "start_in": 0, "start_at": None}
    samples = [{"lead": 0, "value": 1.0, "intensity": 12.0}]
    meta = {
        "rain_within_2h": ProductMetadata(
            source_product="RV", source_timestamp=None, samples=samples
        )
    }

    # The full 5-minute series is surfaced regardless of the diagnostic option.
    off = _make_binary(data, metadata=meta, extra=False)
    assert off.extra_state_attributes["forecast_5min"] == samples

    on = _make_binary(data, metadata=meta, extra=True)
    assert on.extra_state_attributes["forecast_5min"] == samples

    # forecast_5min is excluded from the recorder history.
    assert "forecast_5min" in DwdBinarySensorEntity._unrecorded_attributes
