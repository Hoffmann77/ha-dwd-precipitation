"""Rain warnings: the subentry flow, their entities, and their lifecycle."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.dwd_precipitation.const import DOMAIN, SUBENTRY_RAIN_WARNING
from custom_components.dwd_precipitation.options import (
    DEFAULT_RAIN_WARNING,
    rain_warning_rule,
)
from custom_components.dwd_precipitation.radar.rain_warning import WarningRule
from custom_components.dwd_precipitation.rain_events_tracker import RainEventsTracker
from tests.entity_ids import RAIN_WARNING_IDS, RELEASED_2026_10_0_IDS
from tests.integration.test_setup_entry import _patched_products

LAUNDRY = "sub_laundry"
WINDOWS = "sub_windows"


def _warning(subentry_id: str, title: str, **data) -> dict:
    """Return the stored form of a rain-warning subentry."""
    return {
        "subentry_id": subentry_id,
        "subentry_type": SUBENTRY_RAIN_WARNING,
        "title": title,
        "data": {"lead_time": 30, "combine": "any", **data},
        "unique_id": None,
    }


def _view(start_in_min: float, status: str = "upcoming", mm: float = 2.0) -> dict:
    """Return a rain-events view with one event starting that far from now."""
    start = dt_util.utcnow() + timedelta(minutes=start_in_min)
    return {
        "schema": 1,
        "base": dt_util.utcnow().isoformat(),
        "events": [
            {
                "id": "20250601t1200-0",
                "status": status,
                "start": start.isoformat(),
                "total": {
                    "mm": mm,
                    "peak_1h": {"mm": 1.5, "start": None, "end": None},
                    "peak_10min": {"mm": 0.6, "start": None, "end": None},
                },
                "absorbed": [],
            }
        ],
        "last_ended": None,
    }


async def _set_up(hass, make_entry, subentries, view=None, options=None):
    """Set up a "Home" entry with these warnings, the tracker returning ``view``."""
    entry = make_entry(options, subentries_data=subentries)
    tracker = AsyncMock(return_value=view)
    with _patched_products(), patch.object(RainEventsTracker, "async_track", new=tracker):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _entity_id(hass, entry, subentry_id: str, domain: str) -> str | None:
    suffix = "rain_warning" if domain == "binary_sensor" else "rain_warning_status"
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.entry_id}_{subentry_id}_{suffix}"
    )


def _device(hass, identifier: str):
    """Return the integration's device with this identifier, None if gone."""
    entry_id = identifier.split("_", 1)[0]
    return next(
        (
            device
            for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry_id)
            if (DOMAIN, identifier) in device.identifiers
        ),
        None,
    )


# ---------------------------------------------------------------------------
# Subentry data
# ---------------------------------------------------------------------------


def test_a_warning_without_data_gets_the_defaults() -> None:
    assert rain_warning_rule({}) == WarningRule(lead_time=30)
    assert set(DEFAULT_RAIN_WARNING) == set(WarningRule.__dataclass_fields__)


def test_stored_values_are_typed_and_an_unknown_combine_is_the_default() -> None:
    rule = rain_warning_rule({"lead_time": 45.0, "min_mm": 3, "combine": "most"})

    assert rule == WarningRule(lead_time=45, min_mm=3.0)
    assert isinstance(rule.lead_time, int)


# ---------------------------------------------------------------------------
# Subentry flow
# ---------------------------------------------------------------------------


async def _start(hass, entry, source=SOURCE_USER, subentry_id=None):
    context = {"source": source}
    if subentry_id is not None:
        context["subentry_id"] = subentry_id
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_RAIN_WARNING), context=context
    )


