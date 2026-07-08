#!/usr/bin/env python3
"""Create the curated test fixture for radar/odim.py tests.

Tries to download a real RS file from DWD OpenData.  If no file with
precipitation is found in the last 2 hours, falls back to a synthetic
file with the real RS grid structure and a single known precipitation cell.

The lat/lon of the chosen precipitation cell is computed via pyproj so
that test_location_value_matches_wradlib can verify our coordinate transform
against the ellipsoidal reference implementation.

Run once from the repo root (needs wradlib + pyproj + requests installed):

    uv run --group wradlib-comparison python scripts/create_fixture.py

Writes:
    tests/fixtures/composite_rs_sample.hd5       (RS / ODIM_H5)
    tests/fixtures/fixture_metadata.json         (RS expected values)
    tests/fixtures/radolan_rw_sample.bin.bz2     (RADOLAN RW, real .bz2)
    tests/fixtures/radolan_sf_sample.bin.bz2     (RADOLAN SF, real .bz2)
    tests/fixtures/radolan_metadata.json         (RADOLAN expected values)

The RADOLAN section is best-effort: if wradlib or the DWD files are unavailable
it warns and leaves the RS fixture in place (the RADOLAN tests skip when the
fixtures are absent).
"""

import io
import json
import sys
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import h5py
import numpy as np
import requests

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
HDF5_OUT = FIXTURES / "composite_rs_sample.hd5"
META_OUT  = FIXTURES / "fixture_metadata.json"

DWD_URL   = "https://opendata.dwd.de/weather/radar/composite/rs"
DWD_RADOLAN_URL = "https://opendata.dwd.de/weather/radar/radolan"
RADOLAN_OUT = {
    "rw": FIXTURES / "radolan_rw_sample.bin.bz2",
    "sf": FIXTURES / "radolan_sf_sample.bin.bz2",
}
RADOLAN_META_OUT = FIXTURES / "radolan_metadata.json"
MIN_MM    = 0.1   # minimum precipitation to consider a valid cell

# Real RS grid parameters for the synthetic fallback
PROJDEF = (
    "+proj=stere +lat_ts=60 +lat_0=90 +lon_0=10"
    " +x_0=543196.83521776402 +y_0=3622588.8619310022"
    " +units=m +a=6378137 +b=6356752.3142451802 +no_defs"
)
XSIZE, YSIZE = 1100, 1200
XSCALE = YSCALE = 1000.0
LL_LAT, LL_LON = 45.696, 3.567
GAIN, OFFSET = 0.001, -0.001
NODATA = 4294967295

# Synthetic fallback: cell near central Germany, 2.5 mm precipitation
SYNTH_ROW, SYNTH_COL = 600, 550
SYNTH_RAW = 2501  # → 2.500 mm


def cell_to_lonlat(hdf5_bytes: bytes, row: int, col: int) -> tuple[float, float]:
    """Convert grid (row, col) to (lat, lon) using pyproj."""
    from pyproj import Proj

    with h5py.File(io.BytesIO(hdf5_bytes), "r") as f:
        where = dict(f["where"].attrs)

    projdef = where["projdef"]
    if isinstance(projdef, bytes):
        projdef = projdef.decode()

    p      = Proj(projdef)
    ll_lat = float(where["LL_lat"])
    ll_lon = float(where["LL_lon"])
    xscale = float(where["xscale"])
    yscale = float(where["yscale"])
    ysize  = int(where["ysize"])

    x_ll, y_ll = p(ll_lon, ll_lat)
    x = x_ll + col * xscale
    y = y_ll + (ysize - 1 - row) * yscale
    lon, lat = p(x, y, inverse=True)
    return float(lat), float(lon)


def parse_hdf5(hdf5_bytes: bytes):
    """Return (data_mm, where) from raw HDF5 bytes."""
    with h5py.File(io.BytesIO(hdf5_bytes), "r") as f:
        where = dict(f["where"].attrs)
        what  = dict(f["dataset1/data1/what"].attrs)
        raw   = f["dataset1/data1/data"][:]

    gain   = float(what["gain"])
    offset = float(what["offset"])
    nodata = int(what["nodata"])
    data   = raw.astype(np.float32) * gain + offset
    data[raw == nodata] = np.nan
    return data, where


