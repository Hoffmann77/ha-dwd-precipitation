"""Integration tests — HA config flow."""

from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData

from custom_components.dwd_precipitation.config_flow import COVERAGE_LAT, COVERAGE_LON
from custom_components.dwd_precipitation.const import (
    CONF_COORDS,
    CONF_DRY_STREAK_SOURCE,
    DOMAIN,
    DRY_STREAK_SOURCE_RS,
    DRY_STREAK_SOURCE_RW,
)
from custom_components.dwd_precipitation.radar import OutsideGrid
from custom_components.dwd_precipitation.radar.odim import read_odim_grid

RS_FIXTURE = Path(__file__).parents[1] / "fixtures" / "composite_rs_sample.hd5"


# ---------------------------------------------------------------------------
# Config flow fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Prevent live DWD fetches during config flow tests."""
    with patch(
        "custom_components.dwd_precipitation.async_setup_entry",
        return_value=True,
    ) as mock_entry:
        yield mock_entry


# ===========================================================================
# Config flow
# ===========================================================================

async def test_flow_init_shows_form(hass: HomeAssistant) -> None:
    """Starting the config flow shows the user step form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_flow_valid_name_and_coords_creates_entry(hass: HomeAssistant) -> None:
    """Submitting valid name + coordinates creates a config entry with lat/lon."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "My DWD Station",
            CONF_COORDS: {"latitude": 51.5, "longitude": 9.9},
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "My DWD Station"
    assert result["data"]["latitude"] == pytest.approx(51.5)
    assert result["data"]["longitude"] == pytest.approx(9.9)
    assert CONF_COORDS not in result["data"]


async def test_flow_blank_name_shows_invalid_name_error(hass: HomeAssistant) -> None:
    """Submitting a whitespace-only name returns the invalid_name error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "   ",
            CONF_COORDS: {"latitude": 51.5, "longitude": 9.9},
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_name"}


async def test_flow_default_location_values_creates_entry(hass: HomeAssistant) -> None:
    """Submitting with hass default lat/lon creates an entry with those values."""
    # The HA test harness defaults to a non-German location; point it at
    # Germany so the default coordinates fall within the covered grid.
    await hass.config.async_update(latitude=51.5, longitude=9.9)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": hass.config.location_name,
            CONF_COORDS: {
                "latitude": hass.config.latitude,
                "longitude": hass.config.longitude,
            },
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["latitude"] == pytest.approx(hass.config.latitude)
    assert result["data"]["longitude"] == pytest.approx(hass.config.longitude)


async def test_flow_out_of_range_coordinates_shows_error(hass: HomeAssistant) -> None:
    """Submitting coordinates outside the German grid returns an error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    # New York City — far outside the DWD RS composite grid.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "New York",
            CONF_COORDS: {"latitude": 40.7128, "longitude": -74.0060},
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "coordinates_out_of_range"}


def test_the_coverage_box_holds_the_whole_grid() -> None:
    """The setup check never turns away a location DWD's grid covers.

    Checked on a 0.05 degree mesh against the grid a real RS file describes.
    """
    grid = read_odim_grid(RS_FIXTURE)
    (lat_min, lat_max), (lon_min, lon_max) = COVERAGE_LAT, COVERAGE_LON
    for i in range(281):  # 44.0 .. 58.0 N
        for j in range(421):  # 0.0 .. 21.0 E
            lat, lon = 44.0 + i * 0.05, j * 0.05
            try:
                grid.cell(lat, lon)
            except OutsideGrid:
                continue
            assert lat_min <= lat <= lat_max and lon_min <= lon <= lon_max, (lat, lon)


