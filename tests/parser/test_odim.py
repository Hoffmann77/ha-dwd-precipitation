"""Parser unit tests for radar/odim.py — no HA, no wradlib, no network.

The grid lookup itself is tested in test_grid.py; here, the readers.
"""

import io

import h5py
import numpy as np
import pytest

from radar.grid import OutsideGrid, UnsupportedGrid
from radar.odim import (
    _parse_nodes,
    read_odim_classification,
    read_odim_classification_at,
    read_odim_classification_near,
    read_odim_composite,
    read_odim_composite_at,
    read_odim_grid,
)

from tests.factories.odim import (
    DE1200_WHERE,
    make_hymecng_h5,
    make_odim_external_link,
    make_odim_h5,
    make_odim_soft_link,
    make_odim_virtual_dataset,
)
from tests.factories.real import real_cells, real_member, real_release

DE1200_SHAPE = (DE1200_WHERE["ysize"], DE1200_WHERE["xsize"])


def _locations(buf) -> dict[tuple[int, int], tuple[float, float]]:
    """Return one (lat, lon) inside every cell of a small synthetic grid.

    The factories put their grid at DE1200's lower-left corner; a mesh of
    locations around it finds each cell (the grid is rotated against the
    meridians there, so the mesh starts a little west and south).
    """
    grid = read_odim_grid(buf)
    buf.seek(0)
    found: dict[tuple[int, int], tuple[float, float]] = {}
    for i in range(80):
        for j in range(120):
            lat = DE1200_WHERE["LL_lat"] - 0.02 + i * 0.002
            lon = DE1200_WHERE["LL_lon"] - 0.02 + j * 0.002
            try:
                found.setdefault(grid.cell(lat, lon), (lat, lon))
            except OutsideGrid:
                pass
    assert len(found) == grid.ysize * grid.xsize, "every cell should be found"
    return found


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


# ===========================================================================
# Group 5 — untrusted-file hardening
# ===========================================================================

def test_external_link_payload_rejected():
    """A payload dataset that is an HDF5 external link must be refused, not followed."""
    with pytest.raises(ValueError, match="non-hard link"):
        read_odim_composite(make_odim_external_link())


def test_soft_link_payload_rejected():
    """A payload dataset that is a soft link must be refused."""
    with pytest.raises(ValueError, match="non-hard link"):
        read_odim_composite(make_odim_soft_link())


def test_virtual_dataset_rejected():
    """A virtual dataset (data sourced from other files) must be refused."""
    with pytest.raises(ValueError, match="virtual dataset"):
        read_odim_composite(make_odim_virtual_dataset())


def test_unexpected_shape_rejected():
    """When expected_shape is pinned, a wrong-sized grid is refused before the read."""
    buf = make_odim_h5(shape=(5, 5))
    with pytest.raises(ValueError, match="Unexpected composite shape"):
        read_odim_composite(buf, expected_shape=DE1200_SHAPE)


def test_matching_shape_accepted():
    """A file matching the pinned shape parses normally."""
    buf = make_odim_h5(shape=(4, 6))
    data, _ = read_odim_composite(buf, expected_shape=(4, 6))
    assert data.shape == (4, 6)


# ===========================================================================
# Group 6 — read_odim_classification (HymecNG)
# ===========================================================================

def test_classification_returns_unscaled_class_indices():
    """Class indices are returned as-is (no gain/offset scaling)."""
    raw, dataset_what, moment_what = read_odim_classification(make_hymecng_h5(fill=7))
    assert raw.shape == (5, 5)
    assert int(raw[2, 2]) == 7  # SNOW, unscaled
    assert moment_what["quantity"] == "CLASS"
    assert int(round(moment_what["nodata"])) == 255
    assert int(round(moment_what["undetect"])) == 254


def test_classification_preserves_nodata_and_undetect_sentinels():
    """nodata/undetect cells keep their sentinel values (not coerced to 0/NaN)."""
    raw, _dataset_what, moment_what = read_odim_classification(make_hymecng_h5())
    assert int(raw[0, 0]) == int(round(moment_what["nodata"]))
    assert int(raw[0, 1]) == int(round(moment_what["undetect"]))


def test_classification_returns_validity_window():
    _raw, dataset_what, _moment_what = read_odim_classification(make_hymecng_h5())
    assert dataset_what["enddate"] == "20260729"
    assert dataset_what["endtime"] == "173000"
    assert dataset_what.get("prodname") or dataset_what.get("product")


