"""Integration tests — HA config flow and live DWD data fetch."""

import io
from unittest.mock import patch

import numpy as np
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.dwd_precipitation.const import CONF_COORDS, DOMAIN
from radar.odim import read_odim_composite


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


async def test_flow_zero_coordinates_creates_entry(hass: HomeAssistant) -> None:
    """Submitting lat=0.0, lon=0.0 (Null Island) creates an entry without errors.

    0.0 is falsy in Python; this guards against accidental truthiness checks
    on the coordinate values silently swallowing the submission.
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

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["latitude"] == pytest.approx(0.0)
    assert result["data"]["longitude"] == pytest.approx(0.0)


# ===========================================================================
# Live DWD fetch
# ===========================================================================

@pytest.mark.integration
def test_live_rs_file():
    """Download the current RS tar and verify our parser handles a real DWD file."""
    import tarfile
    from datetime import datetime, timedelta, timezone

    import requests

    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    ts  = now.replace(second=0, microsecond=0)
    ts -= timedelta(minutes=ts.minute % 5)
    fname = f"composite_rs_{ts.strftime('%Y%m%d_%H%M')}"
    url   = f"https://opendata.dwd.de/weather/radar/composite/rs/{fname}.tar"

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    with tarfile.open(fileobj=io.BytesIO(resp.content)) as tf:
        hdf5_bytes = tf.extractfile(f"{fname}_000-hd5").read()

    data, where = read_odim_composite(io.BytesIO(hdf5_bytes))

    assert data.shape == (1200, 1100)
    assert data.dtype == np.float32
    assert "xscale" in where
    assert "yscale" in where
