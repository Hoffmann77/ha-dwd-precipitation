"""Sensor extra_state_attributes / native_value tests.

Entities are built by their constructors on coordinators from the
make_coordinator factory, holding the data a test is about; they are not
added to hass.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

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
from custom_components.dwd_precipitation.products import (
    RadolanRW,
    RadolanRW10,
    RadvorRS,
    RadvorRV,
)
from custom_components.dwd_precipitation.coordinator import (
    CoordinatorData,
    ProductMetadata,
)
from custom_components.dwd_precipitation.dry_streak import (
    DryStreakExtraData,
    downtime_correction,
    fresh_anchor,
    NO_READING,
    Reading,
    amount_reading,
    release_reading,
    unwatched_hours,
)
from custom_components.dwd_precipitation.release_grid import ReleaseGrid
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
    assert amount_reading(None) == NO_READING
    assert amount_reading(SimpleNamespace(data=None)) == NO_READING
    empty = SimpleNamespace(data=CoordinatorData(data={"amount": None}, metadata={}))
    assert amount_reading(empty) == NO_READING


def test_amount_reading_returns_the_amount_and_its_window():
    start = datetime(2026, 7, 3, 10, 0, tzinfo=UTC)
    end = datetime(2026, 7, 3, 11, 0, tzinfo=UTC)
    meta = ProductMetadata(
        source_product="RW", source_timestamp=end, data_start=start, data_end=end
    )
    rw = SimpleNamespace(data=CoordinatorData(data={"amount": 3.2}, metadata={"amount": meta}))
    assert amount_reading(rw) == Reading(3.2, start, end)


def test_downtime_correction_rw_rain_resets():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    rw_end = datetime(2026, 7, 3, 11, 50, tzinfo=UTC)
    rw = Reading(2.0, datetime(2026, 7, 3, 10, 50, tzinfo=UTC), rw_end)
    sf = Reading(5.0, datetime(2026, 7, 2, 11, 50, tzinfo=UTC), rw_end)
    assert downtime_correction(1.0, rw, sf, now) == rw_end


def test_downtime_correction_sf_only_caps_at_window_start():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    sf_start = datetime(2026, 7, 2, 11, 50, tzinfo=UTC)
    rw = Reading(0.0, datetime(2026, 7, 3, 10, 50, tzinfo=UTC), now)
    sf = Reading(5.0, sf_start, now)
    assert downtime_correction(1.0, rw, sf, now) == sf_start


def test_downtime_correction_no_rain_returns_none():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    rw = Reading(0.0, now, now)
    sf = Reading(0.1, now, now)
    assert downtime_correction(1.0, rw, sf, now) is None


def test_fresh_anchor_prefers_sf_dry_window():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    sf_start = datetime(2026, 7, 2, 11, 50, tzinfo=UTC)
    rw_start = datetime(2026, 7, 3, 10, 50, tzinfo=UTC)
    rw = Reading(0.0, rw_start, now)
    sf = Reading(0.0, sf_start, now)
    assert fresh_anchor(1.0, rw, sf, now) == sf_start


def test_fresh_anchor_falls_back_to_now_when_recently_wet():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    rw = Reading(5.0, datetime(2026, 7, 3, 10, 50, tzinfo=UTC), now)
    sf = Reading(5.0, datetime(2026, 7, 2, 11, 50, tzinfo=UTC), now)
    assert fresh_anchor(1.0, rw, sf, now) == now


def test_dry_streak_extra_data_roundtrip():
    anchor = datetime(2026, 7, 1, 8, 30, tzinfo=UTC)
    watched = datetime(2026, 7, 3, 11, 35, tzinfo=UTC)
    hours = [datetime(2026, 7, 3, h, tzinfo=UTC) for h in (12, 13)]
    restored = DryStreakExtraData.from_dict(
        DryStreakExtraData(anchor, watched, hours).as_dict()
    )
    assert restored == DryStreakExtraData(anchor, watched, hours)
    assert DryStreakExtraData.from_dict({"dry_since": None}).dry_since is None


def test_dry_streak_extra_data_from_before_the_gap_check():
    """Stored before 2026.11.0: only the anchor, so nothing is watched yet."""
    restored = DryStreakExtraData.from_dict({"dry_since": "2026-07-01T08:30:00+00:00"})
    assert restored.watched_until is None
    assert restored.gap_hours == []


# --- gaps in the source ------------------------------------------------------

RW_GRID = ReleaseGrid(RadolanRW.RELEASE_INTERVAL, RadolanRW.RELEASE_OFFSET)
# The 2026-10-13 Proetzel outage (#109): RS had no data for Berlin after 11:35.
LAST_SEEN = datetime(2026, 10, 13, 11, 35, tzinfo=UTC)
BACK = datetime(2026, 10, 13, 17, 40, tzinfo=UTC)
GAP_HOURS = [datetime(2026, 10, 13, h, tzinfo=UTC) for h in range(12, 18)]


def _rw_release(value, hour):
    """An RW release as async_fetch_release returns it: the clock hour to ``hour``."""
    meta = ProductMetadata(
        "RW", hour, data_start=hour - timedelta(hours=1), data_end=hour
    )
    return CoordinatorData({KEY_AMOUNT: value}, {KEY_AMOUNT: meta})


@pytest.mark.parametrize(
    ("watched_until", "reading_end", "hours"),
    [
        # The new reading's hour reaches back to what was watched: no gap.
        (LAST_SEEN, LAST_SEEN + timedelta(minutes=5), []),
        (LAST_SEEN, LAST_SEEN + timedelta(hours=1), []),
        # Every clock hour overlapping 11:35-16:40, the stretch nobody watched.
        (LAST_SEEN, BACK, GAP_HOURS),
        # A gap from an hour's end starts with the next hour.
        (
            datetime(2026, 10, 13, 12, tzinfo=UTC),
            datetime(2026, 10, 13, 14, 30, tzinfo=UTC),
            [datetime(2026, 10, 13, h, tzinfo=UTC) for h in (13, 14)],
        ),
    ],
    ids=["5_min", "one_hour", "proetzel", "from_the_hour"],
)
def test_unwatched_hours(watched_until, reading_end, hours):
    assert unwatched_hours(RW_GRID, watched_until, reading_end) == hours


def test_release_reading_returns_the_amount_and_its_window():
    hour = datetime(2026, 10, 13, 13, tzinfo=UTC)
    assert release_reading(_rw_release(2.5, hour)) == Reading(
        2.5, hour - timedelta(hours=1), hour
    )
    assert release_reading(CoordinatorData({KEY_AMOUNT: None}, {})) == NO_READING


@pytest.fixture
def make_gap_sensor(make_coordinator, freezer):
    """Return a factory: the RS dry streak with an RW coordinator for its gaps.

    The source last reported at LAST_SEEN; ``rw`` maps each RW hour to the
    amount its fetch returns (an exception to raise instead). The factory
    returns the sensor and the background tasks it starts, as coroutines a
    test awaits or closes. The clock stands where RW's 17:00 is out.
    """
    freezer.move_to(datetime(2026, 10, 13, 17, 45, tzinfo=UTC))

    def _make(*, rw=None, dry_since=datetime(2026, 10, 1, tzinfo=UTC), threshold=1.0):
        rs = make_coordinator(
            RadvorRS, {CONF_PRECIPITATION_RESET_THRESHOLD: threshold}
        )
        hourly = make_coordinator(RadolanRW, entry=rs.config_entry)
        rw = rw or {}

        async def _fetch(hour):
            value = rw.get(hour, 0.0)
            if isinstance(value, Exception):
                raise value
            return _rw_release(value, hour)

        hourly.async_fetch_release = AsyncMock(side_effect=_fetch)
        tasks: list = []
        rs.config_entry.async_create_background_task = (
            lambda _hass, coro, _name: tasks.append(coro)
        )
        sensor = TimespanWithoutPrecipitationSensor(rs, KEY_LAST_60, hourly=hourly)
        sensor.entity_id = "sensor.home_timespan_without_precipitation"
        sensor.async_write_ha_state = lambda: None
        sensor._dry_since = dry_since
        report(sensor, 0.0, LAST_SEEN)
        return sensor, tasks

    return _make


def report(sensor, value, release):
    """Hand the sensor an RS update: ``value`` mm in the hour to ``release``."""
    meta = ProductMetadata("RS", release, lead_time_minutes=0)
    sensor.coordinator.data = CoordinatorData(
        {KEY_LAST_60: value}, {KEY_LAST_60: meta}
    )
    sensor._process()


def _fetched(sensor) -> list[datetime]:
    return [c.args[0] for c in sensor._hourly.async_fetch_release.call_args_list]


def _close(tasks: list) -> None:
    """Close coroutines a test inspected but did not run."""
    for coro in tasks:
        coro.close()


async def test_continuous_readings_never_fetch_rw(make_gap_sensor):
    sensor, tasks = make_gap_sensor()
    for minutes in range(5, 125, 5):
        report(sensor, 0.0, LAST_SEEN + timedelta(minutes=minutes))

    assert tasks == []
    assert sensor._gap_hours == []
    assert _anchor(sensor) == datetime(2026, 10, 1, tzinfo=UTC)


async def test_gap_shorter_than_the_hour_needs_no_rw(make_gap_sensor):
    sensor, tasks = make_gap_sensor()
    report(sensor, None, LAST_SEEN + timedelta(minutes=5))
    report(sensor, float("nan"), LAST_SEEN + timedelta(minutes=10))
    report(sensor, 0.0, LAST_SEEN + timedelta(minutes=60))

    assert tasks == []


@pytest.mark.asyncio
async def test_rain_in_a_gap_resets_to_the_end_of_its_rw_hour(make_gap_sensor):
    """The issue's case: RS lost the cell for six hours while RW saw rain."""
    rain = datetime(2026, 10, 13, 14, tzinfo=UTC)
    sensor, tasks = make_gap_sensor(rw={rain: 3.4, rain + timedelta(hours=1): 0.4})
    for minutes in range(5, 365, 5):  # no data from 11:40 to 17:35
        report(sensor, None, LAST_SEEN + timedelta(minutes=minutes))
    assert tasks == []

    report(sensor, 0.0, BACK)
    assert len(tasks) == 1
    await tasks[0]

    assert _fetched(sensor) == GAP_HOURS[::-1]  # newest first
    assert _anchor(sensor) == rain
    assert sensor._gap_hours == []
    assert sensor._filling is False


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [0.9, None, float("nan")])
async def test_dry_or_missing_rw_leaves_the_anchor(make_gap_sensor, value):
    sensor, tasks = make_gap_sensor(rw=dict.fromkeys(GAP_HOURS, value))
    report(sensor, 0.0, BACK)
    await tasks[0]

    assert _anchor(sensor) == datetime(2026, 10, 1, tzinfo=UTC)
    # Done either way: an hour without data for the cell is not refetched.
    assert sensor._gap_hours == []