def try_download_real_file() -> tuple[bytes | None, datetime | None]:
    """Try the last 2 hours of RS releases; return bytes of first one with rain."""
    now = datetime.now(timezone.utc)
    ts  = now.replace(second=0, microsecond=0)
    ts -= timedelta(minutes=ts.minute % 5 + 10)

    for _ in range(24):
        fname = f"composite_rs_{ts.strftime('%Y%m%d_%H%M')}"
        url   = f"{DWD_URL}/{fname}.tar"
        print(f"  Trying {url} …", flush=True)
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            print(f"    → failed: {exc}", flush=True)
            ts -= timedelta(minutes=5)
            continue

        try:
            with tarfile.open(fileobj=io.BytesIO(resp.content)) as tf:
                hdf5_bytes = tf.extractfile(f"{fname}_000-hd5").read()
        except Exception as exc:
            print(f"    → tar extraction failed: {exc}", flush=True)
            ts -= timedelta(minutes=5)
            continue

        data, _ = parse_hdf5(hdf5_bytes)
        rain_cells = np.argwhere((~np.isnan(data)) & (data >= MIN_MM))
        if len(rain_cells) == 0:
            print(f"    → no precipitation, trying earlier …", flush=True)
            ts -= timedelta(minutes=5)
            continue

        row, col = int(rain_cells[0][0]), int(rain_cells[0][1])
        value_mm = float(data[row, col])
        print(f"    → found precipitation! row={row}, col={col}, value={value_mm:.3f} mm")
        return hdf5_bytes, ts

    return None, None


def make_synthetic_hdf5() -> bytes:
    """Create a minimal ODIM_H5 fixture with the real RS grid structure."""
    raw = np.full((YSIZE, XSIZE), NODATA, dtype=np.uint32)
    raw[SYNTH_ROW, SYNTH_COL] = SYNTH_RAW

    buf = io.BytesIO()
    with h5py.File(buf, "w") as f:
        # Root what — standard ODIM_H5 file metadata
        rw = f.create_group("what")
        rw.attrs["version"] = np.bytes_(b"H5rad 2.3")
        rw.attrs["date"]    = np.bytes_(b"20260518")
        rw.attrs["time"]    = np.bytes_(b"160000")
        rw.attrs["object"]  = np.bytes_(b"COMP")
        rw.attrs["source"]  = np.bytes_(b"ORG:78,CTY:616,CMT:Deutscher Wetterdienst")

        # where — grid geometry
        w = f.create_group("where")
        w.attrs.create("projdef", data=np.bytes_(PROJDEF))
        w.attrs["xsize"]  = np.int64(XSIZE)
        w.attrs["ysize"]  = np.int64(YSIZE)
        w.attrs["xscale"] = np.float64(XSCALE)
        w.attrs["yscale"] = np.float64(YSCALE)
        w.attrs["LL_lat"] = np.float64(LL_LAT)
        w.attrs["LL_lon"] = np.float64(LL_LON)

        # dataset1/what — product metadata
        d1w = f.create_group("dataset1/what")
        d1w.attrs["product"]   = np.bytes_(b"MAX")
        d1w.attrs["prodname"]  = np.bytes_(b"RS_top_view")
        d1w.attrs["startdate"] = np.bytes_(b"20260518")
        d1w.attrs["starttime"] = np.bytes_(b"150000")
        d1w.attrs["enddate"]   = np.bytes_(b"20260518")
        d1w.attrs["endtime"]   = np.bytes_(b"160000")

        # dataset1/data1/what — moment scaling; nodata is float64 in real files
        dw = f.create_group("dataset1/data1/what")
        dw.attrs["quantity"] = np.bytes_(b"ACRR")
        dw.attrs["gain"]     = np.float64(GAIN)
        dw.attrs["offset"]   = np.float64(OFFSET)
        dw.attrs["nodata"]   = np.float64(NODATA)
        dw.attrs["undetect"] = np.float64(0.0)

        f.create_dataset("dataset1/data1/data", data=raw,
                         compression="gzip", compression_opts=4)
    return buf.getvalue()


def try_download_radolan(product: str) -> tuple[bytes | None, datetime | None]:
    """Try the last ~8 hourly RADOLAN releases (HH:50); return first that downloads."""
    now = datetime.now(timezone.utc)
    ts  = now.replace(minute=50, second=0, microsecond=0)
    if ts > now - timedelta(minutes=40):
        ts -= timedelta(hours=1)

    for _ in range(8):
        fname = f"raa01-{product}_10000-{ts.strftime('%y%m%d%H%M')}-dwd---bin.bz2"
        url   = f"{DWD_RADOLAN_URL}/{product}/{fname}"
        print(f"  Trying {url} …", flush=True)
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            return resp.content, ts
        except Exception as exc:
            print(f"    → failed: {exc}", flush=True)
            ts -= timedelta(hours=1)

    return None, None


