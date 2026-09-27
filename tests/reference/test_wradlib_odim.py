"""wradlib comparison tests (RS / ODIM_H5) — verify our parser matches the reference.

The grid-lookup tests resolve locations with wradlib's own DE1200 grid
(``create_crs("dwd-radolan-wgs84-de1200")`` + ``get_radolan_coordinates``), not
with a reimplementation of our arithmetic: a reference that repeats our
convention cannot catch a mistake in it. wradlib's grid is in turn pinned to
the fixture file's corner attributes, so all three have to agree.
"""

import io
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

pytest.importorskip("wradlib")

from radar.odim import RS_WHERE, get_rs_grid_index, read_odim_composite, rs_grid_contains  # noqa: E402
from tests.wradlib_ref import (  # noqa: E402
    de1200_cell,
    de1200_cells,
    de1200_edge_grid_lonlat,
    read_odim,
    scale_odim,
)

FIXTURE_HDF5 = Path(__file__).parent.parent / "fixtures" / "composite_rs_sample.hd5"
FIXTURE_META = Path(__file__).parent.parent / "fixtures" / "fixture_metadata.json"

YSIZE, XSIZE = RS_WHERE["ysize"], RS_WHERE["xsize"]

# Named locations, so a failure reads as a place rather than a random draw.
CITIES = {
    "Hamburg": (53.5511, 9.9937),
    "Berlin": (52.5200, 13.4050),
    "Freiburg": (47.9990, 7.8421),
    "Munich": (48.1374, 11.5755),
    "Cologne": (50.9375, 6.9603),
}


def _fixture_where():
    if not FIXTURE_HDF5.exists():
        pytest.skip("Fixture file not found — run scripts/create_fixture.py first")
    with h5py.File(FIXTURE_HDF5, "r") as f:
        return {
            k: v.decode() if hasattr(v, "decode") else v.item()
            for k, v in f["where"].attrs.items()
        }


@pytest.mark.wradlib
def test_wradlib_grid_edges_are_the_file_corners():
    """wradlib's DE1200 outer edges are exactly the file's corner attributes.

    ODIM defines LL/UL/UR/LR as the outer corners of the edge pixels. This ties
    the reference grid to what DWD actually publishes, and RS_WHERE to both.
    """
    where = _fixture_where()
    edges = de1200_edge_grid_lonlat()  # (ysize + 1, xsize + 1, [lon, lat]), south-up
    corners = {"LL": edges[0, 0], "LR": edges[0, -1], "UL": edges[-1, 0], "UR": edges[-1, -1]}
    for name, (lon, lat) in corners.items():
        assert lon == pytest.approx(where[f"{name}_lon"], abs=1e-8), name
        assert lat == pytest.approx(where[f"{name}_lat"], abs=1e-8), name

    for key in ("LL_lat", "LL_lon", "xscale", "yscale", "xsize", "ysize"):
        assert RS_WHERE[key] == pytest.approx(where[key], abs=1e-12), key
    assert RS_WHERE["projdef"] == where["projdef"]


@pytest.mark.wradlib
def test_grid_index_matches_wradlib():
    """Our (row, col) equals wradlib's for random locations across the grid.

    Rounding from the corner instead of flooring disagrees with wradlib for
    about three points in four, so a half-cell error cannot slip through.
    """
    rng = np.random.default_rng(20260927)
    lats = np.concatenate([rng.uniform(46.0, 55.5, 5000), [c[0] for c in CITIES.values()]])
    lons = np.concatenate([rng.uniform(4.0, 16.0, 5000), [c[1] for c in CITIES.values()]])
    rows, cols = de1200_cells(lats, lons)

    inside = (rows >= 0) & (rows < YSIZE) & (cols >= 0) & (cols < XSIZE)
    assert inside.sum() > 4500, "sample should fall mostly inside the grid"

    mismatches = [
        (float(lat), float(lon), get_rs_grid_index(lat, lon), (int(r), int(c)))
        for lat, lon, r, c in zip(lats[inside], lons[inside], rows[inside], cols[inside])
        if get_rs_grid_index(lat, lon) != (r, c)
    ]
    assert not mismatches, (
        f"{len(mismatches)} of {inside.sum()} locations differ from wradlib, "
        f"e.g. (lat, lon, ours, wradlib) = {mismatches[:3]}"
    )