@pytest.mark.asyncio
async def test_rw_never_moves_the_anchor_back(make_gap_sensor):
    sensor, tasks = make_gap_sensor(rw={GAP_HOURS[0]: 5.0})
    report(sensor, 2.0, BACK)  # the reading itself resets to 17:40
    await tasks[0]

    assert _anchor(sensor) == BACK


@pytest.mark.asyncio
async def test_failed_fetch_ends_the_round_and_waits_for_a_new_reading(make_gap_sensor):
    sensor, tasks = make_gap_sensor(rw={GAP_HOURS[-2]: OSError("DWD down")})
    report(sensor, 0.0, BACK)
    await tasks[0]

    # One failure ends the round: the rest are kept, nothing more is asked.
    assert _fetched(sensor) == GAP_HOURS[:-3:-1]
    assert sensor._gap_hours == GAP_HOURS[:-1]
    assert sensor.extra_restore_state_data.gap_hours == GAP_HOURS[:-1]

    # A coordinator update without a new reading retries nothing...
    report(sensor, 0.0, BACK)
    assert len(tasks) == 1

    # ...the next reading does.
    sensor._hourly.async_fetch_release.side_effect = None
    sensor._hourly.async_fetch_release.return_value = _rw_release(0.0, BACK)
    report(sensor, 0.0, BACK + timedelta(minutes=5))
    assert len(tasks) == 2
    await tasks[1]
    assert sensor._gap_hours == []


