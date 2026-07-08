"""Integration tests — HA config flow."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.dwd_precipitation.const import CONF_COORDS, DOMAIN


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