@pytest.mark.parametrize("city", CITIES)
@pytest.mark.wradlib
def test_city_cells_match_wradlib(city):
    lat, lon = CITIES[city]
    assert get_rs_grid_index(lat, lon) == de1200_cell(lat, lon)


@pytest.mark.wradlib
def test_grid_contains_matches_wradlib_at_the_edges():
    """rs_grid_contains agrees with wradlib in a band straddling every edge."""
    edges = de1200_edge_grid_lonlat()
    border = np.concatenate([edges[0], edges[-1], edges[:, 0], edges[:, -1]])
    rng = np.random.default_rng(7)
    # Jitter each outer-edge point by up to ~1.5 km (0.02 deg) either way.
    lons = border[:, 0] + rng.uniform(-0.02, 0.02, len(border))
    lats = border[:, 1] + rng.uniform(-0.02, 0.02, len(border))
    rows, cols = de1200_cells(lats, lons)
    expected = (rows >= 0) & (rows < YSIZE) & (cols >= 0) & (cols < XSIZE)
    assert 0 < expected.sum() < len(expected), "band should straddle the edge"

    ours = np.array([rs_grid_contains(lat, lon) for lat, lon in zip(lats, lons)])
    wrong = np.flatnonzero(ours != expected)
    assert not wrong.size, (
        f"{wrong.size} edge points disagree, e.g. lat/lon "
        f"{list(zip(lats[wrong[:3]], lons[wrong[:3]]))}"
    )


@pytest.mark.wradlib
def test_location_value_matches_wradlib():
    """For the curated fixture location, our (row, col) and value match wradlib."""
    if not FIXTURE_HDF5.exists() or not FIXTURE_META.exists():
        pytest.skip("Fixture files not found — run scripts/create_fixture.py first")

    meta       = json.loads(FIXTURE_META.read_text())
    lat, lon   = meta["lat"], meta["lon"]
    hdf5_bytes = FIXTURE_HDF5.read_bytes()

    data_ours, _dataset_what = read_odim_composite(io.BytesIO(hdf5_bytes))
    # read_odim_composite does not return the /where grid dict; the RS grid is
    # fixed, so get_rs_grid_index uses its built-in RS_WHERE by default.
    row_ours, col_ours = get_rs_grid_index(lat, lon)

    assert (row_ours, col_ours) == de1200_cell(lat, lon)
    assert (row_ours, col_ours) == (meta["grid_row"], meta["grid_col"])

    data_wrl = scale_odim(*read_odim(hdf5_bytes))

    value_ours = float(data_ours[row_ours, col_ours])
    assert value_ours == pytest.approx(float(data_wrl[row_ours, col_ours]))
    assert value_ours == pytest.approx(meta["expected_mm"])

    assert not np.isnan(value_ours), "Fixture rain cell should not be NaN"
    assert value_ours > 0.0, f"Expected precipitation > 0, got {value_ours}"


@pytest.mark.wradlib
def test_full_array_matches_wradlib():
    """All values in the fixture match wradlib element-by-element."""
    if not FIXTURE_HDF5.exists():
        pytest.skip("Fixture file not found — run scripts/create_fixture.py first")

    hdf5_bytes = FIXTURE_HDF5.read_bytes()
    data_ours, _ = read_odim_composite(io.BytesIO(hdf5_bytes))

    data_wrl = scale_odim(*read_odim(hdf5_bytes))

    np.testing.assert_array_equal(np.isnan(data_ours), np.isnan(data_wrl))
    mask = ~np.isnan(data_ours)
    np.testing.assert_array_equal(data_ours[mask], data_wrl[mask])
