#!/usr/bin/env python
# Copyright (c) 2011-2023, wradlib developers.
# Distributed under the MIT License. See LICENSE.txt for more info.

"""
RADOLAN and DX Data I/O
^^^^^^^^^^^^^^^^^^^^^^^
Reading DX and RADOLAN data from German Weather Service

Warning
-------
Additionally to the binary composite formats DWD also provides data in ASCII
format, which have a very limited header and need to extract product and
datetime from the filename. Use on your own risk.


.. autosummary::
   :nosignatures:
   :toctree: generated/

   {}

"""

__all__ = [
    "read_dx",
    "read_radolan_composite",
    "get_radolan_filehandle",
    "read_radolan_header",
    "parse_dwd_composite_header",
    "read_radolan_binary_array",
    "decode_radolan_runlength_array",
]
__doc__ = __doc__.format("\n   ".join(__all__))

import datetime as dt
import io
import re

import numpy as np
# import xarray as xr



from . import util

# from wradlib.georef import projection, rect
# from wradlib.io.xarray import WradlibVariable

osr = util.import_optional("osgeo.osr")

# current DWD file naming pattern (2008) for example:
# raa00-dx_10488-200608050000-drs---bin
dwdpattern = re.compile("raa..-(..)[_-]([0-9]{5})-([0-9]*)-(.*?)---bin")
# RW_20221015-0050.asc
dwdascii = re.compile("(..)_([0-9]*)-([0-9]*).asc")

dwdradarmapping = {
    10103: "asb",
    10132: "boo",
    10488: "drs",
    10780: "eis",
    10410: "ess",
    10908: "fbg",
    10440: "fld",
    10339: "hnr",
    10873: "isn",
    10950: "mem",
    10557: "neu",
    10605: "nhb",
    10629: "oft",
    10392: "pro",
    10169: "ros",
    10832: "tur",
    10356: "umd",
}
dwdlocs = {
    "asb": {"height": 36.22, "lat": 53.564129, "lon": 6.748317},
    "boo": {"height": 124.56, "lat": 54.004381, "lon": 10.046899},
    "drs": {"height": 263.36, "lat": 51.124639, "lon": 13.768639},
    "eis": {"height": 799.08, "lat": 49.540667, "lon": 12.402788},
    "ess": {"height": 185.11, "lat": 51.405649, "lon": 6.967111},
    "fbg": {"height": 1516.1, "lat": 47.873611, "lon": 8.003611},
    "fld": {"height": 627.88, "lat": 51.311197, "lon": 8.801998},
    "hnr": {"height": 97.78, "lat": 52.460083, "lon": 9.694533},
    "isn": {"height": 677.77, "lat": 48.174705, "lon": 12.101779},
    "mem": {"height": 724.4, "lat": 48.042145, "lon": 10.219222},
    "neu": {"height": 879.65, "lat": 50.500114, "lon": 11.135034},
    "nhb": {"height": 585.85, "lat": 50.109656, "lon": 6.548328},
    "oft": {"height": 245.8, "lat": 49.984745, "lon": 8.712933},
    "pro": {"height": 193.92, "lat": 52.648667, "lon": 13.858212},
    "ros": {"height": 37.05, "lat": 54.17566, "lon": 12.058076},
    "tur": {"height": 767.62, "lat": 48.585379, "lon": 9.782675},
    "umd": {"height": 185.2, "lat": 52.160096, "lon": 11.176091},
}


class WradlibVariable:
    """Minimal variable wrapper."""

    def __init__(self, dims, data, attrs):
        self._dimensions = dims
        self._data = data
        self._attrs = attrs

    @property
    def dimensions(self):
        return self._dimensions

    @property
    def data(self):
        return self._data

    @property
    def attributes(self):
        return self._attrs


def _get_timestamp_from_filename(filename, *, pattern=dwdpattern):
    """Helper function doing the actual work of get_dx_timestamp"""
    if pattern is dwdpattern:
        time = pattern.search(filename).group(3)
        if len(time) == 10:
            time = "20" + time
    else:
        pat = pattern.search(filename)
        time = pat.group(2) + pat.group(3)
    return dt.datetime.strptime(time, "%Y%m%d%H%M")


def get_dx_timestamp(name):
    """Converts a dx-timestamp (as part of a dx-product filename) to a
    python datetime.object.

    Parameters
    ----------
    name : str
        representing a DWD product name

    Returns
    -------
    time : :py:class:`datetime.datetime`
        timezone-aware datetime.datetime object
    """
    return _get_timestamp_from_filename(name).replace(tzinfo=util.UTC())


def unpack_dx(raw):
    """function removes DWD-DX-product bit-13 zero packing"""
    # data is encoded in the first 12 bits
    data = 4095
    # the zero compression flag is bit 13
    flag = 4096

    beam = []

    # # naive version
    # # 49193 function calls in 0.772 CPU seconds
    # # 20234 function calls in 0.581 CPU seconds
    # for item in raw:
    #     if item & flag:
    #         beam.extend([0]* (item & data))
    #     else:
    #         beam.append(item & data)

    # performance version - hopefully
    # 6204 function calls in 0.149 CPU seconds

    # get all compression cases
    flagged = np.where(raw & flag)[0]

    # if there is no zero in the whole data, we can return raw as it is
    if flagged.size == 0:
        if raw.size != 128:
            raise OSError(
                f"DX decoding data size mismatch. Expected size of 128, but got {raw.size}."
            )
        return raw

    # everything until the first flag is normal data
    beam.extend(raw[0 : flagged[0]])

    # iterate over all flags except the last one
    for this, nxt in zip(flagged[:-1], flagged[1:]):
        # create as many zeros as there are given within the flagged
        # byte's data part
        beam.extend([0] * (raw[this] & data))
        # append the data until the next flag
        beam.extend(raw[this + 1 : nxt])

    # process the last flag
    # add zeroes
    beam.extend([0] * (raw[flagged[-1]] & data))

    # add remaining data
    beam.extend(raw[flagged[-1] + 1 :])

    # return the data
    return np.array(beam)


