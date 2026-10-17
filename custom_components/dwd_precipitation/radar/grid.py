"""The grid a DWD file describes in its ODIM /where group. HA-free.

Every product reads its cell on the grid its own file describes rather than on
a copy of DWD's grid in the code, so if DWD moves or resizes a grid the
integration keeps reading the cell that holds the location (ADR 0010). That
cell is the one *containing* the location: its offset from the grid's outer
lower-left corner, floored (ADR 0008).

Only DWD's projection is computed: polar stereographic on the north pole, on
an ellipsoid. A PROJ string is read in any parameter order and with the
ellipsoid spelled out or named; anything this version would place wrongly is
refused (UnsupportedGrid). Another projection would be one more branch in
_projection.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

# No radar composite of DWD's is larger (DE1200 has 1.32 M cells). It bounds
# what a crafted file could make a reader inflate.
MAX_CELLS = 4_000_000

# Ellipsoids by their PROJ names: (semi-major, semi-minor axis) in metres.
_ELLIPSOIDS = {
    "WGS84": (6378137.0, 6356752.314245179),
    "GRS80": (6378137.0, 6356752.314140356),
}

# Every PROJ parameter understood here. The last four do not move a cell
# (towgs84 only as a zero shift; any other is refused).
_KNOWN = {
    "proj", "lat_0", "lat_ts", "lon_0", "x_0", "y_0", "a", "b", "ellps", "datum",
    "units", "no_defs", "type", "wktext", "towgs84",
}


class UnsupportedGrid(ValueError):
    """A /where group this version cannot place a location on."""


class OutsideGrid(ValueError):
    """The location is not on the file's grid."""


def _t(phi: float, e: float) -> float:
    """Snyder's t: the conformal latitude factor at latitude ``phi`` (radians)."""
    s = math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - e * s) / (1 + e * s)) ** (e / 2)


@dataclass(frozen=True)
class _Stereographic:
    """North-polar stereographic on an ellipsoid (Snyder, Map Projections §21)."""

    a: float  # semi-major axis (m)
    e: float  # first eccentricity
    lon_0: float  # central meridian (degrees)
    x_0: float  # false easting (m)
    y_0: float  # false northing (m)
    m_c: float  # Snyder's m at the standard parallel
    t_c: float  # Snyder's t at the standard parallel

    @classmethod
    def create(
        cls, a: float, b: float, lat_ts: float, lon_0: float, x_0: float, y_0: float
    ) -> _Stereographic:
        e = math.sqrt(1 - (b / a) ** 2)
        phi_c = math.radians(lat_ts)
        m_c = math.cos(phi_c) / math.sqrt(1 - e**2 * math.sin(phi_c) ** 2)
        return cls(a, e, lon_0, x_0, y_0, m_c, _t(phi_c, e))

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        """Return the projected (x, y) of a location, in metres."""
        rho = self.a * self.m_c * _t(math.radians(lat), self.e) / self.t_c
        lam = math.radians(lon - self.lon_0)
        return rho * math.sin(lam) + self.x_0, -rho * math.cos(lam) + self.y_0


@dataclass(frozen=True)
class Grid:
    """A grid of equal cells on a projection, from its outer lower-left corner."""

    projection: _Stereographic
    x_ll: float  # the outer lower-left corner, projected (m)
    y_ll: float
    xscale: float  # cell size (m)
    yscale: float
    xsize: int  # columns
    ysize: int  # rows

    @property
    def shape(self) -> tuple[int, int]:
        """Return (rows, columns): the shape the file's datasets must have."""
        return self.ysize, self.xsize

    def cell(self, lat: float, lon: float) -> tuple[int, int]:
        """Return the (row, col) of the cell holding a location; row 0 is the north edge."""
        x, y = self.projection.xy(lat, lon)
        col = math.floor((x - self.x_ll) / self.xscale)
        row = self.ysize - 1 - math.floor((y - self.y_ll) / self.yscale)
        if not (0 <= row < self.ysize and 0 <= col < self.xsize):
            raise OutsideGrid(f"({lat}, {lon}) is outside the {self.ysize} x {self.xsize} grid")
        return row, col


def grid_from_where(where: Mapping[str, Any]) -> Grid:
    """Return the grid an ODIM /where group describes (attributes as read)."""
    try:
        projdef = where["projdef"]
        description = (
            projdef.decode() if isinstance(projdef, bytes) else str(projdef),
            float(where["LL_lat"]),
            float(where["LL_lon"]),
            float(where["xscale"]),
            float(where["yscale"]),
            int(where["xsize"]),
            int(where["ysize"]),
        )
    except (KeyError, TypeError, ValueError) as err:
        raise UnsupportedGrid(f"incomplete /where group ({err!r})") from err
    return _grid(*description)


# Every member of a release describes its grid the same way, so a grid is
# built once per description, not once per file.
@lru_cache(maxsize=8)
def _grid(
    projdef: str,
    ll_lat: float,
    ll_lon: float,
    xscale: float,
    yscale: float,
    xsize: int,
    ysize: int,
) -> Grid:
    if not (xsize > 0 and ysize > 0 and xsize * ysize <= MAX_CELLS and xscale > 0 and yscale > 0):
        raise UnsupportedGrid(f"a {ysize} x {xsize} grid of {yscale} x {xscale} m cells")
    projection = _projection(projdef)
    x_ll, y_ll = projection.xy(ll_lat, ll_lon)
    return Grid(projection, x_ll, y_ll, xscale, yscale, xsize, ysize)


def _projection(projdef: str) -> _Stereographic:
    """Read a PROJ string, in any order; refuse what would be placed wrongly."""
    params: dict[str, str] = {}
    for token in projdef.split():
        key, _, value = token.removeprefix("+").partition("=")
        params[key] = value

    if unknown := sorted(set(params) - _KNOWN):
        raise UnsupportedGrid(f"PROJ parameters {unknown} in {projdef!r}")
    if params.get("proj") != "stere" or _number(params, "lat_0") != 90:
        raise UnsupportedGrid(f"not a north-polar stereographic grid: {projdef!r}")
    if params.get("units", "m") != "m":
        raise UnsupportedGrid(f"not in metres: {projdef!r}")
    if params.get("towgs84", "0").strip("0.,"):
        raise UnsupportedGrid(f"a datum shift: {projdef!r}")
    lat_ts = _number(params, "lat_ts")
    if not 0 < lat_ts < 90:
        raise UnsupportedGrid(f"standard parallel {lat_ts}: {projdef!r}")

    a, b = _ellipsoid(params, projdef)
    return _Stereographic.create(
        a,
        b,
        lat_ts,
        _number(params, "lon_0", 0.0),
        _number(params, "x_0", 0.0),
        _number(params, "y_0", 0.0),
    )


def _ellipsoid(params: dict[str, str], projdef: str) -> tuple[float, float]:
    """Return (a, b) from +a/+b, or from a named ellipsoid or datum."""
    if "a" in params or "b" in params:
        return _number(params, "a"), _number(params, "b")
    if (name := params.get("ellps") or params.get("datum")) in _ELLIPSOIDS:
        return _ELLIPSOIDS[name]
    raise UnsupportedGrid(f"no ellipsoid this version knows: {projdef!r}")


def _number(params: dict[str, str], key: str, default: float | None = None) -> float:
    """Return a numeric PROJ parameter; a missing one takes ``default`` if given."""
    if key not in params:
        if default is None:
            raise UnsupportedGrid(f"no +{key} in the PROJ string")
        return default
    try:
        return float(params[key])
    except ValueError:
        raise UnsupportedGrid(f"+{key}={params[key]}") from None
