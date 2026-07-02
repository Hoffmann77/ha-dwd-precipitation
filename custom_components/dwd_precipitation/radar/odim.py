"""ODIM_H5 reader for DWD RS Cartesian precipitation composites."""

import re
import math

import numpy as np
import h5py

# RS polar-stereographic projection parameters (constant for all RS files)
_RS_A     = 6378137.0            # WGS84 semi-major axis (metres)
_RS_B     = 6356752.3142451802   # WGS84 semi-minor axis (metres)
_RS_E2    = 1 - (_RS_B / _RS_A) ** 2      # first eccentricity squared
_RS_E     = math.sqrt(_RS_E2)             # first eccentricity
_RS_LAT_TS = math.radians(60.0)           # standard parallel
_RS_LON_0  = 10.0                         # central meridian (degrees)

# Precomputed scale-factor constants at the standard parallel (lat_ts = 60°).
# m_c / t_c implements Snyder's polar stereographic for the ellipsoid:
#   ρ = a · m_c · t(φ) / t_c    where t(φ) is the conformal latitude factor.
_sin_lat_ts = math.sin(_RS_LAT_TS)
_cos_lat_ts = math.cos(_RS_LAT_TS)
_RS_M_C = _cos_lat_ts / math.sqrt(1 - _RS_E2 * _sin_lat_ts ** 2)
_RS_T_C = (
    math.tan(math.pi / 4 - _RS_LAT_TS / 2)
    / ((1 - _RS_E * _sin_lat_ts) / (1 + _RS_E * _sin_lat_ts)) ** (_RS_E / 2)
)

# Fixed RS grid metadata (confirmed from DWD ODIM_H5 files)
RS_WHERE = {
    "projdef": (
        "+proj=stere +lat_ts=60 +lat_0=90 +lon_0=10"
        " +x_0=543196.83521776402 +y_0=3622588.8619310022"
        " +units=m +a=6378137 +b=6356752.3142451802 +no_defs"
    ),
    "LL_lat": 45.696,
    "LL_lon": 3.567,
    "xscale": 1000.0,
    "yscale": 1000.0,
    "ysize": 1200,
    "xsize": 1100,
}


def _parse_proj_param(projdef: str, key: str) -> float:
    """Extract a numeric PROJ4 parameter from a projdef string."""
    m = re.search(rf"\+{key}=(\S+)", projdef)
    if m is None:
        raise ValueError(f"Parameter +{key} not found in: {projdef}")
    return float(m.group(1))


def _lonlat_to_xy(lon: float, lat: float, x_0: float, y_0: float):
    """Convert (lon, lat) to RS projection (x, y) in metres.

    Ellipsoidal polar-stereographic (Snyder §21) matching pyproj's
    +proj=stere +lat_0=90 +lat_ts=60 on WGS84.  Sub-millimetre accuracy.
    """
    phi = math.radians(lat)
    lam = math.radians(lon - _RS_LON_0)
    sin_phi = math.sin(phi)
    t = (
        math.tan(math.pi / 4 - phi / 2)
        / ((1 - _RS_E * sin_phi) / (1 + _RS_E * sin_phi)) ** (_RS_E / 2)
    )
    rho = _RS_A * _RS_M_C * t / _RS_T_C
    return rho * math.sin(lam) + x_0, -rho * math.cos(lam) + y_0


def _normalise_attr_value(value):
    """Return HDF5 attributes as plain Python values."""
    if hasattr(value, "decode"):
        return value.decode()
    if hasattr(value, "item"):
        return value.item()
    return value


def read_odim_composite(fileobj, dataset: str = "dataset1", moment: str = "data1"):
    """Read a Cartesian ODIM_H5 composite.

    Returns (data, dataset_what) where data is a float32 array and dataset_what
    is the normalised /dataset/what attribute dict.
    nodata cells (outside radar range / masked) → NaN.
    undetect cells (radar scanned, zero precipitation detected) → 0.0.
    """
    with h5py.File(fileobj, "r") as hf:
        dataset_what = {
            k: _normalise_attr_value(v)
            for k, v in hf[f"{dataset}/what"].attrs.items()
        }
        what = {
            k: _normalise_attr_value(v)
            for k, v in hf[f"{dataset}/{moment}/what"].attrs.items()
        }
        raw = hf[f"{dataset}/{moment}/data"][:]

    gain     = float(what["gain"])
    offset   = float(what["offset"])
    nodata   = int(what["nodata"])
    undetect = int(round(float(what.get("undetect", 0))))

    data = raw.astype(np.float32) * gain + offset
    data[raw == nodata]   = np.nan
    data[raw == undetect] = 0.0

    return data, dataset_what


def get_rs_grid_index(lat: float, lon: float, where: dict | None = None):
    """Return (row, col) of the RS grid cell nearest to (lat, lon).

    Uses the fixed RS grid parameters by default; pass a custom where dict
    to override (e.g. for testing or future grid changes).
    """
    if where is None:
        where = RS_WHERE

    projdef = where["projdef"]
    if hasattr(projdef, "decode"):
        projdef = projdef.decode()

    x_0 = _parse_proj_param(projdef, "x_0")
    y_0 = _parse_proj_param(projdef, "y_0")
    xscale = float(where["xscale"])
    yscale = float(where["yscale"])
    ysize = int(where["ysize"])

    x_ll, y_ll = _lonlat_to_xy(float(where["LL_lon"]), float(where["LL_lat"]), x_0, y_0)
    x_pt, y_pt = _lonlat_to_xy(lon, lat, x_0, y_0)

    col = int(round((x_pt - x_ll) / xscale))
    # Row 0 is the top (highest y); y_ll is the southernmost (lowest y)
    row = int(ysize - 1 - round((y_pt - y_ll) / yscale))
    return row, col
