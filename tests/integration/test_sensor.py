"""Sensor extra_state_attributes / native_value tests.

Entities are built by their constructors on coordinators from the
make_coordinator factory, holding the data a test is about; they are not
added to hass.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

import pytest

from custom_components.dwd_precipitation import sensor as sensor_module
from custom_components.dwd_precipitation.const import (
    CONF_EXTRA_ATTRIBUTES,
    KEY_AMOUNT,
    KEY_LAST_60,
    CONF_PRECIPITATION_RESET_THRESHOLD,
    DRY_STREAK_SOURCE_RS,
    DRY_STREAK_SOURCE_RW,
    START_END_MODE_DURATION,
    START_END_MODE_TIMESTAMP,
)
from custom_components.dwd_precipitation.coordinator import BaseProductUpdateCoordinator
from custom_components.dwd_precipitation.products import RadolanRW10, RadvorRS, RadvorRV
from custom_components.dwd_precipitation.coordinator import (
    CoordinatorData,
    ProductMetadata,
)
from custom_components.dwd_precipitation.dry_streak import (
    DryStreakExtraData,
    downtime_correction,
    fresh_anchor,
    amount_reading,
)
from homeassistant.components.sensor import SensorDeviceClass
from custom_components.dwd_precipitation.sensor import (
    RADVOR_RV_SENSORS,
    TimespanWithoutPrecipitationSensor,
    PrecipitationSensorEntity,
    PrecipitationSensorEntityDescription,
    _rv_timing_sensors,
)

UTC = timezone.utc

PEAK_HOUR = next(d for d in RADVOR_RV_SENSORS if d.key == "radvor_peak_1h_120")


_PLAIN = PrecipitationSensorEntityDescription(key="k", product_key="rs", sub_key="k")
_PRODUCTS = {"rs": RadvorRS, "rv": RadvorRV}


@pytest.fixture
def make_sensor(make_coordinator):
    """Return a factory: a sensor for ``description`` on a coordinator holding ``data``."""

    def _make(description, data, metadata=None, extra=False) -> PrecipitationSensorEntity:
        coordinator = make_coordinator(
            _PRODUCTS[description.product_key],
            {CONF_EXTRA_ATTRIBUTES: extra},
            data=CoordinatorData(data=data, metadata=metadata or {}),
        )
        return PrecipitationSensorEntity(coordinator, description)

    return _make


def _rv_timing_data():
    return {
        "start_in": 25,
        "start_at": datetime(2026, 7, 16, 20, 55, tzinfo=UTC),
        "end_in": 60,
        "end_at": datetime(2026, 7, 16, 21, 30, tzinfo=UTC),
    }


async def test_extra_attrs_disabled_returns_empty(make_sensor):
    meta = ProductMetadata(
        source_product="RS", source_timestamp=datetime(2026, 5, 18, 16, tzinfo=UTC),
    )
    assert make_sensor(_PLAIN, {"k": 1.0}, {"k": meta}, extra=False).extra_state_attributes == {}


async def test_extra_attrs_includes_window_when_present(make_sensor):
    meta = ProductMetadata(
        source_product="RS",
        source_timestamp=datetime(2026, 5, 18, 16, tzinfo=UTC),
        lead_time_minutes=60,
        data_start=datetime(2026, 5, 18, 16, tzinfo=UTC),
        data_end=datetime(2026, 5, 18, 17, tzinfo=UTC),
    )
    attrs = make_sensor(_PLAIN, {"k": 1.0}, {"k": meta}, extra=True).extra_state_attributes
    assert attrs["source_product"] == "RS"
    assert attrs["source_timestamp"] == "2026-05-18T16:00:00+00:00"
    assert attrs["lead_time_minutes"] == 60
    assert attrs["data_start"] == "2026-05-18T16:00:00+00:00"
    assert attrs["data_end"] == "2026-05-18T17:00:00+00:00"


async def test_extra_attrs_omits_window_when_absent(make_sensor):
    meta = ProductMetadata(
        source_product="RW", source_timestamp=datetime(2025, 6, 1, 12, 50, tzinfo=UTC),
    )
    attrs = make_sensor(_PLAIN, {"k": 1.0}, {"k": meta}, extra=True).extra_state_attributes
    assert "data_start" not in attrs
    assert "data_end" not in attrs
    assert attrs["source_timestamp"] == "2025-06-01T12:50:00+00:00"


async def test_native_value_is_the_sub_keys_value(make_sensor):
    meta = ProductMetadata(source_product="RS", source_timestamp=None)
    assert make_sensor(_PLAIN, {"k": 2.5}, {"k": meta}).native_value == 2.5


# ===========================================================================
# TimespanWithoutPrecipitationSensor
# ===========================================================================

@pytest.fixture
def make_days_sensor(make_coordinator):
    """Return a factory: the dry-streak sensor on its source's coordinator.

    ``value``/``meta`` are the source's past-hour total (none at all with
    ``empty``); ``dry_since`` is the anchor a restart would have restored,
    set directly because restoring needs the entity added to a running entry.
    """

    def _make(
        source="rs", *, value=None, meta=None, dry_since=None, threshold=1.0, empty=False
    ) -> TimespanWithoutPrecipitationSensor:
        cls, sub_key = {
            DRY_STREAK_SOURCE_RS: (RadvorRS, KEY_LAST_60),
            DRY_STREAK_SOURCE_RW: (RadolanRW10, KEY_AMOUNT),
        }[source]
        coordinator = make_coordinator(
            cls,
            {CONF_PRECIPITATION_RESET_THRESHOLD: threshold},
            data=None if empty else CoordinatorData({sub_key: value}, {sub_key: meta}),
        )
        sensor = TimespanWithoutPrecipitationSensor(coordinator, sub_key)
        sensor._dry_since = dry_since
        return sensor

    return _make


def _anchor(sensor: TimespanWithoutPrecipitationSensor) -> datetime | None:
    """The anchor the sensor would store."""
    return sensor.extra_restore_state_data.dry_since


async def test_days_value_and_hours(make_days_sensor, monkeypatch):
    anchor = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)  # 2.5 days / 60 h later
    monkeypatch.setattr(sensor_module.dt_util, "utcnow", lambda: now)

    sensor = make_days_sensor(dry_since=anchor)

    assert sensor.native_value == pytest.approx(2.5, abs=1e-6)
    attrs = sensor.extra_state_attributes
    assert attrs["hours_without_precipitation"] == pytest.approx(60.0)
    assert attrs["dry_since"] == anchor.isoformat()


@pytest.mark.parametrize("reportable", [True, False])
async def test_days_availability_follows_the_staleness_deadline(make_days_sensor, reportable):
    """One rule for every entity: the coordinator's data_is_reportable."""
    sensor = make_days_sensor(dry_since=datetime(2026, 7, 1, tzinfo=UTC))
    with patch.object(
        BaseProductUpdateCoordinator,
        "data_is_reportable",
        new_callable=PropertyMock,
        return_value=reportable,
    ):
        assert sensor.available is reportable