def get_dx_header_token():
    """Return array with known header token of dx data

    Returns
    -------
    head : dict
        with known header token, value set to None
    """
    head = {
        "BY": None,
        "VS": None,
        "CO": None,
        "CD": None,
        "CS": None,
        "EP": None,
        "MS": None,
    }
    return head


def parse_dx_header(header):
    """Internal function to retrieve and interpret the ASCII header of a DWD
    DX product file.

    Parameters
    ----------
    header : str
        string representation of DX header
    """
    # empty container
    out = {}
    # RADOLAN product type def
    out["producttype"] = header[0:2]
    # time stamp from file header as Python datetime object
    out["datetime"] = dt.datetime.strptime(
        header[2:8] + header[13:17] + "00", "%d%H%M%m%y%S"
    )
    # Make it aware of its time zone (UTC)
    out["datetime"] = out["datetime"].replace(tzinfo=util.UTC())
    # radar location ID (always 10000 for composites)
    out["radarid"] = header[8:13]

    head = get_radolan_header_token_pos(header, mode="dx")

    # iterate over token and fill output dict accordingly
    for k, v in head.items():
        if v:
            if k == "BY":
                out["bytes"] = int(header[v[0] : v[1]])
            if k == "VS":
                out["version"] = header[v[0] : v[1]]
            if k == "CO":
                out["cluttermap"] = int(header[v[0] : v[1]])
            if k == "CD":
                out["dopplerfilter"] = int(header[v[0] : v[1]])
            if k == "CS":
                out["statfilter"] = int(header[v[0] : v[1]])
            if k == "EP":
                out["elevprofile"] = [
                    float(header[v[0] + 3 * i : v[0] + 3 * (i + 1)]) for i in range(8)
                ]
            if k == "MS":
                try:
                    cnt = int(header[v[0] : v[0] + 3])
                    out["message"] = header[v[0] + 3 : v[0] + 3 + cnt]
                except ValueError:
                    pass

    return out


def read_dx(filename):
    """Data reader for German Weather Service DX product raw radar data files.

    This product uses a simple algorithm to compress zero values to reduce data
    file size.

    Notes
    -----
    While the format appears to be well-defined, there have been reports on DX-
    files that seem to produce errors. e.g. while one file usually contains a
    360 degree by 128 1km range bins, there are files, that contain 361 beams.
    Also, while usually azimuths are stored monotonously in ascending order,
    this is not guaranteed by the format. This routine does not (yet) check
    for this and directly returns the data in the order found in the file.
    If you are in doubt, check the 'azim' attribute.
    Be aware that this function does no extensive checking on its output.
    If e.g. beams contain different numbers of range bins, the resulting data
    will not be a 2-D array but a 1-D array of objects, which will most
    probably break calling code. It was decided to leave the handling of these
    (hopefully) rare events to the user, who might still be able to retrieve
    some reasonable data, instead of raising an exception, making it impossible
    to get any data from a file containing errors.

    Parameters
    ----------
    filename : str or file-like
        filename of binary file of DX raw data or file-like object

    Returns
    -------
    data : :py:class:`numpy:numpy.ndarray`
        Array of image data [dBZ]; shape (360,128)
    attributes : dict
        dictionary of attributes - currently implemented keys:

        - 'azim' - azimuths array of shape (360, )
        - 'elev' - elevations (1 per azimuth); array of shape (360, )
        - 'clutter' - clutter mask; boolean array of same shape as `data`;
          corresponds to bit 15 set in each dataset.
        - 'bytes'- the total product length (including header).
          Apparently, this value may be off by one byte for unknown reasons
        - 'version'- a product version string - use unknown
        - 'cluttermap' - number of the (DWD internal) cluttermap used
        - 'dopplerfilter' - number of the dopplerfilter used (DWD internal)
        - 'statfilter' - number of a statistical filter used (DWD internal)
        - 'elevprofile' - as stated in the format description, this list
          indicates the elevations in the eight 45 degree sectors. These
          sectors need not start at 0 degrees north, so it is advised to
          explicitly evaluate the `elev` attribute, if elevation information
          is needed.
        - 'message' - additional text stored in the header.

    Examples
    --------
    See :ref:`/notebooks/fileio/legacy/read_dx.ipynb`.
    """

    azimuthbitmask = 2 ** (14 - 1)
    databitmask = 2 ** (13 - 1) - 1
    clutterflag = 2**15
    dataflag = 2**13 - 1

    with get_radolan_filehandle(filename) as f:
        # header string for later processing
        header = ""
        atend = False

        # read header
        while True:
            mychar = f.read(1)
            # 0x03 signals the end of the header but sometimes there might be
            # an additional 0x03 char after that

            if mychar == b"\x03":
                atend = True
            if mychar != b"\x03" and atend:
                break
            header += str(mychar.decode())

        attrs = parse_dx_header(header)

        # position file at end of header
        f.seek(len(header))

        # read number of bytes as declared in the header
        # intermediate fix:
        # if product length is uneven but header is even (e.g. because it has two
        # chr(3) at the end, read one byte less
        buflen = attrs["bytes"] - len(header)
        if (buflen % 2) != 0:
            # make sure that this is consistent with our assumption
            # i.e. contact DWD again, if DX files show up with uneven byte lengths
            # *and* only one 0x03 character
            # assert header[-2] == chr(3)
            buflen -= 1

        buf = f.read(buflen)
        # we can interpret the rest directly as a 1-D array of 16 bit unsigned ints
        raw = np.frombuffer(buf, dtype="uint16")

    # a new ray/beam starts with bit 14 set
    # careful! where always returns its results in a tuple, so in order to get
    # the indices we have to retrieve element 0 of this tuple
    newazimuths = np.where(raw == azimuthbitmask)[0]  # Thomas kontaktieren!

    # for the following calculations it is necessary to have the end of the
    # data as the last index
    newazimuths = np.append(newazimuths, len(raw))

    # initialize our list of rays/beams
    beams = []
    # initialize our list of elevations
    elevs = []
    # initialize our list of azimuths
    azims = []

    # iterate over all beams
    for i in range(newazimuths.size - 1):
        # unpack zeros
        beam = unpack_dx(raw[newazimuths[i] + 3 : newazimuths[i + 1]])
        beams.append(beam)
        elevs.append((raw[newazimuths[i] + 2] & databitmask) / 10.0)
        azims.append((raw[newazimuths[i] + 1] & databitmask) / 10.0)

    beams = np.array(beams)

    # attrs =  {}
    attrs["elev"] = np.array(elevs)
    attrs["azim"] = np.array(azims)
    attrs["clutter"] = (beams & clutterflag) != 0

    # converting the DWD rvp6-format into dBZ data and return as numpy array
    # together with attributes
    return (beams & dataflag) * 0.5 - 32.5, attrs