@pytest.mark.asyncio
async def test_unreleased_rw_hour_waits_for_a_later_reading(make_gap_sensor, freezer):
    # 17:20: RW's 17:00 is not out until about 17:28.
    freezer.move_to(datetime(2026, 10, 13, 17, 20, tzinfo=UTC))
    sensor, tasks = make_gap_sensor()
    report(sensor, 0.0, datetime(2026, 10, 13, 17, 15, tzinfo=UTC))
    await tasks[0]

    assert _fetched(sensor) == GAP_HOURS[-2::-1]
    assert sensor._gap_hours == GAP_HOURS[-1:]

    freezer.move_to(datetime(2026, 10, 13, 17, 35, tzinfo=UTC))
    report(sensor, 0.0, datetime(2026, 10, 13, 17, 30, tzinfo=UTC))
    await tasks[1]
    assert _fetched(sensor)[-1] == GAP_HOURS[-1]
    assert sensor._gap_hours == []


@pytest.mark.asyncio
async def test_hour_gone_at_the_old_end_does_not_hold_up_the_rest(make_gap_sensor):
    """DWD may delete the oldest hour minutes before the window moves on."""
    sensor, tasks = make_gap_sensor(
        rw={GAP_HOURS[0]: OSError("404"), GAP_HOURS[1]: 2.0}
    )
    report(sensor, 0.0, BACK)
    await tasks[0]

    assert _anchor(sensor) == GAP_HOURS[1]
    assert sensor._gap_hours == GAP_HOURS[:1]


