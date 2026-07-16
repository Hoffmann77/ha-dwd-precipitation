"""Constants for the DWD Precipitation integration."""

from homeassistant.const import Platform


DOMAIN = "dwd_precipitation"

PLATFORMS = [Platform.SENSOR]

CONF_COORDS = "coordinates"

CONF_EXTRA_ATTRIBUTES = "extra_state_attributes"

CONF_UNAVAILABLE_WHEN_STALE = "unavailable_when_stale"

CONF_RAIN_THRESHOLD = "rain_threshold"

# 5-minute accumulation (mm) above which a cell counts as raining for the
# RV start/end detection. 0.0 = any DWD-detected precipitation.
DEFAULT_RAIN_THRESHOLD = 0.0

DWD_OPENDATA_URL = "https://opendata.dwd.de"

DWD_RADOLAN_URL = f"{DWD_OPENDATA_URL}/weather/radar/radolan"

DWD_RADVOR_URL = f"{DWD_OPENDATA_URL}/weather/radar/radvor"

DWD_COMPOSITE_URL = f"{DWD_OPENDATA_URL}/weather/radar/composite"