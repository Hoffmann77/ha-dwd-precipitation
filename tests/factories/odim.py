"""Synthetic ODIM_H5 / RS-tar builders shared across the test suite."""

from __future__ import annotations

import io
import tarfile
from datetime import datetime

import h5py
import numpy as np

from radar.odim import RS_WHERE

_PROJDEF = RS_WHERE["projdef"]


def make_odim_h5(shape=(5, 5), gain=0.001, offset=-0.001, nodata=4294967295,
                 projdef_as_bytes=False, fill_raw=1001):
    """Build a minimal ODIM_H5 file in memory matching the real DWD RS format.

    fill_raw=1001 → physical value 1001*0.001 + (-0.001) = 1.0 mm.
    Cell [0, 0] is always set to nodata; cell [0, 1] to undetect (0).
    Returns a rewound BytesIO ready for read_odim_composite().
    """
    buf = io.BytesIO()
    with h5py.File(buf, "w") as f:
        rw = f.create_group("what")
        rw.attrs["version"] = np.bytes_(b"H5rad 2.3")
        rw.attrs["date"]    = np.bytes_(b"20260518")
        rw.attrs["time"]    = np.bytes_(b"160000")
        rw.attrs["object"]  = np.bytes_(b"COMP")
        rw.attrs["source"]  = np.bytes_(b"ORG:78,CTY:616")

        w = f.create_group("where")
        projdef = np.bytes_(_PROJDEF) if projdef_as_bytes else _PROJDEF
        w.attrs.create("projdef", data=projdef)
        w.attrs["xsize"]  = np.int64(shape[1])
        w.attrs["ysize"]  = np.int64(shape[0])
        w.attrs["xscale"] = np.float64(1000.0)
        w.attrs["yscale"] = np.float64(1000.0)
        w.attrs["LL_lat"] = np.float64(RS_WHERE["LL_lat"])
        w.attrs["LL_lon"] = np.float64(RS_WHERE["LL_lon"])

        d1w = f.create_group("dataset1/what")
        d1w.attrs["product"]   = np.bytes_(b"MAX")
        d1w.attrs["prodname"]  = np.bytes_(b"RS_top_view")
        d1w.attrs["startdate"] = np.bytes_(b"20260518")
        d1w.attrs["starttime"] = np.bytes_(b"150000")
        d1w.attrs["enddate"]   = np.bytes_(b"20260518")
        d1w.attrs["endtime"]   = np.bytes_(b"160000")

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


def make_rs_tar(ts: datetime) -> bytes:
    """Build an in-memory RS tar with the three lead-time members (dummy payloads).

    Members are named like the real archive; contents are placeholders because
    callers patch read_odim_composite to inject the parsed values/metadata.
    """
    prefix = f"composite_rs_{ts.strftime('%Y%m%d_%H%M')}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for suffix in ("000", "060", "120"):
            payload = suffix.encode()
            info = tarfile.TarInfo(name=f"{prefix}_{suffix}-hd5")
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()