async def test_the_flow_creates_a_warning(make_entry, hass: HomeAssistant) -> None:
    entry = make_entry()

    result = await _start(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": " Laundry ", "lead_time": 60, "min_mm": 2.5, "combine": "all"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.subentry_type == SUBENTRY_RAIN_WARNING
    assert subentry.title == "Laundry"
    # Only the minimums that were set are stored.
    assert dict(subentry.data) == {"lead_time": 60, "combine": "all", "min_mm": 2.5}


async def test_the_flow_preselects_the_defaults(make_entry, hass: HomeAssistant) -> None:
    result = await _start(hass, make_entry())

    defaults = {
        str(key): key.default() for key in result["data_schema"].schema if callable(key.default)
    }
    assert defaults == {"lead_time": 30, "combine": "any"}


@pytest.mark.parametrize(
    ("name", "error"),
    [("  ", "invalid_name"), ("!!", "invalid_name"), ("laundry!", "name_already_exists")],
)
async def test_the_flow_rejects_a_bad_name(make_entry, hass: HomeAssistant, name, error) -> None:
    """Names are compared as entity ids would see them."""
    entry = make_entry(subentries_data=[_warning(LAUNDRY, "Laundry")])

    result = await _start(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": name, "lead_time": 30, "combine": "any"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert len(entry.subentries) == 1


async def test_reconfigure_changes_the_name_and_clears_a_minimum(
    make_entry, hass: HomeAssistant
) -> None:
    entry = make_entry(subentries_data=[_warning(LAUNDRY, "Laundry", min_mm=2.0)])

    result = await _start(hass, entry, SOURCE_RECONFIGURE, LAUNDRY)
    assert result["step_id"] == "reconfigure"
    suggested = {
        str(key): (key.description or {}).get("suggested_value")
        for key in result["data_schema"].schema
    }
    assert suggested["name"] == "Laundry"
    assert suggested["min_mm"] == 2.0

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Washing", "lead_time": 15, "combine": "any"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    subentry = entry.subentries[LAUNDRY]
    assert subentry.title == "Washing"
    assert dict(subentry.data) == {"lead_time": 15, "combine": "any"}


async def test_reconfigure_may_keep_its_own_name(make_entry, hass: HomeAssistant) -> None:
    entry = make_entry(
        subentries_data=[_warning(LAUNDRY, "Laundry"), _warning(WINDOWS, "Windows")]
    )

    result = await _start(hass, entry, SOURCE_RECONFIGURE, LAUNDRY)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Laundry", "lead_time": 45, "combine": "any"}
    )
    assert result["type"] is FlowResultType.ABORT

    result = await _start(hass, entry, SOURCE_RECONFIGURE, LAUNDRY)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Windows", "lead_time": 45, "combine": "any"}
    )
    assert result["errors"] == {"base": "name_already_exists"}


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


async def test_each_warning_is_a_device_with_two_entities(
    make_entry, hass: HomeAssistant, caplog
) -> None:
    entry = await _set_up(
        hass,
        make_entry,
        [_warning(LAUNDRY, "Laundry", lead_time=60), _warning(WINDOWS, "Windows", lead_time=15)],
        view=_view(40),
    )

    for sub, warning in ((LAUNDRY, "laundry"), (WINDOWS, "windows")):
        for domain, pattern in RAIN_WARNING_IDS.items():
            slug = pattern.format(warning=warning)
            assert _entity_id(hass, entry, sub, domain) == f"{domain}.home_{slug}"
            assert not any(released.endswith(slug) for released in RELEASED_2026_10_0_IDS.values())

    # Rain in 40 minutes: within Laundry's hour, beyond Windows' 15 minutes.
    laundry = hass.states.get("sensor.home_laundry_rain_warning_status")
    assert laundry.state == "soon"
    assert laundry.attributes["friendly_name"] == "Home Laundry Rain warning status"
    assert laundry.attributes["options"] == ["dry", "soon", "rain"]
    assert laundry.attributes["event_id"] == "20250601t1200-0"
    assert laundry.attributes["mm"] == 2.0
    assert laundry.attributes["peak_1h"] == 1.5
    assert laundry.attributes["peak_10min"] == 0.6
    assert laundry.attributes["type"] is None
    flag = hass.states.get("binary_sensor.home_laundry_rain_warning")
    assert flag.state == "on"
    assert flag.attributes["friendly_name"] == "Home Laundry Rain warning"
    # The details are on the status sensor only.
    assert "event_id" not in flag.attributes

    assert hass.states.get("sensor.home_windows_rain_warning_status").state == "dry"
    assert hass.states.get("binary_sensor.home_windows_rain_warning").state == "off"

    # Each warning is a device of its own in its subentry (HA keeps a device
    # in one subentry); the location's device stays in none.
    registry = er.async_get(hass)
    for sub, name in ((LAUNDRY, "Home Laundry"), (WINDOWS, "Home Windows")):
        device = _device(hass, f"{entry.entry_id}_{sub}")
        assert device.name == name
        assert device.config_subentry_id == sub
        for domain in ("sensor", "binary_sensor"):
            entity = registry.async_get(_entity_id(hass, entry, sub, domain))
            assert entity.device_id == device.id
            assert entity.config_subentry_id == sub
    location = _device(hass, entry.entry_id)
    assert location.config_subentry_id is None
    # Sharing the location's device would move it into a subentry, which HA
    # reports (and refuses from 2027.8).
    assert "different config subentry" not in caplog.text


async def test_ongoing_rain_is_rain(make_entry, hass: HomeAssistant) -> None:
    await _set_up(hass, make_entry, [_warning(LAUNDRY, "Laundry")], view=_view(-10, "ongoing"))

    assert hass.states.get("sensor.home_laundry_rain_warning_status").state == "rain"
    assert hass.states.get("binary_sensor.home_laundry_rain_warning").state == "on"


