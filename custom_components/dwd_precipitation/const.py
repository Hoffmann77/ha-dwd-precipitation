"""The enphase_envoy component."""

from homeassistant.const import Platform


DOMAIN = "dwd_precipitation"

PLATFORMS = [Platform.SENSOR]

CONF_COORDS = "coordinates"

DWD_OPENDATA_URL = "https://opendata.dwd.de"

DWD_RADOLAN_URL = f"{DWD_OPENDATA_URL}/weather/radar/radolan"

DWD_RADVOR_URL = f"{DWD_OPENDATA_URL}/weather/radar/radvor"