def test_classification_shape_pinning_rejects_wrong_size():
    with pytest.raises(ValueError, match="Unexpected composite shape"):
        read_odim_classification(make_hymecng_h5(shape=(5, 5)), expected_shape=DE1200_SHAPE)


def test_classification_cell_matches_the_grid():
    raw, dataset_what, moment_what = read_odim_classification(make_hymecng_h5())
    for (row, col), location in _locations(make_hymecng_h5()).items():
        value, cell_what, cell_moment = read_odim_classification_at(
            make_hymecng_h5(), *location
        )
        assert value == int(raw[row, col])
        assert (cell_what, cell_moment) == (dataset_what, moment_what)


def test_classification_location_off_the_grid_raises():
    with pytest.raises(OutsideGrid):
        read_odim_classification_at(make_hymecng_h5(), 52.52, 13.405)  # Berlin


# ===========================================================================
# read_odim_composite_at — one cell, same answer as the full-grid reader
# ===========================================================================

def _varied_odim_h5(shape=(6, 7)):
    """ODIM file with a distinct raw count per cell, plus nodata and undetect."""
    buf = make_odim_h5(shape=shape)
    with h5py.File(buf, "r+") as f:
        raw = np.arange(1, shape[0] * shape[1] + 1, dtype=np.uint32).reshape(shape) * 37
        raw[0, 0] = 4294967295  # nodata
        raw[0, 1] = 0           # undetect
        f["dataset1/data1/data"][...] = raw
    buf.seek(0)
    return buf


def _with_where(buf, **attrs):
    """Return ``buf`` with some /where attributes replaced."""
    with h5py.File(buf, "r+") as f:
        for key, value in attrs.items():
            f["where"].attrs[key] = value
    buf.seek(0)
    return buf


def test_cell_reader_matches_grid_reader_everywhere():
    grid, what = read_odim_composite(_varied_odim_h5())
    for (row, col), location in _locations(_varied_odim_h5()).items():
        value, cell_what = read_odim_composite_at(_varied_odim_h5(), *location)
        if np.isnan(grid[row, col]):
            assert np.isnan(value), (row, col)
        else:
            # Bit-identical, not approximately equal: the same float32 math.
            assert value == grid[row, col], (row, col)
            assert value.dtype == np.float32
        assert cell_what == what


def test_cell_reader_nodata_and_undetect():
    locations = _locations(_varied_odim_h5())
    assert np.isnan(read_odim_composite_at(_varied_odim_h5(), *locations[0, 0])[0])
    assert read_odim_composite_at(_varied_odim_h5(), *locations[0, 1])[0] == 0.0


def test_cell_reader_rejects_a_location_off_the_grid():
    with pytest.raises(OutsideGrid):
        read_odim_composite_at(_varied_odim_h5(), 52.52, 13.405)  # Berlin


def test_cell_reader_keeps_untrusted_input_checks():
    location = DE1200_WHERE["LL_lat"] + 0.01, DE1200_WHERE["LL_lon"] + 0.01
    with pytest.raises(ValueError, match="non-hard link"):
        read_odim_composite_at(make_odim_external_link(), *location)
    # The payload must be exactly the grid /where declares...
    with pytest.raises(ValueError, match="shape"):
        read_odim_composite_at(_with_where(make_odim_h5(shape=(5, 5)), ysize=6), *location)
    # ... and that grid no larger than a DWD composite, before anything is read.
    with pytest.raises(UnsupportedGrid):
        read_odim_composite_at(_with_where(make_odim_h5(), ysize=1_000_000), *location)


def test_cell_reader_needs_a_where_group():
    buf = make_odim_h5()
    with h5py.File(buf, "r+") as f:
        del f["where"]
    buf.seek(0)
    with pytest.raises(UnsupportedGrid):
        read_odim_composite_at(buf, 45.7, 3.6)


# --- real files (scripts/create_fixture.py --product rv|hymecng) ------------------


@pytest.mark.parametrize("kind", ["wet", "nodata"])
def test_real_rv_analysis_cell(kind):
    """A real RV analysis: the cell at a location, and its value in mm."""
    content, _ = real_member("rv")
    cell = real_cells("rv")[kind]
    assert read_odim_grid(io.BytesIO(content)).cell(cell["lat"], cell["lon"]) == (
        cell["row"],
        cell["col"],
    )

    value, what = read_odim_composite_at(io.BytesIO(content), cell["lat"], cell["lon"])
    if cell["value"] is None:
        assert np.isnan(value)
    else:
        assert float(value) == pytest.approx(cell["value"], abs=5e-4)
    # The analysis is the 5 minutes ending at the release.
    release = real_release("rv")
    assert (what["enddate"], what["endtime"]) == (f"{release:%Y%m%d}", f"{release:%H%M%S}")