def get_radolan_header_token():
    """Return array with known header token of radolan composites

    Returns
    -------
    head : dict
        with known header token, value set to None
    """
    head = {
        "BY": None,
        "VS": None,
        "SW": None,
        "PR": None,
        "INT": None,
        "GP": None,
        "MS": None,
        "LV": None,
        "CS": None,
        "MX": None,
        "BG": None,
        "ST": None,
        "VV": None,
        "MF": None,
        "QN": None,
        "VR": None,
        "U": None,
    }
    return head


def get_radolan_site_token():
    head = get_radolan_header_token()
    head.update(
        {
            "CO": None,
            "CD": None,
            "MH": None,
            "HI": None,
            "CI": None,
            "CL": None,
            "FL": None,
        }
    )
    return head


def get_radolan_header_token_pos(header, *, mode="composite"):
    """Get Token and positions from DWD radolan header

    Parameters
    ----------
    header : str
        (ASCII header)
    mode : str, optional
        'composite', 'station' or 'dx', defaults to 'composite'.

    Returns
    -------
    head : dict
        with found header tokens and positions
    """
    if mode == "composite":
        head_dict = get_radolan_header_token()
    elif mode == "station":
        head_dict = get_radolan_site_token()
    elif mode == "dx":
        head_dict = get_dx_header_token()
    else:
        raise ValueError(
            f"Unknown mode {mode}, use either `composite`, `stations or `dx` depending on data source"
        )

    for token in head_dict.keys():
        d = header.rfind(token)
        if d > -1:
            head_dict[token] = d
    head = {}

    result_dict = {}
    result_dict.update((k, v) for k, v in head_dict.items() if v is not None)
    for k, v in head_dict.items():
        if v is not None:
            start = v + len(k)
            filt = [x for x in result_dict.values() if x > v]
            if filt:
                stop = min(filt)
            else:
                stop = len(header)
            head[k] = (start, stop)
        else:
            head[k] = v

    return head