async def test_days_none_anchor_is_unknown(make_days_sensor):
    sensor = make_days_sensor(dry_since=None)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {"hours_without_precipitation": None}


async def test_days_future_anchor_clamped_to_zero(make_days_sensor, monkeypatch):
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(sensor_module.dt_util, "utcnow", lambda: now)
    sensor = make_days_sensor(dry_since=now + timedelta(hours=1))
    assert sensor.native_value == 0.0
    assert sensor.extra_state_attributes["hours_without_precipitation"] == 0.0


async def test_process_resets_anchor_when_raining(make_days_sensor):
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    meta = ProductMetadata(source_product="RS", source_timestamp=now)
    sensor = make_days_sensor(
        dry_since=datetime(2026, 7, 1, tzinfo=UTC), value=2.0, meta=meta, threshold=1.0
    )
    sensor._process()
    assert _anchor(sensor) == now


async def test_process_keeps_anchor_when_dry(make_days_sensor):
    old = datetime(2026, 7, 1, tzinfo=UTC)
    sensor = make_days_sensor(
        dry_since=old, value=0.2
    )
    sensor._process()
    assert _anchor(sensor) == old


async def test_process_ignores_missing_and_nan_reading(make_days_sensor):
    old = datetime(2026, 7, 1, tzinfo=UTC)
    for value in (None, float("nan")):
        sensor = make_days_sensor(dry_since=old, value=value)
        sensor._process()
        assert _anchor(sensor) == old


@pytest.mark.parametrize("value", [1.0, 4.2])  # at and above the threshold
async def test_process_rw_resets_anchor_to_end_of_the_hour(make_days_sensor, value):
    hour_end = datetime(2026, 7, 3, 11, 50, tzinfo=UTC)
    meta = ProductMetadata(source_product="RW", source_timestamp=hour_end)
    sensor = make_days_sensor(
        "rw", dry_since=datetime(2026, 7, 1, tzinfo=UTC), value=value, meta=meta
    )
    sensor._process()
    assert _anchor(sensor) == hour_end


@pytest.mark.parametrize("value", [0.9, None, float("nan")])
async def test_process_rw_keeps_anchor_when_dry_or_missing(make_days_sensor, value):
    old = datetime(2026, 7, 1, tzinfo=UTC)
    meta = ProductMetadata(
        source_product="RW", source_timestamp=datetime(2026, 7, 3, 11, 50, tzinfo=UTC)
    )
    sensor = make_days_sensor("rw", dry_since=old, value=value, meta=meta)
    sensor._process()
    assert _anchor(sensor) == old


async def test_process_rw_without_data_keeps_anchor(make_days_sensor):
    old = datetime(2026, 7, 1, tzinfo=UTC)
    sensor = make_days_sensor("rw", dry_since=old, empty=True)
    sensor._process()
    assert _anchor(sensor) == old


