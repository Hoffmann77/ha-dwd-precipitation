"""Parser unit tests for radar/odim.py — no HA, no wradlib, no network."""

import numpy as np
import pytest

from radar.odim import (
    RS_WHERE,
    _lonlat_to_xy,
    _parse_proj_param,
    get_rs_grid_index,
    read_odim_composite,
)

from tests.factories.odim import make_odim_h5

_PROJDEF = RS_WHERE["projdef"]
_X_0 = 543196.83521776402
_Y_0 = 3622588.8619310022


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
    buf = make_odim_h5()
    return read_odim_composite(buf)


def test_scaling(parsed_synthetic):
    data, _ = parsed_synthetic
    non_nan = data[~np.isnan(data)]
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


def test_dataset_what_keys(parsed_synthetic):
    """read_odim_composite returns the /dataset/what group — the timestamp/product
    metadata the products layer consumes for source_timestamp and the data window.
    """
    _, dataset_what = parsed_synthetic
    assert "startdate" in dataset_what
    assert "starttime" in dataset_what
    assert "enddate" in dataset_what
    assert "endtime" in dataset_what
    assert dataset_what.get("prodname") or dataset_what.get("product")


def test_bytes_projdef_roundtrip():
    """projdef stored as bytes in the HDF5 must parse without error."""
    buf = make_odim_h5(projdef_as_bytes=True)
    data, _dataset_what = read_odim_composite(buf)
    assert data.shape == (5, 5)
    assert not np.isnan(data[1, 0])
