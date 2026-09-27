"""Pure-wradlib reference: read DWD files and resolve locations without our code.

Shared by the reference tier (committed fixtures) and the live_wradlib tier
(fresh DWD files). Nothing here imports from ``radar/``: a reference that
reuses our arithmetic cannot catch a mistake in it. Import only after
``pytest.importorskip("wradlib")``.
"""

from __future__ import annotations

import bz2
import io
from functools import lru_cache

import numpy as np
import wradlib as wrl

# DWD's DE1200 grid (RS, RV, HymecNG) and the national RADOLAN grid (RW, SF).
DE1200_SHAPE = (1200, 1100)
RADOLAN_SHAPE = (900, 900)


@lru_cache(maxsize=1)
def de1200_crs():
    return wrl.georef.create_crs("dwd-radolan-wgs84-de1200")


@lru_cache(maxsize=1)
def _de1200_edges():
    return wrl.georef.get_radolan_coordinates(*DE1200_SHAPE, crs=de1200_crs(), mode="edge")


def de1200_edge_grid_lonlat() -> np.ndarray:
    """Pixel-edge lon/lat grid, shape (ysize + 1, xsize + 1, 2), south-up."""
    return wrl.georef.get_radolan_grid(
        *DE1200_SHAPE, crs=de1200_crs(), mode="edge", wgs84=True
    )


def de1200_cells(lats, lons) -> tuple[np.ndarray, np.ndarray]:
    """Resolve locations to ODIM (row, col) on wradlib's DE1200 grid.

    wradlib numbers rows south-up; ODIM stores the northernmost row first, so
    ODIM row = ysize - 1 - wradlib row. The cell is the one whose edges enclose
    the projected point; -1 / size marks a point off that side of the grid.
    """
    x_edges, y_edges = _de1200_edges()
    x, y = wrl.georef.reproject(
        np.asarray(lons, dtype=float), np.asarray(lats, dtype=float),
        trg_crs=de1200_crs(),
    )
    col = np.searchsorted(x_edges, x, side="right") - 1
    row_south_up = np.searchsorted(y_edges, y, side="right") - 1
    return DE1200_SHAPE[0] - 1 - row_south_up, col


def de1200_cell(lat: float, lon: float) -> tuple[int, int]:
    rows, cols = de1200_cells([lat], [lon])
    return int(rows[0]), int(cols[0])


def radolan_cell(lat: float, lon: float) -> tuple[int, int]:
    """(row, col) on wradlib's 900x900 RADOLAN grid; row 0 is the south edge."""
    x_edges, y_edges = wrl.georef.get_radolan_coordinates(*RADOLAN_SHAPE, mode="edge")
    x, y = wrl.georef.get_radolan_coords(lon, lat)
    return (
        int(np.searchsorted(y_edges, y, side="right")) - 1,
        int(np.searchsorted(x_edges, x, side="right")) - 1,
    )


def read_odim(hd5: bytes) -> tuple[np.ndarray, dict]:
    """Return (raw grid, /dataset1/data1/what) from wradlib's ODIM reader."""
    dd = wrl.io.read_opera_hdf5(io.BytesIO(hd5))
    return dd["dataset1/data1/data"], dd["dataset1/data1/what"]


def scale_odim(raw: np.ndarray, what: dict) -> np.ndarray:
    """Apply the ODIM gain/offset: nodata -> NaN, undetect -> 0.0.

    float32, like DWD's own convention for the physical value, so it can be
    compared exactly with our reader.
    """
    data = raw.astype(np.float32) * float(what["gain"]) + float(what["offset"])
    data[raw == int(what["nodata"])] = np.nan
    data[raw == int(round(float(what.get("undetect", 0))))] = 0.0
    return data


def read_radolan(bz2_bytes: bytes) -> tuple[np.ndarray, dict]:
    """Return (data, attrs) from wradlib's RADOLAN reader."""
    return wrl.io.read_radolan_composite(bz2.open(io.BytesIO(bz2_bytes)))
