"""Config flow for the DWD Precipitation integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.const import CONF_NAME

from .const import (
    DOMAIN,
    CONF_COORDS,
    CONF_EXTRA_ATTRIBUTES,
    CONF_UNAVAILABLE_WHEN_STALE,
    CONF_RAIN_THRESHOLD,
    DEFAULT_RAIN_THRESHOLD,
)
from .radar import rs_grid_contains


_LOGGER = logging.getLogger(__name__)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for DWD Precipitation."""

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_EXTRA_ATTRIBUTES,
                    default=self.config_entry.options.get(CONF_EXTRA_ATTRIBUTES, False),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_UNAVAILABLE_WHEN_STALE,
                    default=self.config_entry.options.get(CONF_UNAVAILABLE_WHEN_STALE, True),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_RAIN_THRESHOLD,
                    default=self.config_entry.options.get(
                        CONF_RAIN_THRESHOLD, DEFAULT_RAIN_THRESHOLD
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        step=0.1,
                        unit_of_measurement="mm",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for DWD Precipitation."""

    VERSION = 1

    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlowHandler:
        """Return the options flow handler."""
        return OptionsFlowHandler()

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the user step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = user_input.copy()

            if not data[CONF_NAME].lstrip(" "):
                errors["base"] = "invalid_name"

            existing_names = {
                entry.title
                for entry in self.hass.config_entries.async_entries(DOMAIN)
            }
            if data[CONF_NAME] in existing_names:
                errors["base"] = "name_already_exists"

            coords = data.pop(CONF_COORDS)
            data["latitude"] = coords["latitude"]
            data["longitude"] = coords["longitude"]

            if not rs_grid_contains(data["latitude"], data["longitude"]):
                errors["base"] = "coordinates_out_of_range"

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
            vol.Required(
                CONF_COORDS,
                default={
                    "latitude": self.hass.config.latitude,
                    "longitude": self.hass.config.longitude,
                },
            ): selector.LocationSelector(selector.LocationSelectorConfig()),
        }

        return vol.Schema(schema)
