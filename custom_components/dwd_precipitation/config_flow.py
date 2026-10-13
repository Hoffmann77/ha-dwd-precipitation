"""Config flow for the DWD Precipitation integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult, section
from homeassistant.helpers import selector
from homeassistant.const import CONF_NAME

from .const import (
    DOMAIN,
    CONF_COORDS,
    CONF_EXTRA_ATTRIBUTES,
    DEFAULT_EXTRA_ATTRIBUTES,
    CONF_UNAVAILABLE_WHEN_STALE,
    DEFAULT_UNAVAILABLE_WHEN_STALE,
    CONF_PRECIPITATION_THRESHOLD,
    DEFAULT_PRECIPITATION_THRESHOLD,
    CONF_START_END_MODE,
    DEFAULT_START_END_MODE,
    START_END_MODE_TIMESTAMP,
    START_END_MODE_DURATION,
    CONF_PRECIPITATION_END_ALGORITHM,
    DEFAULT_PRECIPITATION_END_ALGORITHM,
    RAIN_END_ALGO_EPISODE,
    RAIN_END_ALGO_CLEARING,
    CONF_PRECIPITATION_RESET_THRESHOLD,
    DEFAULT_PRECIPITATION_RESET_THRESHOLD,
    CONF_DRY_STREAK_SOURCE,
    DEFAULT_DRY_STREAK_SOURCE,
    DRY_STREAK_SOURCES,
    CONF_FULL_ROLLING_SERIES,
    DEFAULT_FULL_ROLLING_SERIES,
    CONF_RAIN_EVENTS,
    DEFAULT_RAIN_EVENTS,
    CONF_RAIN_EVENT_THRESHOLD,
    DEFAULT_RAIN_EVENT_THRESHOLD,
)
from .radar import rs_grid_contains

# The collapsed part of the options form. Only the form is nested: its values
# are stored flat with the others (see OptionsFlowHandler.async_step_init).
SECTION_ADVANCED = "advanced_options"


_LOGGER = logging.getLogger(__name__)


def _number(unit: str) -> selector.NumberSelector:
    """Return a non-negative number box in steps of 0.1 ``unit``."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, step=0.1, unit_of_measurement=unit, mode=selector.NumberSelectorMode.BOX
        )
    )


def _dropdown(options: list[str], translation_key: str) -> selector.SelectSelector:
    """Return a dropdown of ``options``, labelled by ``translation_key``."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            translation_key=translation_key,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for DWD Precipitation."""

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Manage the options.

        The form nests the rarely needed options in a collapsed section, but
        they are stored flat like the rest: every option keeps its key, so
        nothing reading ``entry.options`` notices the section and no
        migration is needed.
        """
        if user_input is not None:
            data = {k: v for k, v in user_input.items() if k != SECTION_ADVANCED}
            data.update(user_input.get(SECTION_ADVANCED, {}))
            return self.async_create_entry(title="", data=data)

        options = self.config_entry.options

        def current(key: str, default) -> vol.Optional:
            """An optional field that shows the entry's value, else the default."""
            return vol.Optional(key, default=options.get(key, default))

        advanced = vol.Schema(
            {
                current(CONF_RAIN_EVENTS, DEFAULT_RAIN_EVENTS): selector.BooleanSelector(),
                current(CONF_RAIN_EVENT_THRESHOLD, DEFAULT_RAIN_EVENT_THRESHOLD): _number(
                    "mm/h"
                ),
                current(
                    CONF_PRECIPITATION_END_ALGORITHM, DEFAULT_PRECIPITATION_END_ALGORITHM
                ): _dropdown(
                    [RAIN_END_ALGO_EPISODE, RAIN_END_ALGO_CLEARING],
                    CONF_PRECIPITATION_END_ALGORITHM,
                ),
                current(
                    CONF_FULL_ROLLING_SERIES, DEFAULT_FULL_ROLLING_SERIES
                ): selector.BooleanSelector(),
                current(
                    CONF_UNAVAILABLE_WHEN_STALE, DEFAULT_UNAVAILABLE_WHEN_STALE
                ): selector.BooleanSelector(),
            }
        )
        schema = vol.Schema(
            {
                current(
                    CONF_EXTRA_ATTRIBUTES, DEFAULT_EXTRA_ATTRIBUTES
                ): selector.BooleanSelector(),
                current(
                    CONF_PRECIPITATION_THRESHOLD, DEFAULT_PRECIPITATION_THRESHOLD
                ): _number("mm/h"),
                current(CONF_START_END_MODE, DEFAULT_START_END_MODE): _dropdown(
                    [START_END_MODE_TIMESTAMP, START_END_MODE_DURATION],
                    CONF_START_END_MODE,
                ),
                current(
                    CONF_PRECIPITATION_RESET_THRESHOLD, DEFAULT_PRECIPITATION_RESET_THRESHOLD
                ): _number("mm"),
                current(CONF_DRY_STREAK_SOURCE, DEFAULT_DRY_STREAK_SOURCE): _dropdown(
                    list(DRY_STREAK_SOURCES), CONF_DRY_STREAK_SOURCE
                ),
                vol.Required(SECTION_ADVANCED): section(advanced, {"collapsed": True}),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for DWD Precipitation."""

    VERSION = 1

    # 1.2: options carry CONF_DRY_STREAK_SOURCE (see async_migrate_entry).
    MINOR_VERSION = 2

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
                # Store the source explicitly rather than leaving it to the
                # read-time default, so a later change of the default never
                # moves an existing install.
                return self.async_create_entry(
                    title=data[CONF_NAME],
                    data=data,
                    options={CONF_DRY_STREAK_SOURCE: DEFAULT_DRY_STREAK_SOURCE},
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