async def test_process_rw_first_observation_anchors_at_end_of_the_hour(make_days_sensor):
    hour_end = datetime(2026, 7, 3, 11, 50, tzinfo=UTC)
    meta = ProductMetadata(source_product="RW", source_timestamp=hour_end)
    sensor = make_days_sensor("rw", dry_since=None, value=0.0, meta=meta)
    sensor._process()
    assert _anchor(sensor) == hour_end


def test_amount_reading_handles_missing_data():
    assert amount_reading(None) == (None, None, None)
    assert amount_reading(SimpleNamespace(data=None)) == (None, None, None)
    empty = SimpleNamespace(data=CoordinatorData(data={"amount": None}, metadata={}))
    assert amount_reading(empty) == (None, None, None)


def test_amount_reading_returns_the_amount_and_its_window():
    start = datetime(2026, 7, 3, 10, 0, tzinfo=UTC)
    end = datetime(2026, 7, 3, 11, 0, tzinfo=UTC)
    meta = ProductMetadata(
        source_product="RW", source_timestamp=end, data_start=start, data_end=end
    )
    rw = SimpleNamespace(data=CoordinatorData(data={"amount": 3.2}, metadata={"amount": meta}))
    assert amount_reading(rw) == (3.2, start, end)


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


# --- merged start/end sensors ------------------------------------------

async def test_timestamp_mode_state_is_time_with_minutes_attribute(make_sensor):
    start, end = _rv_timing_sensors(START_END_MODE_TIMESTAMP)
    assert start.device_class is SensorDeviceClass.TIMESTAMP
    assert start.key == "radvor_rv_precipitation_start"
    assert end.key == "radvor_rv_precipitation_end"

    sensor = make_sensor(start, data=_rv_timing_data(), extra=False)
    assert sensor.native_value == datetime(2026, 7, 16, 20, 55, tzinfo=UTC)
    # Companion value is exposed even though diagnostic attributes are disabled.
    assert sensor.extra_state_attributes == {"minutes_until": 25}


async def test_duration_mode_state_is_minutes_with_time_attribute(make_sensor):
    start, _end = _rv_timing_sensors(START_END_MODE_DURATION)
    assert start.device_class is SensorDeviceClass.DURATION
    assert start.key == "radvor_rv_precipitation_start"

    sensor = make_sensor(start, data=_rv_timing_data(), extra=False)
    assert sensor.native_value == 25
    # The absolute time is serialized to an ISO string attribute.
    assert sensor.extra_state_attributes == {"at": "2026-07-16T20:55:00+00:00"}


def test_timing_keys_are_stable_across_modes():
    ts_keys = {d.key for d in _rv_timing_sensors(START_END_MODE_TIMESTAMP)}
    dur_keys = {d.key for d in _rv_timing_sensors(START_END_MODE_DURATION)}
    assert ts_keys == dur_keys == {
        "radvor_rv_precipitation_start",
        "radvor_rv_precipitation_end",
    }


def _peak_sensor(make_sensor, metadata, extra=False) -> PrecipitationSensorEntity:
    """The peak sensor on an RV coordinator holding ``metadata`` for it."""
    return make_sensor(PEAK_HOUR, data={"peak_1h": 6.5}, metadata={"peak_1h": metadata}, extra=extra)


def test_peak_hour_sensor_reads_rv_under_its_released_key():
    """RV feeds it, with or without the full rolling series option."""
    assert (PEAK_HOUR.product_key, PEAK_HOUR.sub_key) == ("rv", "peak_1h")
    assert PEAK_HOUR.key == "radvor_peak_1h_120"


async def test_peak_hour_sensor_always_exposes_window_and_series(make_sensor):
    series = [{"lead": 90, "start": None, "end": None, "value": 6.5}]
    meta = ProductMetadata(
        source_product="RV",
        source_timestamp=datetime(2026, 5, 18, 16, 0, tzinfo=UTC),
        lead_time_minutes=90,
        data_start=datetime(2026, 5, 18, 16, 30, tzinfo=UTC),
        data_end=datetime(2026, 5, 18, 17, 30, tzinfo=UTC),
        rolling_1h=series,
    )
    sensor = _peak_sensor(make_sensor, meta)
    assert sensor.native_value == 6.5
    assert sensor.extra_state_attributes == {
        "window_start": "2026-05-18T16:30:00+00:00",
        "window_end": "2026-05-18T17:30:00+00:00",
        "forecast_rolling_1h": series,
    }
    # The series is kept out of the recorder, like the RV 5-minute one, and
    # so is the window, which moves with every release.
    assert {"forecast_rolling_1h", "window_start", "window_end"} <= (
        PrecipitationSensorEntity._unrecorded_attributes
    )


async def test_peak_hour_sensor_dry_forecast_has_null_window(make_sensor):
    meta = ProductMetadata(
        source_product="RV", source_timestamp=None, rolling_1h=[],
    )
    attrs = _peak_sensor(make_sensor, meta).extra_state_attributes
    assert attrs["window_start"] is None
    assert attrs["window_end"] is None