async def test_an_event_below_the_minimum_is_dry(make_entry, hass: HomeAssistant) -> None:
    await _set_up(
        hass, make_entry, [_warning(LAUNDRY, "Laundry", min_mm=5.0)], view=_view(-10, "ongoing")
    )

    state = hass.states.get("sensor.home_laundry_rain_warning_status")
    assert state.state == "dry"
    assert state.attributes["event_id"] is None


async def test_without_a_view_the_warning_is_unknown(make_entry, hass: HomeAssistant) -> None:
    """A tracker failure (or a fill still running) is not reported as dry."""
    await _set_up(hass, make_entry, [_warning(LAUNDRY, "Laundry")], view=None)

    assert hass.states.get("sensor.home_laundry_rain_warning_status").state == "unknown"
    assert hass.states.get("binary_sensor.home_laundry_rain_warning").state == "unknown"


# ---------------------------------------------------------------------------
# Tracker and lifecycle
# ---------------------------------------------------------------------------


async def test_a_warning_runs_the_tracker_without_the_rain_events_sensor(
    make_entry, hass: HomeAssistant
) -> None:
    entry = await _set_up(hass, make_entry, [_warning(LAUNDRY, "Laundry")], view=_view(40))

    assert entry.runtime_data.coordinators["rv"]._rain_tracker is not None
    assert (
        er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_radvor_rv_rain_events"
        )
        is None
    )


async def test_a_warning_keeps_the_tracker_store(make_entry, hass: HomeAssistant, hass_storage) -> None:
    """With the option off, the store is deleted only when no warning needs it."""
    entry = make_entry(subentries_data=[_warning(LAUNDRY, "Laundry")])
    key = f"dwd_precipitation.{entry.entry_id}.rain_events"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {}}

    with _patched_products(), patch.object(RainEventsTracker, "async_track", new=AsyncMock(return_value=None)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert key in hass_storage

        hass.config_entries.async_remove_subentry(entry, LAUNDRY)
        await hass.async_block_till_done()

    assert entry.runtime_data.coordinators["rv"]._rain_tracker is None
    assert key not in hass_storage


async def test_deleting_a_warning_removes_only_its_entities(
    make_entry, hass: HomeAssistant
) -> None:
    entry = await _set_up(
        hass,
        make_entry,
        [_warning(LAUNDRY, "Laundry"), _warning(WINDOWS, "Windows")],
        view=_view(40),
    )

    with _patched_products(), patch.object(RainEventsTracker, "async_track", new=AsyncMock(return_value=None)):
        hass.config_entries.async_remove_subentry(entry, LAUNDRY)
        await hass.async_block_till_done()

    assert _entity_id(hass, entry, LAUNDRY, "sensor") is None
    assert _entity_id(hass, entry, LAUNDRY, "binary_sensor") is None
    assert _entity_id(hass, entry, WINDOWS, "sensor") is not None
    # Its device goes with it; the location's device and entities stay.
    assert not _device(hass, f"{entry.entry_id}_{LAUNDRY}")
    assert _device(hass, entry.entry_id)
    assert hass.states.get("sensor.home_precipitation_last_60_min") is not None


async def test_adding_a_warning_reloads_the_entry(make_entry, hass: HomeAssistant) -> None:
    entry = await _set_up(hass, make_entry, [])

    tracker = AsyncMock(return_value=_view(10))
    with _patched_products(), patch.object(RainEventsTracker, "async_track", new=tracker):
        result = await _start(hass, entry)
        await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"name": "Laundry", "lead_time": 30, "combine": "any"}
        )
        await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.home_laundry_rain_warning").state == "on"


async def test_renaming_a_warning_keeps_its_entity_ids(make_entry, hass: HomeAssistant) -> None:
    entry = await _set_up(hass, make_entry, [_warning(LAUNDRY, "Laundry")], view=_view(10))

    tracker = AsyncMock(return_value=_view(10))
    with _patched_products(), patch.object(RainEventsTracker, "async_track", new=tracker):
        result = await _start(hass, entry, SOURCE_RECONFIGURE, LAUNDRY)
        await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"name": "Washing", "lead_time": 30, "combine": "any"}
        )
        await hass.async_block_till_done()

    device = _device(hass, f"{entry.entry_id}_{LAUNDRY}")
    assert device.name == "Home Washing"
    state = hass.states.get("sensor.home_laundry_rain_warning_status")
    assert state.attributes["friendly_name"] == "Home Washing Rain warning status"
    assert hass.states.get("binary_sensor.home_laundry_rain_warning").attributes[
        "friendly_name"
    ] == "Home Washing Rain warning"