async def test_flow_zero_coordinates_shows_error(hass: HomeAssistant) -> None:
    """Submitting lat=0.0, lon=0.0 (Null Island) returns the out-of-range error.

    Null Island is far outside the German grid, so it must be rejected. 0.0 is
    falsy in Python; this also guards against accidental truthiness checks on the
    coordinate values silently swallowing the submission before validation runs.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Null Island",
            CONF_COORDS: {"latitude": 0.0, "longitude": 0.0},
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "coordinates_out_of_range"}


async def test_new_entry_stores_the_default_dry_streak_source(
    hass: HomeAssistant,
) -> None:
    """A new install writes its source down instead of relying on the default."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "My DWD Station",
            CONF_COORDS: {"latitude": 51.5, "longitude": 9.9},
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].options == {CONF_DRY_STREAK_SOURCE: DRY_STREAK_SOURCE_RW}
    assert result["result"].minor_version == 2


# ===========================================================================
# Options flow
# ===========================================================================

def _schema_default(result, key: str):
    """Return the form default the options schema offers for key."""
    marker = next(m for m in result["data_schema"].schema if m == key)
    return marker.default()


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({}, DRY_STREAK_SOURCE_RW),
        ({CONF_DRY_STREAK_SOURCE: DRY_STREAK_SOURCE_RS}, DRY_STREAK_SOURCE_RS),
    ],
)
async def test_options_form_offers_the_dry_streak_source(
    make_entry,
    hass: HomeAssistant, options: dict, expected: str
) -> None:
    """The form shows the entry's own source, defaulting to RW."""
    entry = make_entry(options, minor_version=2)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert _schema_default(result, CONF_DRY_STREAK_SOURCE) == expected


async def test_options_flow_saves_the_dry_streak_source(make_entry, hass: HomeAssistant) -> None:
    """Saving rs round-trips into the entry options."""
    entry = make_entry({CONF_DRY_STREAK_SOURCE: DRY_STREAK_SOURCE_RW}, minor_version=2)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_DRY_STREAK_SOURCE: DRY_STREAK_SOURCE_RS, "advanced_options": {}},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DRY_STREAK_SOURCE] == DRY_STREAK_SOURCE_RS


async def test_options_flow_rejects_an_unknown_dry_streak_source(
    make_entry,
    hass: HomeAssistant,
) -> None:
    """Only the two product keys are accepted."""
    entry = make_entry(minor_version=2)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={CONF_DRY_STREAK_SOURCE: "sf", "advanced_options": {}},
        )


ADVANCED = (
    "rain_events",
    "rain_event_threshold",
    "precipitation_end_algorithm",
    "full_rolling_series",
    "unavailable_when_stale",
)


def _section(result):
    marker = next(m for m in result["data_schema"].schema if m == "advanced_options")
    return result["data_schema"].schema[marker]


async def test_advanced_options_are_a_collapsed_section(make_entry, hass: HomeAssistant) -> None:
    """The rarely needed options sit in a collapsed section with flat defaults."""
    entry = make_entry({"full_rolling_series": True, "rain_event_threshold": 0.4}, minor_version=2)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    advanced = _section(result)

    assert advanced.options["collapsed"] is True
    inner = {str(m): m.default() for m in advanced.schema.schema}
    assert tuple(inner) == ADVANCED
    assert inner["full_rolling_series"] is True
    assert inner["rain_event_threshold"] == 0.4
    assert inner["unavailable_when_stale"] is True
    assert inner["rain_events"] is False
    main = {str(m) for m in result["data_schema"].schema}
    assert main.isdisjoint(ADVANCED)


async def test_advanced_options_are_stored_flat(make_entry, hass: HomeAssistant) -> None:
    """Saving flattens the section, so every option keeps its key."""
    entry = make_entry({CONF_DRY_STREAK_SOURCE: DRY_STREAK_SOURCE_RS}, minor_version=2)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_DRY_STREAK_SOURCE: DRY_STREAK_SOURCE_RS,
            "advanced_options": {
                "rain_event_threshold": 0.6,
                "full_rolling_series": True,
            },
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "advanced_options" not in entry.options
    assert entry.options["rain_event_threshold"] == 0.6
    assert entry.options["full_rolling_series"] is True
    assert entry.options["unavailable_when_stale"] is True  # its default
    assert entry.options[CONF_DRY_STREAK_SOURCE] == DRY_STREAK_SOURCE_RS