def radolan_cell_meta(bz2_bytes: bytes) -> dict:
    """Parse a RADOLAN .bz2 with wradlib (authoritative) and record a rain cell.

    lat/lon come from wradlib's WGS84 grid so the parser test can verify our
    vendored georef puts that cell at the same (row, col).
    """
    import bz2 as _bz2

    import wradlib as wrl

    data, attrs = wrl.io.read_radolan_composite(_bz2.open(io.BytesIO(bz2_bytes)))
    arr = np.asarray(data, dtype=float)

    rain = np.argwhere(np.isfinite(arr) & (arr >= MIN_MM))
    if len(rain):
        row, col = int(rain[0][0]), int(rain[0][1])
    else:
        row, col = arr.shape[0] // 2, arr.shape[1] // 2

    grid = wrl.georef.get_radolan_grid(*arr.shape, wgs84=True)
    lon, lat = float(grid[row, col, 0]), float(grid[row, col, 1])

    return {
        "producttype":     str(attrs["producttype"]),
        "datetime":        attrs["datetime"].strftime("%Y-%m-%dT%H:%M:00Z"),
        "grid_shape":      list(arr.shape),
        "intervalseconds": int(attrs["intervalseconds"]),
        "precision":       float(attrs.get("precision", 0.0)),
        "lat":             lat,
        "lon":             lon,
        "grid_row":        row,
        "grid_col":        col,
        "expected_mm":     float(arr[row, col]),
    }


def generate_radolan_fixtures() -> None:
    """Best-effort: download + record RW and SF RADOLAN fixtures."""
    try:
        import wradlib  # noqa: F401
    except ImportError:
        print("\nSkipping RADOLAN fixtures: wradlib not installed.")
        return

    meta: dict = {}
    for product in ("rw", "sf"):
        print(f"\nAttempting to download real RADOLAN {product.upper()} file …")
        content, ts = try_download_radolan(product)
        if content is None:
            print(f"  No {product.upper()} file available — skipping.")
            continue
        RADOLAN_OUT[product].write_bytes(content)
        print(f"  Saved {product.upper()} → {RADOLAN_OUT[product]} "
              f"({RADOLAN_OUT[product].stat().st_size:,} bytes)")
        meta[product] = radolan_cell_meta(content)
        m = meta[product]
        print(f"  {product.upper()} cell row={m['grid_row']}, col={m['grid_col']}, "
              f"value={m['expected_mm']:.3f} mm @ lat={m['lat']:.4f}, lon={m['lon']:.4f}")

    if meta:
        RADOLAN_META_OUT.write_text(json.dumps(meta, indent=2))
        print(f"\nSaved RADOLAN metadata → {RADOLAN_META_OUT}")


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)

    try:
        from pyproj import Proj  # noqa: F401 — check it's available
    except ImportError:
        print("ERROR: pyproj not found. Install: uv sync --group wradlib-comparison")
        sys.exit(1)

    print("Attempting to download real RS file from DWD OpenData …")
    hdf5_bytes, ts = try_download_real_file()
    synthetic = False

    if hdf5_bytes is None:
        print("No real file available, creating synthetic fixture …")
        hdf5_bytes = make_synthetic_hdf5()
        synthetic = True

    # Find the precipitation cell to record
    data, _ = parse_hdf5(hdf5_bytes)
    if synthetic:
        row, col = SYNTH_ROW, SYNTH_COL
    else:
        rain_cells = np.argwhere((~np.isnan(data)) & (data >= MIN_MM))
        row, col = int(rain_cells[0][0]), int(rain_cells[0][1])

    value_mm = float(data[row, col])
    lat, lon = cell_to_lonlat(hdf5_bytes, row, col)

    print(f"\nFixture precipitation cell: row={row}, col={col}")
    print(f"Location (pyproj):          lat={lat:.6f}, lon={lon:.6f}")
    print(f"Value:                       {value_mm:.3f} mm")

    HDF5_OUT.write_bytes(hdf5_bytes)
    print(f"\nSaved HDF5     → {HDF5_OUT}  ({HDF5_OUT.stat().st_size:,} bytes)")

    meta = {
        "lat":         lat,
        "lon":         lon,
        "expected_mm": value_mm,
        "grid_row":    row,
        "grid_col":    col,
        "synthetic":   synthetic,
        "source_ts":   ts.strftime("%Y-%m-%dT%H:%M:00Z") if ts else None,
        "note": (
            "lat/lon derived from (row, col) via pyproj so the wradlib test "
            "can verify our ellipsoidal coordinate transform matches pyproj."
        ),
    }
    META_OUT.write_text(json.dumps(meta, indent=2))
    print(f"Saved metadata → {META_OUT}")

    generate_radolan_fixtures()


if __name__ == "__main__":
    main()