def parse_dwd_composite_header(header):
    """Parses the ASCII header of a DWD quantitative composite file

    Parameters
    ----------
    header : str
        (ASCII header)

    Returns
    -------
    output : dict
        of metadata retrieved from file header
    """
    # do not parse ascii header
    if isinstance(header, dict) and header["producttype"] == "ascii":
        return header

    # empty container
    out = {}

    # RADOLAN product type def
    out["producttype"] = header[0:2]
    # file time stamp as Python datetime object
    out["datetime"] = dt.datetime.strptime(
        header[2:8] + header[13:17] + "00", "%d%H%M%m%y%S"
    )
    # radar location ID (always 10000 for composites)
    out["radarid"] = header[8:13]

    # if station product
    if out["radarid"] == 10000:
        kwargs = dict(mode="composite")
    else:
        kwargs = dict(mode="station")
        # assume site product with 200 rows/cols
        out["nrow"] = 200
        out["ncol"] = 200

    # get dict of header token with positions
    head = get_radolan_header_token_pos(header, **kwargs)
    # iterate over token and fill output dict accordingly
    for k, v in head.items():
        if v:
            if k == "BY":
                out["datasize"] = int(header[v[0] : v[1]]) - len(header) - 1
            elif k == "VS":
                vs = int(header[v[0] : v[1]])
                out["formatversion"] = vs
                out["maxrange"] = {
                    0: "100 km and 128 km (mixed)",
                    1: "100 km",
                    2: "128 km",
                    3: "150 km",
                }.get(vs, "100 km")
            elif k == "SW":
                out["radolanversion"] = header[v[0] : v[1]].strip()
            elif k == "PR":
                out["precision"] = float("1" + header[v[0] : v[1]].strip())
            elif k == "INT":
                out["intervalseconds"] = int(header[v[0] : v[1]]) * 60
            elif k == "U":
                out["intervalunit"] = int(header[v[0] : v[1]])
                if out["intervalunit"] == 1:
                    out["intervalseconds"] *= 1440
            elif k == "GP":
                dimstrings = header[v[0] : v[1]].strip().split("x")
                out["nrow"] = int(dimstrings[0])
                out["ncol"] = int(dimstrings[1])
            elif k == "BG":
                dimstrings = header[v[0] : v[1]]
                dimstrings = (
                    dimstrings[: int(len(dimstrings) / 2)],
                    dimstrings[int(len(dimstrings) / 2) :],
                )
                out["nrow"] = int(dimstrings[0])
                out["ncol"] = int(dimstrings[1])
            elif k == "LV":
                lv = header[v[0] : v[1]].split()
                out["nlevel"] = int(lv[0])
                out["level"] = np.array(lv[1:]).astype("float")
            elif k == "MS":
                try:
                    locationstring = header[v[0] :].strip().split("<")[1].split(">")[0]
                    out["radarlocations"] = locationstring.split(",")
                except IndexError:
                    try:
                        cnt = int(header[v[0] : v[0] + 3])
                        out["message"] = header[v[0] + 3 : v[0] + 3 + cnt]
                    except ValueError:
                        pass
            elif k == "ST":
                locationstring = header[v[0] :].strip().split("<")[1].split(">")[0]
                out["radardays"] = locationstring.split(",")
            elif k == "CS":
                if out["producttype"] == "PZ":
                    out["statisticfilter"] = header[v[0] : v[1]].strip()
                else:
                    out["indicator"] = {
                        0: "near ground level",
                        1: "maximum",
                        2: "tops",
                    }.get(int(header[v[0] : v[1]]))
            elif k == "MX":
                out["imagecount"] = int(header[v[0] : v[1]])
            elif k == "VV":
                out["predictiontime"] = int(header[v[0] : v[1]])
            elif k == "MF":
                out["moduleflag"] = int(header[v[0] : v[1]])
            elif k == "QN":
                out["quantification"] = int(header[v[0] : v[1]])
            elif k == "VR":
                out["reanalysisversion"] = header[v[0] : v[1]].strip()
            elif k == "CO":
                out["cluttermap"] = header[v[0] : v[1]].strip()
            elif k == "CD":
                out["dopplerfilter"] = header[v[0] : v[1]].strip()
            elif k == "MH":
                out["maxheight"] = int(header[v[0] : v[1]])
            elif k == "HI":
                out["hailwarning"] = header[v[0] : v[1]].strip()
            elif k == "CI":
                ci = header[v[0] : v[1]]
                lci = len(ci) // 2
                out["severeconvection"] = [float(ci[:lci]), float(ci[lci:])]
            elif k == "CL":
                cl = header[v[0] : v[1]]
                out["severeconvectionheights"] = [int(cl[0:2]), int(cl[2:4])]
            elif k == "FL":
                out["freezing_level"] = header[v[0] : v[1]].strip()
    return out


def decode_radolan_runlength_line(line, attrs):
    """Decodes one line of runlength coded binary data of DWD
    composite file and returns decoded array

    Parameters
    ----------
    line : :py:class:`numpy:numpy.ndarray`
        of byte values
    attrs : dict
        dictionary of attributes derived from file header

    Returns
    -------
    arr : :py:class:`numpy:numpy.ndarray`
        of decoded values
    """
    # byte '0' is line number, we don't need it
    # so, we start with offset byte
    lo = 1
    byte = line[lo]
    # line empty condition, lf directly behind line number
    if byte == 10:
        return np.ones(attrs["ncol"], dtype=np.uint8) * attrs["nodataflag"]
    offset = byte - 16

    # check if offset byte is 255 and take next byte(s)
    # also for the offset
    while byte == 255:
        lo += 1
        byte = line[lo]
        offset += byte - 16

    # just take the rest
    dline = line[lo + 1 :]

    # this could be optimized
    # iterate over line string, until lf (10) is reached
    for lo, byte in enumerate(dline):
        if byte == 10:
            break
        width = (byte & 0xF0) >> 4
        val = byte & 0x0F
        # the "offset pixel" are "not measured" values
        # so, we set them to 'nodata'
        if lo == 0:
            arr = np.ones(offset, dtype=np.uint8) * attrs["nodataflag"]
        arr = np.append(arr, np.ones(width, dtype=np.uint8) * val)

    trailing = attrs["ncol"] - len(arr)
    if trailing > 0:
        arr = np.append(arr, np.ones(trailing, dtype=np.uint8) * attrs["nodataflag"])
    elif trailing < 0:
        arr = dline[:trailing]

    return arr


