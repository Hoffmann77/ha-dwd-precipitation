"""ODIM_H5 reader for DWD's Cartesian composites (RS, RV, HymecNG, RW, SF).

The integration reads one cell: the one holding a location, on the grid the
file itself describes in its /where group (radar/grid.py). The whole-grid
readers are the oracle for the test tiers and scripts/.

"""

import numpy as np
import h5py

from .grid import Grid, UnsupportedGrid, grid_from_where


def _normalise_attr_value(value):
    """Return an HDF5 attribute as a plain Python value.

    h5py hands strings over as bytes and numbers as numpy scalars; this turns
    them into str, int and float, so the attribute dicts the readers return can
    be compared and stored like any other.

    """
    if hasattr(value, "decode"):
        return value.decode()
    if hasattr(value, "item"):
        return value.item()
    return value


def _resolve_hard(parent, path: str):
    """Walk ``path`` in the file, following hard links only.

    ``parent`` is the open file (or a group in it), ``path`` a slash-separated
    path such as "dataset1/data1/data". A soft or external link is refused with
    ValueError before libhdf5 follows it, so a crafted file cannot redirect a
    read to another object, or to another file on disk. DWD's files use plain
    hard links only.

    """
    obj = parent
    for part in path.split("/"):
        if not part:
            continue
        link_cls = getattr(obj.get(part, getclass=True, getlink=True), "__name__", None)
        if link_cls != "HardLink":
            raise ValueError(
                f"Refusing to follow non-hard link ({link_cls}) at {part!r} in {path!r}"
            )
        obj = obj[part]
    return obj


def _require_plain_dataset(dset, expected_shape=None):
    """Return ``dset`` if it is a safe in-file dataset, else raise ValueError.

    Refuses anything that is not a dataset, virtual datasets and data stored in
    external files, which could pull bytes from outside the opened buffer, and
    any shape other than ``expected_shape`` when one is given.

    """
    if not isinstance(dset, h5py.Dataset):
        raise ValueError("Expected an HDF5 dataset for the composite payload")
    if dset.is_virtual:
        raise ValueError("Refusing to read a virtual dataset")
    if dset.external:
        raise ValueError("Refusing to read a dataset backed by external files")
    if expected_shape is not None and dset.shape != tuple(expected_shape):
        raise ValueError(
            f"Unexpected composite shape {dset.shape}, expected {tuple(expected_shape)}"
        )
    return dset


def _open_composite(hf, dataset: str, moment: str, expected_shape):
    """Return a composite's payload dataset and the attributes describing it.

    ODIM_H5 keeps each grid in ``<dataset>/<moment>/data`` ("dataset1/data1" in
    DWD's files). Opens it with the hardening checks, along with the dataset's
    ``what`` group (validity window, product) and the moment's (gain, offset,
    nodata), both as plain dicts. The payload is not read yet.

    """
    dataset_what = {
        k: _normalise_attr_value(v)
        for k, v in _resolve_hard(hf, f"{dataset}/what").attrs.items()
    }
    what = {
        k: _normalise_attr_value(v)
        for k, v in _resolve_hard(hf, f"{dataset}/{moment}/what").attrs.items()
    }
    dset = _require_plain_dataset(
        _resolve_hard(hf, f"{dataset}/{moment}/data"), expected_shape
    )
    return dset, dataset_what, what


def _file_grid(hf) -> Grid:
    """Return the grid the open file's /where group describes.

    Every reader finds its cell on this grid rather than on a copy of DWD's
    grid in the code (ADR 0010). Raises UnsupportedGrid for a file without
    /where, or one this version cannot place a location on.

    """
    if "where" not in hf:
        raise UnsupportedGrid("the file has no /where group")
    attrs = _resolve_hard(hf, "where").attrs
    return grid_from_where({k: _normalise_attr_value(v) for k, v in attrs.items()})


def _cell_of(hf, lat: float, lon: float, dataset: str, moment: str):
    """Return the raw cell holding a location, and the attributes describing it.

    The cell is found on the file's own grid (OutsideGrid when the location is
    not on it), and the payload must be exactly that grid, which also bounds
    what the read inflates. Returns the cell as a 1 x 1 array of stored counts,
    the dataset's ``what`` and the moment's ``what``.

    """
    grid = _file_grid(hf)
    row, col = grid.cell(lat, lon)
    dset, dataset_what, what = _open_composite(hf, dataset, moment, grid.shape)
    return dset[row:row + 1, col:col + 1], dataset_what, what


