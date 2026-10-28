"""Config flow for the DWD Precipitation integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.const import CONF_NAME
from homeassistant.util import slugify

from .const import (
    DOMAIN,
    DOCS_URL,
    CONF_COORDS,
    CONF_EXTRA_ATTRIBUTES,
    CONF_UNAVAILABLE_WHEN_STALE,
    CONF_PRECIPITATION_THRESHOLD,
    CONF_START_END_MODE,
    START_END_MODE_TIMESTAMP,
    START_END_MODE_DURATION,
    CONF_PRECIPITATION_END_ALGORITHM,
    RAIN_END_ALGO_EPISODE,
    RAIN_END_ALGO_CLEARING,
    CONF_PRECIPITATION_RESET_THRESHOLD,
    CONF_DRY_STREAK_SOURCE,
    DEFAULT_DRY_STREAK_SOURCE,
    DRY_STREAK_SOURCES,
    CONF_FULL_ROLLING_SERIES,
    CONF_NEIGHBOURHOOD,
    CONF_RAIN_EVENTS,
    CONF_RAIN_EVENT_THRESHOLD,
    CONF_LEAD_TIME,
    LEAD_TIME_MAX,
    LEAD_TIME_MIN,
    LEAD_TIME_STEP,
    CONF_MIN_MM,
    CONF_MIN_PEAK_1H,
    CONF_MIN_PEAK_10MIN,
    CONF_COMBINE,
    SUBENTRY_RAIN_WARNING,
)
from .options import (
    DEFAULT_RAIN_WARNING,
    DwdOptions,
    rain_warning_rule,
    rain_warning_subentries,
    tracks_rain_events,
)
from .radar.rain_warning import COMBINES

# Where DWD's radar can have data for a location: a latitude/longitude box
# around its DE1200 grid (45.69-56.21 N, 1.47-18.73 E), rounded outwards. It
# only turns away a location that is clearly elsewhere; the grid each file
# describes is what decides (ADR 0010), and a location in the box but off it
# is reported when a product is read.
COVERAGE_LAT = (45.6, 56.3)
COVERAGE_LON = (1.4, 18.8)

# The sections of the options form, one per group of sensors, in the order
# shown. Only the form is nested: every option is stored flat, under its own
# key (see OptionsFlowHandler.async_step_init).
SECTION_RAIN_FORECAST = "rain_forecast"
SECTION_DRY_STREAK = "dry_streak"
SECTION_RAIN_EVENTS = "rain_event_tracking"
SECTION_ADVANCED = "advanced_options"
OPTION_SECTIONS: dict[str, tuple[str, ...]] = {
    SECTION_RAIN_FORECAST: (
        CONF_PRECIPITATION_THRESHOLD,
        CONF_START_END_MODE,
        CONF_PRECIPITATION_END_ALGORITHM,
        CONF_NEIGHBOURHOOD,
    ),
    SECTION_DRY_STREAK: (CONF_PRECIPITATION_RESET_THRESHOLD, CONF_DRY_STREAK_SOURCE),
    SECTION_RAIN_EVENTS: (CONF_RAIN_EVENTS, CONF_RAIN_EVENT_THRESHOLD),
    SECTION_ADVANCED: (
        CONF_EXTRA_ATTRIBUTES,
        CONF_FULL_ROLLING_SERIES,
        CONF_UNAVAILABLE_WHEN_STALE,
    ),
}

# A rain warning's lead time: how many minutes before the rain it starts, in
# the 5-minute steps of the forecast, up to its 2-hour horizon.

# A rain warning's optional minimums, all in mm.
RAIN_WARNING_MINIMUMS = (CONF_MIN_MM, CONF_MIN_PEAK_1H, CONF_MIN_PEAK_10MIN)


_LOGGER = logging.getLogger(__name__)


def _number(unit: str) -> selector.NumberSelector:
    """Return a non-negative number box in steps of 0.1 ``unit``.

    A Home Assistant number selector shown as a text box, for the thresholds in
    the options form; ``unit`` ("mm/h" or "mm") is shown next to it.

    """
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, step=0.1, unit_of_measurement=unit, mode=selector.NumberSelectorMode.BOX
        )
    )


def _dropdown(
    options: list[str],
    translation_key: str,
    mode: selector.SelectSelectorMode = selector.SelectSelectorMode.DROPDOWN,
) -> selector.SelectSelector:
    """Return a choice of ``options``, labelled by ``translation_key``.

    ``options`` are the values stored; the labels the user sees come from the
    translations under ``translation_key`` (translations/en.json, de.json), so
    the stored values never depend on the language. ``mode`` LIST shows them
    as radio buttons, which reads better than a dropdown for two choices.

    """
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            translation_key=translation_key,
            mode=mode,
        )
    )


def _choice(options: list[str], translation_key: str) -> selector.SelectSelector:
    """Return ``options`` as radio buttons (see _dropdown)."""
    return _dropdown(options, translation_key, selector.SelectSelectorMode.LIST)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for DWD Precipitation."""

    async def async_step_init(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Show the options form, or save what the user entered.

        Home Assistant calls this twice: without input to show the form, and
        with the submitted values. The form has one section per group of
        sensors (OPTION_SECTIONS), but the options are stored flat: every
        option keeps its key, so nothing that reads ``entry.options`` notices
        the sections and no migration is needed. Saving reloads the entry
        (see update_listener).

        The "Rain events" section opens expanded only when the entry tracks
        rain events (the sensor or a rain warning), since its threshold does
        nothing otherwise; "Advanced" is always collapsed. The help texts link
        to the documentation through the ``docs_url`` placeholder.

        """
        if user_input is not None:
            data = {}
            for key, value in user_input.items():
                if key in OPTION_SECTIONS:
                    data.update(value)
                else:
                    data[key] = value
            return self.async_create_entry(title="", data=data)

        entry = self.config_entry
        options = DwdOptions.from_options(entry.options)

        def current(key: str) -> vol.Optional:
            """Return an optional field showing the stored value or the default.

            Pre-fills each field from DwdOptions: the stored value, or the
            default when nothing is stored. A stored value no version wrote
            shows the default that replaces it, so saving the form unchanged
            fixes it.

            """
            return vol.Optional(key, default=getattr(options, key))

        fields = {
            CONF_PRECIPITATION_THRESHOLD: _number("mm/h"),
            CONF_START_END_MODE: _choice(
                [START_END_MODE_TIMESTAMP, START_END_MODE_DURATION],
                CONF_START_END_MODE,
            ),
            CONF_PRECIPITATION_END_ALGORITHM: _choice(
                [RAIN_END_ALGO_EPISODE, RAIN_END_ALGO_CLEARING],
                CONF_PRECIPITATION_END_ALGORITHM,
            ),
            CONF_PRECIPITATION_RESET_THRESHOLD: _number("mm"),
            CONF_DRY_STREAK_SOURCE: _choice(
                list(DRY_STREAK_SOURCES), CONF_DRY_STREAK_SOURCE
            ),
            CONF_NEIGHBOURHOOD: selector.BooleanSelector(),
            CONF_RAIN_EVENTS: selector.BooleanSelector(),
            CONF_RAIN_EVENT_THRESHOLD: _number("mm/h"),
            CONF_EXTRA_ATTRIBUTES: selector.BooleanSelector(),
            CONF_FULL_ROLLING_SERIES: selector.BooleanSelector(),
            CONF_UNAVAILABLE_WHEN_STALE: selector.BooleanSelector(),
        }
        collapsed = {
            SECTION_RAIN_FORECAST: False,
            SECTION_DRY_STREAK: False,
            SECTION_RAIN_EVENTS: not tracks_rain_events(entry, options),
            SECTION_ADVANCED: True,
        }
        schema = vol.Schema(
            {
                vol.Required(name): section(
                    vol.Schema({current(key): fields[key] for key in keys}),  # pyright: ignore[reportArgumentType]  (probatio, see below)
                    {"collapsed": collapsed[name]},
                )
                for name, keys in OPTION_SECTIONS.items()
            }
        )
        # HA's annotations name probatio.Schema, which HA installs as
        # voluptuous at runtime: the same class there, two to pyright.
        # Importing probatio here would break every HA from before the alias.
        return self.async_show_form(
            step_id="init",
            data_schema=schema,  # pyright: ignore[reportArgumentType]
            description_placeholders={"docs_url": DOCS_URL},
        )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for DWD Precipitation."""

    VERSION = 1

    # 1.2: options carry CONF_DRY_STREAK_SOURCE (see async_migrate_entry).
    MINOR_VERSION = 2

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: config_entries.ConfigEntry
    ) -> dict[str, type[config_entries.ConfigSubentryFlow]]:
        """Return the subentries an entry can have: rain warnings.

        Home Assistant shows an "Add rain warning" button on the entry for
        each type returned here, and opens RainWarningSubentryFlow from it.

        """
        return {SUBENTRY_RAIN_WARNING: RainWarningSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlowHandler:
        """Return the options flow handler.

        Home Assistant calls this when the user opens the integration's
        options; the handler shows the form
        (OptionsFlowHandler.async_step_init).

        """
        return OptionsFlowHandler()

    async def async_step_user(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Ask for a name and a location, and create the entry.

        Home Assistant calls this when the user adds the integration: first
        without input to show the form, then with what was entered. It rejects
        an empty or already used name, and a location outside the box DWD's
        radar covers, by showing the form again with an error. A new entry
        stores the default dry-streak source explicitly, so a later change of
        the default never moves it.

        """
        errors: dict[str, str] = {}

        if user_input is not None:
            data = user_input.copy()

            if not data[CONF_NAME].strip():
                errors["base"] = "invalid_name"

            existing_names = {
                entry.title.strip()
                for entry in self.hass.config_entries.async_entries(DOMAIN)
            }
            if data[CONF_NAME].strip() in existing_names:
                errors["base"] = "name_already_exists"

            coords = data.pop(CONF_COORDS)
            data["latitude"] = coords["latitude"]
            data["longitude"] = coords["longitude"]

            lat_min, lat_max = COVERAGE_LAT
            lon_min, lon_max = COVERAGE_LON
            if not (
                lat_min <= data["latitude"] <= lat_max
                and lon_min <= data["longitude"] <= lon_max
            ):
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
            data_schema=self.get_schema_user_step(),  # pyright: ignore[reportArgumentType]  (probatio, see above)
            errors=errors,
        )

    @callback
    def get_schema_user_step(self) -> vol.Schema:
        """Return the form of the first setup step.

        A name, defaulting to Home Assistant's location name, and a place on
        the map, defaulting to Home Assistant's home coordinates. The name
        becomes the device's name and the prefix of every entity id.

        """
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


class RainWarningSubentryFlow(config_entries.ConfigSubentryFlow):
    """Add or change one rain warning of a location (a config subentry).

    The form asks for a name, the lead time and the optional minimum event;
    the name is the subentry's title, and with the location's title the name
    of the warning's device ("Home Laundry"). The data is stored flat and read back with rain_warning_rule().
    Saving reloads the entry (see update_listener).

    """

    async def async_step_user(self, user_input=None) -> config_entries.SubentryFlowResult:
        """Show the form for a new warning, or create it from what was entered."""
        return await self._async_step_form("user", user_input, None)

    async def async_step_reconfigure(
        self, user_input=None
    ) -> config_entries.SubentryFlowResult:
        """Show the form filled with the warning's values, or save the changes.

        The name can change too: the device gets the new name, the entity ids
        stay what they were.

        """
        return await self._async_step_form(
            "reconfigure", user_input, self._get_reconfigure_subentry()
        )

    async def _async_step_form(
        self,
        step_id: str,
        user_input: dict | None,
        subentry: config_entries.ConfigSubentry | None,
    ) -> config_entries.SubentryFlowResult:
        """Validate and save the form of ``step_id``, or show it.

        ``subentry`` is the warning being reconfigured (None for a new one).
        An empty name, or one another warning of this location already has
        (compared as entity ids would see it, so "Laundry" and "laundry!"
        collide), shows the form again with an error.

        """
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            taken = {
                slugify(other.title)
                for other in rain_warning_subentries(self._get_entry())
                if subentry is None or other.subentry_id != subentry.subentry_id
            }
            # slugify() turns a name without letters or digits into "unknown".
            if not any(char.isalnum() for char in name):
                errors["base"] = "invalid_name"
            elif slugify(name) in taken:
                errors["base"] = "name_already_exists"
            else:
                data = {
                    CONF_LEAD_TIME: int(user_input[CONF_LEAD_TIME]),
                    CONF_COMBINE: user_input[CONF_COMBINE],
                }
                data.update(
                    {
                        key: float(user_input[key])
                        for key in RAIN_WARNING_MINIMUMS
                        if user_input.get(key) is not None
                    }
                )
                if subentry is None:
                    return self.async_create_entry(title=name, data=data)
                return self.async_update_and_abort(
                    self._get_entry(), subentry, title=name, data=data
                )

        return self.async_show_form(
            step_id=step_id,
            data_schema=self._schema(subentry, user_input),  # pyright: ignore[reportArgumentType]  (probatio, see OptionsFlowHandler)
            errors=errors,
        )

    @staticmethod
    def _schema(
        subentry: config_entries.ConfigSubentry | None, user_input: dict | None
    ) -> vol.Schema:
        """Return the warning form, filled with what it should show.

        What was just entered when the form comes back with an error, else the
        warning's stored values (reconfigure), else the defaults. A minimum is
        only suggested, never a default, so clearing the field removes it.

        """
        if user_input is not None:
            values = dict(user_input)
        elif subentry is not None:
            rule = rain_warning_rule(subentry.data)
            values = {CONF_NAME: subentry.title} | {
                key: getattr(rule, key) for key in DEFAULT_RAIN_WARNING
            }
        else:
            values = {CONF_NAME: ""} | DEFAULT_RAIN_WARNING

        def suggested(key: str) -> dict:
            return {"suggested_value": values.get(key)}

        return vol.Schema(
            {
                vol.Required(CONF_NAME, description=suggested(CONF_NAME)): str,
                vol.Required(CONF_LEAD_TIME, default=values[CONF_LEAD_TIME]): (
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=LEAD_TIME_MIN,
                            max=LEAD_TIME_MAX,
                            step=LEAD_TIME_STEP,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    )
                ),
                **{
                    vol.Optional(key, description=suggested(key)): _number("mm")
                    for key in RAIN_WARNING_MINIMUMS
                },
                vol.Required(CONF_COMBINE, default=values[CONF_COMBINE]): _dropdown(
                    list(COMBINES), CONF_COMBINE
                ),
            }
        )
