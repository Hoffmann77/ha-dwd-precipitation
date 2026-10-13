"""Where DWD OpenData publishes each product's releases. HA-free.

The one place the URL patterns live: the products fetch from here, and the
release-delay probe, the comparison scripts and the live test tiers build
their URLs from here too, so none of them can check a different file than the
integration fetches.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

OPENDATA = "https://opendata.dwd.de"
RADAR = f"{OPENDATA}/weather/radar"
COMPOSITE = f"{RADAR}/composite"
RADOLAN = f"{RADAR}/radolan"


def radvor_prefix(product: str, ts: datetime) -> str:
    """Return the name stem of a RADVOR release (``composite_rs_<ts>``).

    The tar is ``<stem>.tar``, its members ``<stem>_<lead>-hd5``.
    """
    return f"composite_{product}_{ts:%Y%m%d_%H%M}"


def radvor_url(product: str, ts: datetime) -> str:
    """Return the tar of a RADVOR nowcast release (RS, RV)."""
    return f"{COMPOSITE}/{product}/{radvor_prefix(product, ts)}.tar"


def hymecng_url(ts: datetime) -> str:
    """Return the HymecNG file of release ``ts`` (one ODIM_H5 file, no tar)."""
    return f"{COMPOSITE}/hymecng/composite_HymecNG_{ts:%Y%m%d_%H%M}_000-hd5"


def radolan_url(product: str, ts: datetime) -> str:
    """Return a RADOLAN analysis (RW, SF) in its HDF5 edition."""
    return f"{RADOLAN}/{product}/raa01-{product}_10000-{ts:%y%m%d%H%M}-dwd---bin.hdf5"


# Each product key's file. rw_10min and sf_2350 are other release grids over
# the same file families as rw and sf.
PRODUCT_URLS: dict[str, Callable[[datetime], str]] = {
    "rs": lambda ts: radvor_url("rs", ts),
    "rv": lambda ts: radvor_url("rv", ts),
    "hymecng": hymecng_url,
    "rw": lambda ts: radolan_url("rw", ts),
    "rw_10min": lambda ts: radolan_url("rw", ts),
    "sf": lambda ts: radolan_url("sf", ts),
    "sf_2350": lambda ts: radolan_url("sf", ts),
}


def product_url(product_key: str, ts: datetime) -> str:
    """Return the URL of release ``ts`` of the product with that key."""
    return PRODUCT_URLS[product_key](ts)
