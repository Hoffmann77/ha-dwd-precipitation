"""wradlib comparison tests (RS / ODIM_H5) — verify our parser matches the reference."""

import io
import json
from pathlib import Path

import numpy as np
import pytest

from radar.odim import get_rs_grid_index, read_odim_composite

FIXTURE_HDF5 = Path(__file__).parent.parent / "fixtures" / "composite_rs_sample.hd5"
FIXTURE_META = Path(__file__).parent.parent / "fixtures" / "fixture_metadata.json"


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
    from pyproj import Proj

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

    data_ours, _dataset_what = read_odim_composite(io.BytesIO(hdf5_bytes))
    # read_odim_composite no longer returns the /where grid dict; the RS grid is
    # fixed, so get_rs_grid_index uses its built-in RS_WHERE by default.
    row_ours, col_ours = get_rs_grid_index(lat, lon)
    value_ours = float(data_ours[row_ours, col_ours])

    dd       = wrl.io.read_opera_hdf5(io.BytesIO(hdf5_bytes))
    data_wrl = _apply_wradlib_scaling(dd)

    row_ref, col_ref = _pyproj_grid_index(dd, lat, lon)

    assert row_ours == row_ref, f"Row mismatch: ours={row_ours}, pyproj={row_ref}"
    assert col_ours == col_ref, f"Col mismatch: ours={col_ours}, pyproj={col_ref}"

    value_ours = float(data_ours[row_ours, col_ours])
    assert value_ours == pytest.approx(float(data_wrl[row_ours, col_ours]))

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

    np.testing.assert_array_equal(np.isnan(data_ours), np.isnan(data_wrl))
    mask = ~np.isnan(data_ours)
    np.testing.assert_array_equal(data_ours[mask], data_wrl[mask])
