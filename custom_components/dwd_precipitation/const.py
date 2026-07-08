"""Constants for the DWD Precipitation integration."""

from homeassistant.const import Platform


DOMAIN = "dwd_precipitation"

PLATFORMS = [Platform.SENSOR]

CONF_COORDS = "coordinates"

CONF_EXTRA_ATTRIBUTES = "extra_state_attributes"

CONF_UNAVAILABLE_WHEN_STALE = "unavailable_when_stale"

DWD_OPENDATA_URL = "https://opendata.dwd.de"

DWD_RADOLAN_URL = f"{DWD_OPENDATA_URL}/weather/radar/radolan"

DWD_RADVOR_URL = f"{DWD_OPENDATA_URL}/weather/radar/radvor"

DWD_COMPOSITE_URL = f"{DWD_OPENDATA_URL}/weather/radar/composite"