"""Tests for radar/odim.py — ODIM_H5 parser and RS grid index."""

import io
import json
import math
from pathlib import Path

import h5py
import numpy as np
import pytest

# Import directly from the radar sub-package to avoid triggering
# custom_components/dwd_precipitation/__init__.py (which imports homeassistant).
# Both import paths resolve to the same module; "." in pythonpath provides the
# full package path for the ha-test environment, while
# "custom_components/dwd_precipitation" in pythonpath provides "radar.odim"
# for the wradlib-comparison environment without homeassistant.
from radar.odim import (
    RS_WHERE,
    _lonlat_to_xy,
    _parse_proj_param,
    get_rs_grid_index,
    read_odim_composite,
)

FIXTURE_HDF5 = Path(__file__).parent / "fixtures" / "composite_rs_sample.hd5"
FIXTURE_META = Path(__file__).parent / "fixtures" / "fixture_metadata.json"

_PROJDEF = RS_WHERE["projdef"]
_X_0 = 543196.83521776402
_Y_0 = 3622588.8619310022


# ---------------------------------------------------------------------------
# Synthetic HDF5 builder
# ---------------------------------------------------------------------------

def _make_odim_h5(shape=(5, 5), gain=0.001, offset=-0.001, nodata=4294967295,
                  projdef_as_bytes=False, fill_raw=1001):
    """Build a minimal ODIM_H5 file in memory matching the real DWD RS format.

    fill_raw=1001 → physical value 1001*0.001 + (-0.001) = 1.0 mm.
    Cell [0, 0] is always set to nodata.
    """
    buf = io.BytesIO()
    with h5py.File(buf, "w") as f:
        # Root what — standard ODIM_H5 file metadata
        rw = f.create_group("what")
        rw.attrs["version"] = np.bytes_(b"H5rad 2.3")
        rw.attrs["date"]    = np.bytes_(b"20260518")
        rw.attrs["time"]    = np.bytes_(b"160000")
        rw.attrs["object"]  = np.bytes_(b"COMP")
        rw.attrs["source"]  = np.bytes_(b"ORG:78,CTY:616")

        # where — grid geometry
        w = f.create_group("where")
        projdef = np.bytes_(_PROJDEF) if projdef_as_bytes else _PROJDEF
        w.attrs.create("projdef", data=projdef)
        w.attrs["xsize"]  = np.int64(shape[1])
        w.attrs["ysize"]  = np.int64(shape[0])
        w.attrs["xscale"] = np.float64(1000.0)
        w.attrs["yscale"] = np.float64(1000.0)
        w.attrs["LL_lat"] = np.float64(RS_WHERE["LL_lat"])
        w.attrs["LL_lon"] = np.float64(RS_WHERE["LL_lon"])

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
        dw.attrs["gain"]     = np.float64(gain)
        dw.attrs["offset"]   = np.float64(offset)
        dw.attrs["nodata"]   = np.float64(nodata)
        dw.attrs["undetect"] = np.float64(0.0)

        raw = np.full(shape, fill_raw, dtype=np.uint32)
        raw[0, 0] = nodata
        raw[0, 1] = 0  # undetect: radar scanned, no precipitation
        f.create_dataset("dataset1/data1/data", data=raw)

    buf.seek(0)
    return buf


# ===========================================================================
# Group 1 — _parse_proj_param
# ===========================================================================

def test_parse_x0():
    assert _parse_proj_param(_PROJDEF, "x_0") == pytest.approx(_X_0)


def test_parse_y0():
    assert _parse_proj_param(_PROJDEF, "y_0") == pytest.approx(_Y_0)


def test_parse_missing_raises():
    with pytest.raises(ValueError, match="not found"):
        _parse_proj_param(_PROJDEF, "nonexistent_param")


# ===========================================================================
# Group 2 — _lonlat_to_xy
# ===========================================================================

def test_north_pole_maps_to_origin():
    """lat=90 → rho=0 → result is exactly (x_0, y_0)."""
    x, y = _lonlat_to_xy(0.0, 90.0, _X_0, _Y_0)
    assert x == pytest.approx(_X_0)
    assert y == pytest.approx(_Y_0)