async def test_only_one_gap_check_runs_at_a_time(make_gap_sensor):
    sensor, tasks = make_gap_sensor()
    report(sensor, 0.0, BACK)
    report(sensor, None, BACK + timedelta(minutes=5))
    report(sensor, 0.0, BACK + timedelta(hours=2))

    # The second gap joins the list the running round works through.
    assert len(tasks) == 1
    assert sensor._gap_hours == GAP_HOURS + [
        datetime(2026, 10, 13, h, tzinfo=UTC) for h in (18, 19)
    ]
    _close(tasks)


async def test_gap_older_than_rw_on_opendata_is_given_up(make_gap_sensor, caplog):
    sensor, tasks = make_gap_sensor()
    sensor._watched_until = LAST_SEEN - timedelta(days=3)
    report(sensor, 0.0, BACK)

    # The latest RW hour and the 47 before it are fetched, as for the total;
    # the older ones are logged once.
    assert sensor._gap_hours[0] == datetime(2026, 10, 11, 18, tzinfo=UTC)
    assert sensor._gap_hours[-1] == datetime(2026, 10, 13, 17, tzinfo=UTC)
    assert len(sensor._gap_hours) == 48
    assert "while DWD still served them" in caplog.text
    _close(tasks)


async def test_without_rw_a_gap_is_only_recorded(make_days_sensor):
    """No RW coordinator to fill from: the reading is still processed."""
    sensor = make_days_sensor(
        dry_since=datetime(2026, 10, 1, tzinfo=UTC),
        value=0.0,
        meta=ProductMetadata("RS", BACK),
    )
    sensor._watched_until = LAST_SEEN
    sensor._process()

    assert sensor._watched_until == BACK
    assert sensor._gap_hours == []


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