@pytest.mark.parametrize("kind", ["wet", "undetect", "nodata"])
def test_real_hymecng_cell(kind):
    """A real HymecNG file: the raw class, undetect and nodata as stored."""
    content, _ = real_member("hymecng")
    cell = real_cells("hymecng")[kind]
    assert read_odim_grid(io.BytesIO(content)).cell(cell["lat"], cell["lon"]) == (
        cell["row"],
        cell["col"],
    )

    value, _, moment_what = read_odim_classification_at(
        io.BytesIO(content), cell["lat"], cell["lon"]
    )
    assert value == cell["value"]
    assert (int(moment_what["undetect"]), int(moment_what["nodata"])) == (254, 255)


@pytest.mark.parametrize("kind", ["wet", "undetect", "nodata"])
def test_real_hymecng_window_matches_the_whole_grid(kind):
    """The window around a location is the whole grid's square there, clipped."""
    content, _ = real_member("hymecng")
    cell = real_cells("hymecng")[kind]
    whole, _, _ = read_odim_classification(io.BytesIO(content))

    value, window, center, cell_m, _, moment_what = read_odim_classification_near(
        io.BytesIO(content), cell["lat"], cell["lon"], 5000
    )

    assert value == cell["value"]
    assert cell_m == (1000.0, 1000.0)
    row, col = cell["row"], cell["col"]
    r0, c0 = row - center[0], col - center[1]
    assert (r0, c0) == (max(row - 5, 0), max(col - 5, 0))
    assert window.shape == (min(row + 6, whole.shape[0]) - r0, min(col + 6, whole.shape[1]) - c0)
    np.testing.assert_array_equal(window, whole[r0:r0 + window.shape[0], c0:c0 + window.shape[1]])
    assert (int(moment_what["undetect"]), int(moment_what["nodata"])) == (254, 255)


# --- the radars a composite was built from (/how nodes) ----------------------

# The 17 German radars, as DWD lists them in /how nodes.
_DWD_NODES = (
    "deasb", "deboo", "dedrs", "deeis", "deess", "defbg", "defld", "dehnr",
    "deisn", "demem", "deneu", "denhb", "deoft", "depro", "deros", "detur", "deumd",
)


def _with_nodes(buf, nodes):
    """Return ``buf`` with a /how group listing ``nodes`` the way DWD does."""
    with h5py.File(buf, "r+") as f:
        f.create_group("how").attrs["nodes"] = np.bytes_(
            ",".join(f"'{node}'" for node in nodes).encode()
        )
    buf.seek(0)
    return buf


def test_parse_nodes_reads_dwds_quoted_list():
    assert _parse_nodes("'deasb','deboo', 'depro'") == ("deasb", "deboo", "depro")
    assert _parse_nodes("") == ()


def test_cell_readers_name_the_radars():
    """Both cell readers add the file's /how nodes to the dataset's what."""
    location = DE1200_WHERE["LL_lat"] + 0.01, DE1200_WHERE["LL_lon"] + 0.01
    _, what = read_odim_composite_at(_with_nodes(make_odim_h5(), ("deboo", "depro")), *location)
    assert what["nodes"] == ("deboo", "depro")

    _, what, _ = read_odim_classification_at(
        _with_nodes(make_hymecng_h5(), ("deasb",)), *location
    )
    assert what["nodes"] == ("deasb",)


def test_a_file_without_nodes_names_no_radars():
    location = DE1200_WHERE["LL_lat"] + 0.01, DE1200_WHERE["LL_lon"] + 0.01
    _, what = read_odim_composite_at(make_odim_h5(), *location)
    assert "nodes" not in what


@pytest.mark.parametrize("product", ["rv", "hymecng"])
def test_real_files_name_their_radars(product):
    """DWD's own files list the radars they were built from."""
    content, _ = real_member(product)
    cell = real_cells(product)["wet"]
    reader = read_odim_composite_at if product == "rv" else read_odim_classification_at
    what = reader(io.BytesIO(content), cell["lat"], cell["lon"])[1]
    assert sorted(what["nodes"]) == sorted(_DWD_NODES)