def read_radolan_runlength_line(fid):
    """Reads one line of runlength coded binary data of DWD
    composite file and returns it as numpy array

    Parameters
    ----------
    fid : object
        file/buffer id

    Returns
    -------
    line : :py:class:`numpy:numpy.ndarray`
        Array of coded values
    """
    line = fid.readline()

    # check if eot
    if line == b"\x04":
        return None

    # convert input buffer to np.uint8 array
    line = np.frombuffer(line, np.uint8).astype(np.uint8)

    return line


def decode_radolan_runlength_array(binarr, attrs):
    """Decodes the binary runlength coded section from DWD composite
    file and return decoded numpy array with correct shape

    Parameters
    ----------
    binarr : str
        Buffer
    attrs : dict
        Attribute dict of file header

    Returns
    -------
    arr : :py:class:`numpy:numpy.ndarray`
        Array of decoded values
    """
    buf = io.BytesIO(binarr)

    # read and decode first line
    line = read_radolan_runlength_line(buf)
    arr = decode_radolan_runlength_line(line, attrs)

    # read following lines
    line = read_radolan_runlength_line(buf)

    while line is not None:
        dline = decode_radolan_runlength_line(line, attrs)
        arr = np.vstack((arr, dline))
        line = read_radolan_runlength_line(buf)

    # reshape early for PZ station product
    if mh := attrs.get("maxheight", False):
        arr = arr.reshape(mh, attrs["nrow"], attrs["ncol"])
    # return upside down because first line read is top line
    return np.flip(arr, axis=-2)


def read_radolan_binary_array(fid, size, *, raise_on_error=True):
    """Read binary data from file given by filehandle

    Parameters
    ----------
    fid : object
        file handle
    size : int
        number of bytes to read
    raise_on_error : bool
        If True, raise IOError if data is truncated.

    Returns
    -------
    binarr : bytes
        binary data
    """
    binarr = fid.read(size)
    if raise_on_error and len(binarr) != size:
        try:
            desc = fid.name
        except AttributeError:
            desc = repr(fid)
        raise OSError(
            f"File corruption while reading {desc}! Could not read enough data!"
        )
    return binarr


def get_radolan_filehandle(fname):
    """Opens radolan file and returns file handle

    Parameters
    ----------
    fname : str or file-like
        filename or file-like object

    Returns
    -------
    f : object
        file handle
    """
    if isinstance(fname, str):
        if fname.endswith(".gz"):
            _open = util.import_optional("gzip").open
        elif fname.endswith(".bz2"):
            _open = util.import_optional("bz2").open
        else:
            _open = open
        fname = _open(fname, mode="rb")
    return fname


def read_radolan_header(fid):
    """Reads radolan ASCII header and returns it as string

    Parameters
    ----------
    fid : object
        file handle

    Returns
    -------
    header : str
    """

    header = ""
    while True:
        mychar = fid.read(1)
        if not mychar:
            raise EOFError("Unexpected EOF detected while reading RADOLAN header.")
        # if the first char is "n", then most likely this is ascii radolan data
        if header == "" and mychar == b"n":
            fid.seek(0)
            # read the header
            header = [fid.readline().decode().split() for i in range(6)]
            header = {h[0]: int(h[1]) for h in header}
            header["producttype"] = "ascii"
            return header
        if mychar == b"\x03":
            break
        header += str(mychar.decode())
    return header


