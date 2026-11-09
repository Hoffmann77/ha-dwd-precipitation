"""Binary sensor tests: is_on and attributes on an RV coordinator's data."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.dwd_precipitation.const import CONF_EXTRA_ATTRIBUTES
from custom_components.dwd_precipitation.coordinator import (
    CoordinatorData,
    ProductMetadata,
)
from custom_components.dwd_precipitation.binary_sensor import (
    BINARY_SENSORS,
    DwdBinarySensorEntity,
)
from custom_components.dwd_precipitation.products import RadvorRV

UTC = timezone.utc


@pytest.fixture
def make_binary(make_coordinator):
    """Return a factory: the binary sensor on an RV coordinator holding ``data``."""

    def _make(data, metadata=None, extra=False) -> DwdBinarySensorEntity:
        coordinator = make_coordinator(
            RadvorRV,
            {CONF_EXTRA_ATTRIBUTES: extra},
            data=None if data is None else CoordinatorData(data, metadata or {}),
        )
        return DwdBinarySensorEntity(coordinator, BINARY_SENSORS[0])

    return _make


async def test_on_when_rain_within_2h_with_start_time_attributes(make_binary):
    data = {
        "rain_within_2h": True,
        "start_in": 25,
        "start_at": datetime(2026, 7, 16, 20, 55, tzinfo=UTC),
    }
    entity = make_binary(data)
    assert entity.is_on is True
    attrs = entity.extra_state_attributes
    assert attrs["minutes_until"] == 25
    assert attrs["at"] == "2026-07-16T20:55:00+00:00"


async def test_off_when_no_rain(make_binary):
    data = {"rain_within_2h": False, "start_in": None, "start_at": None}
    entity = make_binary(data)
    assert entity.is_on is False
    attrs = entity.extra_state_attributes
    assert attrs["minutes_until"] is None
    assert attrs["at"] is None


async def test_none_when_no_data(make_binary):
    entity = make_binary(None)
    assert entity.is_on is None
    assert entity.extra_state_attributes == {}


async def test_raw_forecast_exposed_by_default(make_binary):
    data = {"rain_within_2h": True, "start_in": 0, "start_at": None}
    samples = [{"lead": 0, "value": 1.0, "intensity": 12.0}]
    meta = {
        "rain_within_2h": ProductMetadata(
            source_product="RV", source_timestamp=None, samples=samples
        )
    }

    # The full 5-minute series is surfaced regardless of the diagnostic option.
    off = make_binary(data, metadata=meta, extra=False)
    assert off.extra_state_attributes["forecast_5min"] == samples

    on = make_binary(data, metadata=meta, extra=True)
    assert on.extra_state_attributes["forecast_5min"] == samples

    # forecast_5min is excluded from the recorder history.
    assert "forecast_5min" in DwdBinarySensorEntity._unrecorded_attributes


async def test_rain_events_live_on_their_own_sensor_not_the_flag(make_binary):
    events = {"schema": 1, "events": [], "last_ended": None}
    data = {"rain_within_2h": False, "start_in": None, "start_at": None, "rain_events": events}
    assert "rain_events" not in make_binary(data).extra_state_attributes
