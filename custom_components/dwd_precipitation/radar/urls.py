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

    RADVOR is DWD's radar nowcast (products RS and RV). Each release is one tar
    archive named ``<stem>.tar``, and every grid inside it is a member named
    ``<stem>_<lead>-hd5``, where the lead is the forecast's minutes after the
    release time ``ts`` (UTC). The range reader and the parsers build the
    member names from this stem.

    """
    return f"composite_{product}_{ts:%Y%m%d_%H%M}"


def radvor_url(product: str, ts: datetime) -> str:
    """Return the tar of a RADVOR nowcast release (RS, RV).

    DWD publishes one tar per 5-minute release, holding its 25 grids: the leads
    0, 5, ..., 120 minutes after the release time ``ts`` (UTC). ``product`` is
    "rs" or "rv".

    """
    return f"{COMPOSITE}/{product}/{radvor_prefix(product, ts)}.tar"


def hymecng_url(ts: datetime) -> str:
    """Return the HymecNG file of release ``ts`` (one ODIM_H5 file, no tar).

    HymecNG is DWD's precipitation-type product (rain, snow, hail, ...),
    published every 5 minutes as a single grid. ``ts`` is the release's nominal
    time in UTC.

    """
    return f"{COMPOSITE}/hymecng/composite_HymecNG_{ts:%Y%m%d_%H%M}_000-hd5"


def radolan_url(product: str, ts: datetime) -> str:
    """Return a RADOLAN analysis (RW, SF) in its HDF5 edition.

    RADOLAN products are measured precipitation totals, adjusted with rain-
    gauge readings: RW the last hour, SF the last 24 hours. ``product`` is "rw"
    or "sf" and ``ts`` the end of the window, in UTC. DWD also publishes
    RADOLAN in a legacy binary edition, which the integration does not read
    (ADR 0004).

    """
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
    """Return the URL of release ``ts`` of the product with that key.

    ``product_key`` is a coordinator's PRODUCT_KEY ("rs", "rv", "hymecng",
    "rw", "rw_10min", "sf" or "sf_2350"); the two derived keys use the files of
    "rw" and "sf". The products, the scripts and the live tests all build their
    URLs here, so none of them can check a different file than the integration
    fetches.

    """
    return PRODUCT_URLS[product_key](ts)