def _fix_radolan_truncated_buffer(data, size, dtype):
    """Fill truncated buffer."""
    isize = np.dtype(dtype).itemsize
    fill_value = 250 if isize == 1 else 8192
    if len(data) % isize:
        data = data[:-1]
    fill = np.full((size - len(data)) // isize, fill_value, dtype=dtype)
    data += fill.tobytes()
    return data


def read_radolan_composite(f, *, missing=-9999, loaddata=True, fillmissing=False):
    """Read quantitative radar composite format of the German Weather Service

    The quantitative composite format of the DWD (German Weather Service) was
    established in the course of the RADOLAN project and includes several file
    types, e.g. RX, RO, RK, RZ, RP, RT, RC, RI, RG, PC, PG and many, many more.
    (see format description on the RADOLAN project homepage :cite:`DWD2009`).
    At the moment, the national RADOLAN composite is a 900 x 900 grid with 1 km
    resolution and in polar-stereographic projection. There are other grid
    resolutions for different composites (e.g. PC, PG)

    Note
    ----
    DWD also provides data in ASCII format, which have a very limited header and need
    to extract product and datetime from the filename. Use on your own risk.

        .. versionadded:: 1.17

    Warning
    -------
    This function already evaluates and applies the so-called
    PR factor which is specified in the header section of the RADOLAN files.
    The raw values in an RY file are in the unit 0.01 mm/5min, while
    read_radolan_composite returns values in mm/5min (e.g. factor 100 higher).
    The factor is also returned as part of attrs dictionary under
    keyword "precision".

    Note
    ----
    You might also use :func:`wradlib.io.radolan.open_radolan_dataset` or :func:`xarray:xarray.open_dataset`
    with keyword engine='radolan' to import into xarray Dataset.

    Parameters
    ----------
    f : str or file-like
        path to the composite file or file-like object
    missing : int
        value assigned to no-data cells
    loaddata : bool
        True | False, If False function returns (None, attrs)
    fillmissing : bool
        If True fills truncated values with "missing". Defaults to False.
        Does not work for run-length encoded files ("PC" and "PG).

    Returns
    -------
    output : tuple
        tuple of two items (data, attrs):
            - data : :class:`numpy:numpy.ndarray` of shape (number of rows,
              number of columns) or :py:class:`xarray:xarray.Dataset`
            - attrs : dict of metadata information from the file header

    Examples
    --------
    See :ref:`/notebooks/fileio/radolan/radolan_format.ipynb`.
    """
    NODATA = missing

    # get _radolan_file class
    with _radolan_file(
        f, fillmissing=fillmissing, copy=True, ancillary=False
    ) as radfile:
        attrs = radfile.attrs

        if not loaddata:
            return None, attrs

        if radfile.attrs["producttype"] == "ascii":
            NODATA = attrs["nodataflag"]
        else:
            attrs["nodataflag"] = NODATA

        if not attrs["radarid"] == "10000":
            util.warn(
                "You are using function "
                "wradlib.io.read_radolan_composit for a non composite file. "
                "This might work, but please check the validity of the results!"
            )

        arr = radfile.data[radfile.product]

    # apply precision factor
    if "precision" in attrs:
        arr = arr * attrs["precision"]
    # set nodata value
    if "nodatamask" in attrs:
        arr.flat[attrs["nodatamask"].flatten()] = NODATA
    return arr, attrs


def _get_radolan_product_attributes(attrs):
    """Create RADOLAN product attributes dictionary

    Parameters
    ----------
    attrs : dict
        dictionary of metadata information from the file header

    Returns
    -------
    pattrs : dict
        RADOLAN product attributes
    """
    product = attrs["producttype"]
    pattrs = {}

    if product not in ["PG", "PC", "PZ", "ascii"]:
        interval = attrs["intervalseconds"]
        precision = attrs["precision"]
    if product in ["RX", "EX", "WX"]:
        pattrs.update(radolan["dBZ"])
    elif product in ["WN"]:
        pattrs.update(radolan["dBZ2"])
        pattrs["scale_factor"] *= np.float32(precision)
    elif product in [
        "RY",
        "RZ",
        "RW",
        "RH",
        "RB",
        "RL",
        "RU",
        "EH",
        "EB",
        "EW",
        "EY",
        "EZ",
        "YW",
        "RV",
        "RE",
        "RQ",
    ]:
        pattrs.update(radolan["RR"])
        scale_factor = np.float32(precision * 3600 / interval)
        pattrs.update({"scale_factor": scale_factor})
    elif product in [
        "SQ",
        "SH",
        "SF",
        "W1",
        "W2",
        "W3",
        "W4",
    ]:
        pattrs.update(radolan["RA"])
        pattrs.update({"scale_factor": np.float32(precision)})
    elif product in ["PG", "PC", "PZ"]:
        pattrs.update(radolan["PG"])
    elif product in ["%M", "%J", "%Y"]:
        pattrs.update(radolan["%"])
    elif product in ["ascii"]:
        pattrs["scale_factor"] = attrs["precision"]
        pattrs["_FillValue"] = np.array([attrs["nodataflag"]], dtype=np.int32)
    else:
        raise ValueError(f"Unkown RADOLAN product {product!r}!")

    return pattrs


radolan = {
    "dBZ": {
        "scale_factor": np.float32(0.5),
        "add_offset": np.float32(-32.5),
        "valid_min": np.int32(0),
        "valid_max": np.int32(255),
        "_FillValue": np.array([249, 250, 255], dtype=np.int32),
        "standard_name": "equivalent_reflectivity_factor",
        "long_name": "equivalent_reflectivity_factor",
        "unit": "dBZ",
    },
    "dBZ2": {
        "scale_factor": np.float32(0.5),
        "add_offset": np.float32(-32.5),
        "valid_min": np.int32(0),
        "valid_max": np.int32(4095),
        "_FillValue": np.array([2490, 2500, 65535], dtype=np.int32),
        "standard_name": "equivalent_reflectivity_factor",
        "long_name": "equivalent_reflectivity_factor",
        "unit": "dBZ",
    },
    "RR": {
        "add_offset": np.float32(0),
        "valid_min": np.int32(0),
        "valid_max": np.int32(4095),
        "_FillValue": np.array([2490, 2500, 65535], dtype=np.int32),
        "standard_name": "rainfall_rate",
        "long_name": "rainfall_rate",
        "unit": "mm h-1",
    },
    "RA": {
        "add_offset": np.float32(0),
        "valid_min": np.int32(0),
        "valid_max": np.int32(4095),
        "_FillValue": np.array([2490, 2500, 65535], dtype=np.int32),
        "standard_name": "rainfall_amount",
        "long_name": "rainfall_amount",
        "unit": "mm",
    },
    "PG": {
        "valid_min": np.int32(0),
        "valid_max": np.int32(255),
        "_FillValue": np.int32(255),
    },
    "%": {
        "add_offset": np.float32(0),
        "valid_min": np.int32(0),
        "valid_max": np.int32(4095),
        "_FillValue": np.array([2490, 2500, 65535], dtype=np.int32),
        "standard_name": "relativ_rainfall_amount_to_30_year_average",
        "long_name": "relativ_rainfall_amount_to_30_year_average",
        "unit": "1",
    },
}


class _radolan_file:
    """A file object for RADOLAN data.

    This class maps RADOLAN data to NetCDF style dimensions, variables and attributes.

    Parameters
    ----------
    filename : str or file-like
        path to the composite file or file-like object
    fillmissing : bool
        If True fills truncated values with "missing". Defaults to False.
        Does not work for run-length encoded files ("PC" and "PG).
    copy : bool
        If False tries to get a view into the data. If True copies data in any case.
        Defaults to False.
    ancillary : bool, tuple of str
        If True, resturns ancillary masks ("secondary", "nodatamask", "cluttermask")
        as additional data variables. Can be specified as tuple of strings.
        Defaults to False.

    Returns
    -------
    dset : :py:class:`xarray:xarray.Dataset`
        RADOLAN data and coordinates

    """

    def __init__(
        self, filename, *, fillmissing=False, copy=False, ancillary=False, **kwargs
    ):
        if hasattr(filename, "seek"):
            if hasattr(filename, "name"):
                self.filename = filename.name
            else:
                self.filename = "None"
        else:
            self.filename = filename

        filename = get_radolan_filehandle(filename)

        if hasattr(filename, "seek"):
            self.fp = filename
        else:
            mode = "r"
            self.fp = open(filename, f"{mode}b")

        self._attrs = None
        self._product = None
        self._data = {}
        self._dtype = None
        self._shape = None
        self.dimensions = {}
        self._variables = None
        self.attributes = {}

        self._fill = fillmissing
        self._copy = copy
        if self.attrs["producttype"] == "ascii":
            self._product = self.filename[0:2].upper()
        self._ancillary = self._get_ancillary(requested=ancillary)

    @property
    def attrs(self):
        if self._attrs is None:
            # move file pointer to start
            self.fp.seek(0)
            self._attrs = self._read_attrs()
        return self._attrs

    @property
    def product(self):
        if self._product is None:
            self._product = self.attrs["producttype"]
        return self._product

    @property
    def data(self):
        if not self._data or self.product not in self._data:
            self._read_data()
        return self._data

    @property
    def shape(self):
        if self._shape is None:
            shape = (self.attrs["nrow"], self.attrs["ncol"])
            if mh := self.attrs.get("maxheight", False):
                shape = (mh,) + shape
            self._shape = shape
        return self._shape

    @property
    def dtype(self):
        if self._dtype is None:
            if self.product in ["RX", "EX", "WX"]:
                self._dtype = np.dtype(np.uint8)
            elif self.product in ["HG"]:
                self._dtype = np.dtype(np.uint32)
            else:
                self._dtype = np.dtype(np.uint16)
        return self._dtype

    @property
    def variables(self):
        if self._variables is None:
            self._read()
        return self._variables

    def _read_attrs(self):
        header = read_radolan_header(self.fp)
        if isinstance(header, dict) and header["producttype"] == "ascii":
            header["ncol"] = header.pop("ncols")
            header["nrow"] = header.pop("nrows")
            header["radarid"] = "10000"
            header["nodataflag"] = header.pop("NODATA_value")
            if header["nodataflag"] == -1:
                header["precision"] = 0.1
            header["datetime"] = _get_timestamp_from_filename(
                self.filename, pattern=dwdascii
            ).replace(tzinfo=util.UTC())
        return parse_dwd_composite_header(header)

    def _process_data(self):
        data = self._data[self.product]
        if self.attrs["producttype"] == "ascii":
            self.attrs["nodatamask"] = np.where(data == self.attrs["nodataflag"])[0]
        elif self.product in ["PG", "PC", "PZ"]:
            self.attrs["nodataflag"] = 255
            self.attrs["nodatamask"] = data == 255
        elif self.product in ["RX", "EX", "WX"]:
            self.attrs["nodatamask"] = np.where(data == 250)[0]
            self.attrs["cluttermask"] = np.where(data == 249)[0]
        else:
            self.attrs["secondary"] = np.where(data & 0x1000)[0]
            self.attrs["nodatamask"] = np.where(data & 0x2000)[0]
            negative = np.where(data & 0x4000)[0]
            self.attrs["cluttermask"] = np.where(data & 0x8000)[0]
            data &= 0xFFF
            if self.product == "RD":
                data[negative] = -data[negative]

        # masks
        if self._ancillary:
            for a in self._ancillary:
                vals = self.attrs.get(a, None)
                if vals is not None:
                    ancdata = np.zeros_like(data, dtype=bool)
                    ancdata[vals] = True
                    self._data[a] = ancdata

    def _read_data(self):
        # handle ascii data
        if self.attrs["producttype"] == "ascii":
            # todo: check if flip is needed
            self._data[self.product] = np.flip(np.genfromtxt(self.fp), axis=0)
            self._process_data()
            return

        # handle truncated data
        binarr_kwargs = {}
        if self._fill and self.product not in ["PG", "PC", "PZ"]:
            binarr_kwargs.update({"raise_on_error": False})
        # read data
        size = self.attrs["datasize"]
        indat = read_radolan_binary_array(self.fp, size, **binarr_kwargs)

        if self._fill and len(indat) < size and self.product not in ["PG", "PC", "PZ"]:
            indat = _fix_radolan_truncated_buffer(indat, size, self.dtype)

        if self.product in ["PC", "PG", "PZ"]:
            self._data[self.product] = decode_radolan_runlength_array(
                indat,
                {
                    "ncol": self.attrs["ncol"],
                    "nrow": self.attrs["nrow"],
                    "maxheight": self.attrs.get("maxheight", False),
                    "nodataflag": 255,
                },
            )
        else:
            self._data[self.product] = np.frombuffer(indat, dtype=self.dtype)
            if not self._copy and self.dtype == np.uint8:
                self._data[self.product] = self._data[self.product].view(
                    dtype=self.dtype
                )
            else:
                # use astype here since we change the data later
                self._data[self.product] = self._data[self.product].astype(self.dtype)
        self._process_data()
        for _k, v in self._data.items():
            v.shape = self.shape
            self._data[_k] = v

    def _read(self):
        attrs = self.attrs.copy()
        pattrs = _get_radolan_product_attributes(attrs)

        if self.attrs.get("maxheight", False):
            self.dimensions["z"] = self.attrs["maxheight"]
        self.dimensions["y"] = self.attrs["nrow"]
        self.dimensions["x"] = self.attrs["ncol"]
        dims = " ".join(list(self.dimensions.keys()))
        pattrs.update({"long_name": self.product, "coordinates": f"time {dims}"})

        data_var = WradlibVariable(self.dimensions, data=self, attrs=pattrs)

        # coordinate variables
        time_attrs = {
            "standard_name": "time",
            "units": "seconds since 1970-01-01T00:00:00Z",
        }
        raw_time = attrs.get("datetime").replace(tzinfo=dt.timezone.utc)
        time = np.array([raw_time.timestamp()])
        time_var = WradlibVariable("time", data=time, attrs=time_attrs)

        pred_time = attrs.get("predictiontime", None)
        if pred_time is not None:
            pred_time = np.array(
                [raw_time + dt.timedelta(minutes=pred_time)], dtype=np.datetime64
            )
            pred_time_var = WradlibVariable(
                "prediction_time", data=pred_time, attrs=time_attrs
            )

        # if GDAL is not installed, fall back to trigonometric calculation
        if util.has_import(osr):
            if attrs.get("formatversion", 3) >= 5:
                crs = projection.create_osr("dwd-radolan-wgs84")
            else:
                crs = projection.create_osr("dwd-radolan-sphere")
        else:
            crs = "trig"

        coords_kwargs = {}
        if self.attrs.get("maxheight", False):
            radar = dwdradarmapping[int(self.attrs["radarid"])]
            site = dwdlocs[radar]
            coords_kwargs.update(dict(lon=site["lon"], lat=site["lat"]))

        xlocs, ylocs = rect.get_radolan_coordinates(
            self.dimensions["y"],
            self.dimensions["x"],
            crs=crs,
            mode="center",
            **coords_kwargs,
        )
        xattrs = {
            "units": "m",
            "long_name": "x coordinate of projection",
            "standard_name": "projection_x_coordinate",
        }
        x_var = WradlibVariable("x", xlocs, xattrs)

        yattrs = {
            "units": "m",
            "long_name": "y coordinate of projection",
            "standard_name": "projection_y_coordinate",
        }
        y_var = WradlibVariable("y", ylocs, yattrs)

        if self.attrs.get("maxheight", False):
            zattrs = {
                "units": "m",
                "long_name": "z coordinate of projection",
                "standard_name": "projection_z_coordinate",
            }
            zlocs = np.arange(
                1000, self.attrs["maxheight"] * 1000 + 1, 1000, dtype=float
            )
            z_var = WradlibVariable("z", zlocs, zattrs)

        self._variables = {
            self.product: data_var,
            "time": time_var,
        }

        if self.attrs.get("maxheight", False):
            self._variables.update({"z": z_var})

        self._variables.update(
            {
                "y": y_var,
                "x": x_var,
            }
        )

        if pred_time is not None:
            self._variables.update({"prediction_time": pred_time_var})

        if self._ancillary:
            for a in self._ancillary:
                ancvar = WradlibVariable(self.dimensions, data=self, attrs={})
                self._variables[a] = ancvar

        # remove unneeded global attributes
        remove = [
            "producttype",
            "datetime",
            "datasize",
            "precision",
            "nrow",
            "ncol",
            "maxrange",
            "intervalseconds",
            "xllcorner",
            "yllcorner",
            "cellsize",
            "nodataflag",
        ]
        [attrs.pop(key, None) for key in remove]
        self.attributes.update(attrs)

    def _get_ancillary(self, requested=True):
        if self.product in ["PG", "PC", "PZ"] or self.attrs["producttype"] == "ascii":
            anc = ("nodatamask",)
        elif self.product in ["RX", "EX", "WX"]:
            anc = ("nodatamask", "cluttermask")
        else:
            anc = ("nodatamask", "cluttermask", "secondary")
        if requested is False:
            return tuple([])
        elif requested is True:
            requested = anc

        anc = set(anc) & set(requested)
        reject = set(anc) ^ set(requested)
        if reject:
            util.warn(
                f"Ancillary data `{tuple(reject)}` requested but not available for product `{self.product}`."
            )

        return tuple(anc)

    def close(self):
        """Closes the Radolan file."""
        # only close if we've opened it and it can be closed
        if self.filename != "None" and hasattr(self, "fp") and not self.fp.closed:
            self.fp.close()

    __del__ = close

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()