def test_central_meridian_x_equals_x0():
    """lon=10 (central meridian) → sin(0)=0 → x component from rho is 0 → x=x_0."""
    x, _ = _lonlat_to_xy(10.0, 51.0, _X_0, _Y_0)
    assert x == pytest.approx(_X_0, rel=1e-9)


# ===========================================================================
# Group 3 — get_rs_grid_index
# ===========================================================================

def test_ll_corner_maps_to_bottom_left():
    """The LL corner (lowest-left pixel) must map to (ysize-1, 0)."""
    row, col = get_rs_grid_index(RS_WHERE["LL_lat"], RS_WHERE["LL_lon"])
    assert col == 0
    assert row == RS_WHERE["ysize"] - 1


def test_ur_corner_maps_near_top_right():
    """UR corner should map within ±5 cells of (0, xsize-1)."""
    # Approx UR from DWD spec
    row, col = get_rs_grid_index(55.845, 18.732)
    assert abs(row - 0) <= 5
    assert abs(col - (RS_WHERE["xsize"] - 1)) <= 5


def test_bytes_projdef_same_result():
    """projdef stored as bytes (real DWD files) gives identical result."""
    where_bytes = dict(RS_WHERE)
    where_bytes["projdef"] = RS_WHERE["projdef"].encode()
    row_str, col_str = get_rs_grid_index(51.0, 10.0)
    row_b,   col_b   = get_rs_grid_index(51.0, 10.0, where=where_bytes)
    assert row_str == row_b
    assert col_str == col_b


# ===========================================================================
# Group 4 — read_odim_composite (synthetic, no wradlib)
# ===========================================================================

@pytest.fixture(scope="module")
def parsed_synthetic():
    buf = _make_odim_h5()
    return read_odim_composite(buf)


def test_scaling(parsed_synthetic):
    data, _ = parsed_synthetic
    non_nan = data[~np.isnan(data)]
    # data[0,1] is the undetect cell (0.0); first positive value is from fill_raw=1001.
    assert float(non_nan[non_nan > 0][0]) == pytest.approx(1.0)


def test_nodata_is_nan(parsed_synthetic):
    data, _ = parsed_synthetic
    assert np.isnan(data[0, 0])


def test_undetect_is_zero(parsed_synthetic):
    # raw=0 with offset=-0.001 would give -0.001 without the undetect fix.
    data, _ = parsed_synthetic
    assert data[0, 1] == 0.0


def test_shape(parsed_synthetic):
    data, _ = parsed_synthetic
    assert data.shape == (5, 5)


def test_dtype_float32(parsed_synthetic):
    data, _ = parsed_synthetic
    assert data.dtype == np.float32


def test_where_keys(parsed_synthetic):
    _, where = parsed_synthetic
    assert "xscale" in where
    assert "yscale" in where


def test_bytes_projdef_roundtrip():
    """projdef stored as bytes in the HDF5 must parse without error."""
    buf = _make_odim_h5(projdef_as_bytes=True)
    data, where = read_odim_composite(buf)
    assert data.shape == (5, 5)
    assert not np.isnan(data[1, 0])


# ===========================================================================
# Group 5 — wradlib comparison against curated fixture
# ===========================================================================

def _apply_wradlib_scaling(dd):
    raw      = dd["dataset1/data1/data"]
    gain     = float(dd["dataset1/data1/what"]["gain"])
    offset   = float(dd["dataset1/data1/what"]["offset"])
    nodata   = int(dd["dataset1/data1/what"]["nodata"])
    undetect = int(round(float(dd["dataset1/data1/what"].get("undetect", 0))))
    data     = raw.astype(np.float32) * gain + offset
    data[raw == nodata]   = np.nan
    data[raw == undetect] = 0.0
    
    return data


def _pyproj_grid_index(dd, lat, lon):
    """Reference grid index from pyproj (authoritative).

    Row 0 is the top (northernmost).  y increases northward in projection
    space, so raster_row = ysize - 1 - northward_pixels_from_LL.
    """
    from pyproj import Proj  # mandatory wradlib dep

    projdef = dd["where"]["projdef"]
    if isinstance(projdef, bytes):
        projdef = projdef.decode()
    p      = Proj(projdef)
    ll_lat = float(dd["where"]["LL_lat"])
    ll_lon = float(dd["where"]["LL_lon"])
    xscale = float(dd["where"]["xscale"])
    yscale = float(dd["where"]["yscale"])
    ysize  = int(dd["where"]["ysize"])

    x,    y    = p(lon,    lat)
    x_ll, y_ll = p(ll_lon, ll_lat)
    col = int(round((x - x_ll) / xscale))
    row = int(ysize - 1 - round((y - y_ll) / yscale))
    return row, col


