"""Constants for the DWD Precipitation integration."""

from homeassistant.const import Platform

from .radar.nowcast import (
    DEFAULT_END_ALGO,
    END_ALGO_CLEARING,
    END_ALGO_EPISODE,
)


DOMAIN = "dwd_precipitation"

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONF_COORDS = "coordinates"

CONF_EXTRA_ATTRIBUTES = "extra_state_attributes"

CONF_UNAVAILABLE_WHEN_STALE = "unavailable_when_stale"

CONF_PRECIPITATION_THRESHOLD = "precipitation_threshold"

# Rain intensity (mm/h) above which a cell counts as raining for the RV
# start/end detection. 0.0 = any DWD-detected precipitation.
DEFAULT_PRECIPITATION_THRESHOLD = 0.0

CONF_START_END_MODE = "start_end_mode"

# How the merged RV start/end sensors express their state: "timestamp" = the
# absolute time (device_class TIMESTAMP), "duration" = minutes until the event
# (device_class DURATION). The other representation is exposed as an attribute.
START_END_MODE_TIMESTAMP = "timestamp"
START_END_MODE_DURATION = "duration"
DEFAULT_START_END_MODE = START_END_MODE_TIMESTAMP

CONF_PRECIPITATION_END_ALGORITHM = "precipitation_end_algorithm"

# Which algorithm derives the RV "precipitation end" from the 5-minute forecast
# series. The accepted values are owned by radar.nowcast so the pure detector
# and the config option cannot drift apart.
# "episode"  = end of the first contiguous rain episode (first dry gap).
# "clearing" = when no more rain is forecast within the 2-hour horizon.
RAIN_END_ALGO_EPISODE = END_ALGO_EPISODE
RAIN_END_ALGO_CLEARING = END_ALGO_CLEARING
DEFAULT_PRECIPITATION_END_ALGORITHM = DEFAULT_END_ALGO

CONF_PRECIPITATION_RESET_THRESHOLD = "precipitation_reset_threshold"

# mm; "Precipitation last 1h" at/above this value resets the dry streak counter.
DEFAULT_PRECIPITATION_RESET_THRESHOLD = 1.0

# HymecNG precipitation-type classes, indexed by the DWD class value (0..10) as
# defined by the ODIM legend embedded in the composite. These are the possible
# states of the "Precipitation type" enum sensor.
PRECIP_TYPE_BY_INDEX = (
    "no_precipitation",   # 0  NO_PRECIPITATION
    "not_classified",     # 1  NOT_CLASSIFIED
    "drizzle",            # 2  DRIZZLE
    "rain",               # 3  RAIN
    "freezing_drizzle",   # 4  FREEZING_DRIZZLE
    "freezing_rain",      # 5  FREEZING_RAIN
    "sleet",              # 6  SNOW_RAIN (Schneeregen)
    "snow",               # 7  SNOW
    "graupel",            # 8  GRAUPEL
    "hail",               # 9  HAIL
    "large_hail",         # 10 LARGE_HAIL
)
PRECIP_TYPE_OPTIONS = list(PRECIP_TYPE_BY_INDEX)

DWD_OPENDATA_URL = "https://opendata.dwd.de"

DWD_RADOLAN_URL = f"{DWD_OPENDATA_URL}/weather/radar/radolan"

DWD_RADVOR_URL = f"{DWD_OPENDATA_URL}/weather/radar/radvor"

DWD_COMPOSITE_URL = f"{DWD_OPENDATA_URL}/weather/radar/composite"