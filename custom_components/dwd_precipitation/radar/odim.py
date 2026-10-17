"""ODIM_H5 reader for DWD's Cartesian composites (RS, RV, HymecNG, RW, SF).

The integration reads one cell: the one holding a location, on the grid the
file itself describes in its /where group (radar/grid.py). The whole-grid
readers are the oracle for the test tiers and scripts/.
"""

import numpy as np
import h5py

from .grid import Grid, UnsupportedGrid, grid_from_where


def _normalise_attr_value(value):
    """Return HDF5 attributes as plain Python values."""
    if hasattr(value, "decode"):
        return value.decode()
    if hasattr(value, "item"):
        return value.item()
    return value


def _resolve_hard(parent, path: str):
    """Traverse ``path`` under ``parent``, requiring every component to be a hard link.

    ``get(..., getclass=True, getlink=True)`` returns the *link class* without
    dereferencing it, so a soft or external link is rejected before libhdf5 ever
    follows it. This closes the HDF5 external-link / soft-link vector: a crafted
    file could otherwise redirect a path to another object — or, via an external
    link, to another file on disk — the moment we index into it. DWD RS/RV
    composites are self-contained with plain hard links only, so nothing
    legitimate is rejected.
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
    """Return ``dset`` if it is a safe in-file dataset, else raise.

    Rejects virtual datasets and datasets whose raw data lives in external files
    — both let a crafted file pull bytes from outside the buffer we opened — and,
    when ``expected_shape`` is given, any unexpected shape (which also bounds the
    allocation the subsequent read performs).
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
    """Return ``(dset, dataset_what, what)`` for a composite's payload, checked."""
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
    """Return the grid the open file's /where group describes."""
    if "where" not in hf:
        raise UnsupportedGrid("the file has no /where group")
    attrs = _resolve_hard(hf, "where").attrs
    return grid_from_where({k: _normalise_attr_value(v) for k, v in attrs.items()})


def _cell_of(hf, lat: float, lon: float, dataset: str, moment: str):
    """Return ``(raw 1x1 slice, dataset_what, what)`` of the cell holding a location.

    The cell is found on the file's own grid, and the payload must be exactly
    that grid, which also bounds what the read inflates. Raises OutsideGrid for
    a location off the grid, UnsupportedGrid for a grid this version cannot
    compute.
    """
    grid = _file_grid(hf)
    row, col = grid.cell(lat, lon)
    dset, dataset_what, what = _open_composite(hf, dataset, moment, grid.shape)
    return dset[row:row + 1, col:col + 1], dataset_what, what


def _scale(raw, what):
    """Turn raw ACRR counts into mm: nodata → NaN, undetect → 0.0."""
    gain     = float(what["gain"])
    offset   = float(what["offset"])
    nodata   = int(what["nodata"])
    undetect = int(round(float(what.get("undetect", 0))))

    data = raw.astype(np.float32) * gain + offset
    data[raw == nodata]   = np.nan
    data[raw == undetect] = 0.0
    return data


def read_odim_grid(fileobj) -> Grid:
    """Return the grid an ODIM_H5 file describes (for the test tiers and scripts/)."""
    with h5py.File(fileobj, "r") as hf:
        return _file_grid(hf)


def read_odim_composite(
    fileobj,
    dataset: str = "dataset1",
    moment: str = "data1",
    expected_shape=None,
):
    """Read a Cartesian ODIM_H5 composite, the whole grid.

    No runtime caller: the integration reads one cell
    (:func:`read_odim_composite_at`). This is the oracle the test tiers and
    scripts/ compare against.

    Returns (data, dataset_what) where data is a float32 array and dataset_what
    is the normalised /dataset/what attribute dict.
    nodata cells (outside radar range / masked) → NaN.
    undetect cells (radar scanned, zero precipitation detected) → 0.0.

    The file is treated as untrusted input: every path is walked hard-link-only
    and the payload dataset must be a plain in-file array (no virtual/external
    storage). Pass ``expected_shape`` (rows, cols) to also pin the grid size,
    which bounds the array allocation.
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

    Returns (value, dataset_what): the same float32 value
    :func:`read_odim_composite` would hold at that cell (NaN for nodata), with
    the same untrusted-input checks. DWD stores the whole grid as a single
    compressed chunk, so libhdf5 still inflates it; what this saves is scaling
    and masking 1.3 million cells to keep one, which is most of the cost.
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
    """Read a Cartesian ODIM_H5 *classification* composite (e.g. HymecNG).

    The whole grid, for the test tiers; HymecNG reads one cell with
    :func:`read_odim_classification_at`.

    Unlike :func:`read_odim_composite`, the payload holds a discrete class index
    (a precipitation-type category) rather than a physical quantity, so it is
    returned unscaled. Returns ``(raw, dataset_what, moment_what)``:

    * ``raw`` — the integer class-index grid (as stored, dtype preserved),
    * ``dataset_what`` — the ``/dataset/what`` attributes (validity window),
    * ``moment_what`` — the ``/dataset/data/what`` attributes, including
      ``nodata`` and ``undetect`` so the caller can distinguish "outside
      coverage" from "scanned, no precipitation".

    The file is treated as untrusted input with the same hard-link-only,
    plain-dataset, shape-pinned checks as :func:`read_odim_composite`.
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
    """Read the class index of the cell holding (lat, lon) from a classification composite.

    Returns ``(value, dataset_what, moment_what)``: the class index
    :func:`read_odim_classification` would hold at that cell, as an int, with
    the same untrusted-input checks.
    """
    with h5py.File(fileobj, "r") as hf:
        raw, dataset_what, moment_what = _cell_of(hf, lat, lon, dataset, moment)

    return int(raw[0, 0]), dataset_what, moment_what
