"""Config flow for the DWD Precipitation integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.const import CONF_NAME

from .const import DOMAIN, CONF_COORDS


_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for DWD Precipitation."""

    VERSION = 1

    MINOR_VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the user step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = user_input.copy()

            if not data[CONF_NAME].lstrip(" "):
                errors["base"] = "invalid_name"

            coords = data.pop(CONF_COORDS)
            data["latitude"] = coords["latitude"]
            data["longitude"] = coords["longitude"]

            if not errors:
                return self.async_create_entry(
                    title=data[CONF_NAME],
                    data=data,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.get_shema_user_step(),
            errors=errors,
        )

    @callback
    def get_shema_user_step(self) -> vol.Schema:
        """Return the schema for the user step."""
        schema = {
            vol.Required(
                CONF_NAME, default=self.hass.config.location_name
            ): str,
            vol.Optional(CONF_COORDS): selector.LocationSelector(
                selector.LocationSelectorConfig(),
            ),
        }

        return vol.Schema(schema)