@pytest.mark.wradlib
def test_location_value_matches_wradlib():
    """For a curated fixture location, our (row,col) and value match wradlib+pyproj."""
    wrl = pytest.importorskip("wradlib")

    if not FIXTURE_HDF5.exists() or not FIXTURE_META.exists():
        pytest.skip("Fixture files not found — run scripts/create_fixture.py first")

    meta       = json.loads(FIXTURE_META.read_text())
    lat, lon   = meta["lat"], meta["lon"]
    hdf5_bytes = FIXTURE_HDF5.read_bytes()

    # --- our parser ---
    data_ours, where = read_odim_composite(io.BytesIO(hdf5_bytes))
    row_ours, col_ours = get_rs_grid_index(lat, lon, where)
    value_ours = float(data_ours[row_ours, col_ours])

    # --- wradlib parser ---
    dd       = wrl.io.read_opera_hdf5(io.BytesIO(hdf5_bytes))
    data_wrl = _apply_wradlib_scaling(dd)

    # --- pyproj reference index ---
    row_ref, col_ref = _pyproj_grid_index(dd, lat, lon)

    # Our ellipsoidal formula matches pyproj exactly — no pixel tolerance needed.
    assert row_ours == row_ref, (
        f"Row mismatch: ours={row_ours}, pyproj={row_ref}"
    )
    assert col_ours == col_ref, (
        f"Col mismatch: ours={col_ours}, pyproj={col_ref}"
    )

    # Parsed value at the rain cell must equal wradlib.
    value_ours = float(data_ours[row_ours, col_ours])
    assert value_ours == pytest.approx(float(data_wrl[row_ours, col_ours]))

    # The fixture was chosen to have actual precipitation at this cell.
    assert not np.isnan(value_ours), "Fixture rain cell should not be NaN"
    assert value_ours > 0.0, f"Expected precipitation > 0, got {value_ours}"


@pytest.mark.wradlib
def test_full_array_matches_wradlib():
    """All values in the fixture match wradlib element-by-element."""
    wrl = pytest.importorskip("wradlib")

    if not FIXTURE_HDF5.exists():
        pytest.skip("Fixture file not found — run scripts/create_fixture.py first")

    hdf5_bytes = FIXTURE_HDF5.read_bytes()
    data_ours, _ = read_odim_composite(io.BytesIO(hdf5_bytes))

    dd       = wrl.io.read_opera_hdf5(io.BytesIO(hdf5_bytes))
    data_wrl = _apply_wradlib_scaling(dd)

    # NaN positions must match
    np.testing.assert_array_equal(np.isnan(data_ours), np.isnan(data_wrl))
    # Non-NaN values must be identical
    mask = ~np.isnan(data_ours)
    np.testing.assert_array_equal(data_ours[mask], data_wrl[mask])


# ===========================================================================
# Group 6 — live integration test (downloads current RS tar from DWD)
# ===========================================================================

@pytest.mark.integration
def test_live_rs_file():
    """Download the current RS tar and verify our parser handles a real DWD file."""
    import tarfile
    from datetime import datetime, timedelta, timezone

    import requests

    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    ts  = now.replace(second=0, microsecond=0)
    ts -= timedelta(minutes=ts.minute % 5)
    fname = f"composite_rs_{ts.strftime('%Y%m%d_%H%M')}"
    url   = f"https://opendata.dwd.de/weather/radar/composite/rs/{fname}.tar"

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    with tarfile.open(fileobj=io.BytesIO(resp.content)) as tf:
        hdf5_bytes = tf.extractfile(f"{fname}_000-hd5").read()

    data, where = read_odim_composite(io.BytesIO(hdf5_bytes))

    assert data.shape == (1200, 1100)
    assert data.dtype == np.float32
    assert "xscale" in where
    assert "yscale" in where
