#!/usr/bin/env python3
"""Create the curated test fixture for radar/odim.py tests.

Creates a synthetic ODIM_H5 file with the real RS grid structure and a single
precipitation cell at a known location.  The cell's lat/lon is computed via
pyproj (the authoritative reference implementation) so the wradlib comparison
test can verify that our coordinate transform agrees with it.

Run once from the repo root (needs wradlib + pyproj installed):

    uv run --group wradlib-comparison python scripts/create_fixture.py

Writes:
    tests/fixtures/composite_rs_sample.hd5
    tests/fixtures/fixture_metadata.json
"""

import io
import json
import sys
from pathlib import Path

import h5py
import numpy as np

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
HDF5_OUT = FIXTURES / "composite_rs_sample.hd5"
META_OUT  = FIXTURES / "fixture_metadata.json"

# Real DWD RS grid parameters (confirmed from live files)
PROJDEF = (
    "+proj=stere +lat_ts=60 +lat_0=90 +lon_0=10"
    " +x_0=543196.83521776402 +y_0=3622588.8619310022"
    " +units=m +a=6378137 +b=6356752.3142451802 +no_defs"
)
XSIZE, YSIZE = 1100, 1200
XSCALE = YSCALE = 1000.0   # metres per pixel
LL_LAT, LL_LON = 45.696, 3.567
GAIN, OFFSET = 0.001, -0.001
NODATA = 4294967295        # uint32 max

# Cell near central Germany that we'll set to 2.5 mm
RAIN_ROW, RAIN_COL = 600, 550
RAIN_RAW = 2501            # 2501 * 0.001 - 0.001 = 2.500 mm


def cell_to_lonlat(row: int, col: int) -> tuple[float, float]:
    """Convert grid (row, col) to (lat, lon) via pyproj — the authoritative reference."""
    from pyproj import Proj
    p      = Proj(PROJDEF)
    x_ll, y_ll = p(LL_LON, LL_LAT)
    x = x_ll + col * XSCALE
    y = y_ll + (YSIZE - 1 - row) * YSCALE
    lon, lat = p(x, y, inverse=True)
    return float(lat), float(lon)


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)

    try:
        lat, lon = cell_to_lonlat(RAIN_ROW, RAIN_COL)
    except ImportError:
        print("ERROR: pyproj not found. Install via: uv sync --group wradlib-comparison")
        sys.exit(1)

    expected_mm = float(RAIN_RAW * GAIN + OFFSET)
    print(f"Precipitation cell: row={RAIN_ROW}, col={RAIN_COL}")
    print(f"Projected location: lat={lat:.6f}, lon={lon:.6f}")
    print(f"Expected value:     {expected_mm:.3f} mm")

    # Build the HDF5 fixture
    raw = np.full((YSIZE, XSIZE), NODATA, dtype=np.uint32)
    raw[RAIN_ROW, RAIN_COL] = RAIN_RAW

    buf = io.BytesIO()
    with h5py.File(buf, "w") as f:
        w = f.create_group("where")
        # Store projdef as fixed-length bytes (matches real DWD files)
        w.attrs.create("projdef", data=np.bytes_(PROJDEF))
        w.attrs["xsize"]  = np.int64(XSIZE)
        w.attrs["ysize"]  = np.int64(YSIZE)
        w.attrs["xscale"] = np.float64(XSCALE)
        w.attrs["yscale"] = np.float64(YSCALE)
        w.attrs["LL_lat"] = np.float64(LL_LAT)
        w.attrs["LL_lon"] = np.float64(LL_LON)

        dw = f.create_group("dataset1/data1/what")
        dw.attrs["gain"]     = np.float64(GAIN)
        dw.attrs["offset"]   = np.float64(OFFSET)
        dw.attrs["nodata"]   = np.uint32(NODATA)
        dw.attrs["undetect"] = np.float64(0.0)

        f.create_dataset("dataset1/data1/data", data=raw,
                         compression="gzip", compression_opts=4)

    HDF5_OUT.write_bytes(buf.getvalue())
    print(f"Saved HDF5 → {HDF5_OUT}  ({HDF5_OUT.stat().st_size:,} bytes)")

    meta = {
        "lat":         lat,
        "lon":         lon,
        "expected_mm": expected_mm,
        "grid_row":    RAIN_ROW,
        "grid_col":    RAIN_COL,
        "note": (
            "Synthetic fixture. lat/lon computed via pyproj from (row, col). "
            "Only cell [RAIN_ROW, RAIN_COL] has precipitation; all others are nodata."
        ),
    }
    META_OUT.write_text(json.dumps(meta, indent=2))
    print(f"Saved metadata → {META_OUT}")


if __name__ == "__main__":
    main()