def _scale(raw, what):
    """Turn raw ACRR counts into mm: nodata -> NaN, undetect -> 0.0.

    ACRR is accumulated precipitation, stored as integer counts; the value in
    mm is count * gain + offset, from the moment's ``what``. "nodata" (outside
    coverage) becomes NaN; "undetect" (radar scanned, nothing found) becomes a
    dry 0.0 rather than the offset's -0.001 mm. Works on any array shape.

    """
    gain     = float(what["gain"])
    offset   = float(what["offset"])
    nodata   = int(what["nodata"])
    undetect = int(round(float(what.get("undetect", 0))))

    data = raw.astype(np.float32) * gain + offset
    data[raw == nodata]   = np.nan
    data[raw == undetect] = 0.0
    return data


def read_odim_grid(fileobj) -> Grid:
    """Return the grid an ODIM_H5 file describes.

    ``fileobj`` is a path or a file-like object. For the test tiers and
    scripts/; the integration's readers find the grid themselves.

    """
    with h5py.File(fileobj, "r") as hf:
        return _file_grid(hf)


def read_odim_composite(
    fileobj,
    dataset: str = "dataset1",
    moment: str = "data1",
    expected_shape=None,
):
    """Read a whole Cartesian ODIM_H5 composite, in mm.

    Returns the float32 grid (NaN for no data, 0.0 for undetect) and its
    /dataset/what attributes, under the same untrusted-file checks as the cell
    reader. No runtime caller: the oracle the test tiers and scripts/ compare
    the cell reader against.

    """
    with h5py.File(fileobj, "r") as hf:
        dset, dataset_what, what = _open_composite(hf, dataset, moment, expected_shape)
        raw = dset[:]

    return _scale(raw, what), dataset_what


def read_odim_composite_at(
    fileobj,
    lat: float,
    lon: float,
    dataset: str = "dataset1",
    moment: str = "data1",
):
    """Read the cell holding (lat, lon) from a Cartesian ODIM_H5 composite.

    What every amount product (RS, RV, RW, SF) reads per release. Returns the
    cell's value in mm, the value read_odim_composite would hold there (NaN for
    no data), and the dataset's ``what`` attributes (validity window, product).
    The cell is found on the file's own grid. libhdf5 still inflates the whole
    grid; reading one cell saves scaling and masking 1.3 million of them.

    """
    with h5py.File(fileobj, "r") as hf:
        raw, dataset_what, what = _cell_of(hf, lat, lon, dataset, moment)

    return _scale(raw, what)[0, 0], dataset_what


def read_odim_classification(
    fileobj,
    dataset: str = "dataset1",
    moment: str = "data1",
    expected_shape=None,
):
    """Read a whole classification composite (HymecNG), unscaled.

    The cells are precipitation-type class indices (0 no precipitation, 3 rain,
    7 snow, ...), returned as stored, together with the dataset's ``what`` and
    the moment's ``what``, which says which values mean "no data" and "nothing
    detected". For the test tiers; HymecNG reads one cell with
    read_odim_classification_at.

    """
    with h5py.File(fileobj, "r") as hf:
        dset, dataset_what, moment_what = _open_composite(
            hf, dataset, moment, expected_shape
        )
        raw = dset[:]

    return raw, dataset_what, moment_what


def read_odim_classification_at(
    fileobj,
    lat: float,
    lon: float,
    dataset: str = "dataset1",
    moment: str = "data1",
):
    """Read the class index of the cell holding (lat, lon).

    From a classification composite (HymecNG), on the file's own grid. Returns
    the index as an int, the dataset's ``what`` and the moment's ``what``,
    which says which values mean "no data" and "nothing detected".

    """
    with h5py.File(fileobj, "r") as hf:
        raw, dataset_what, moment_what = _cell_of(hf, lat, lon, dataset, moment)

    return int(raw[0, 0]), dataset_what, moment_what
