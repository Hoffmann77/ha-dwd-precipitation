"""Parser unit tests for radar/grid.py — the grid a file's /where group describes."""

import pytest

from radar.grid import MAX_CELLS, OutsideGrid, UnsupportedGrid, grid_from_where

from tests.factories.odim import DE1200_WHERE

DE1200 = grid_from_where(DE1200_WHERE)

# How RW and SF (the RADOLAN HDF5 edition) describe the same grid: another
# parameter order, the corners rounded to 8 decimals, a y_0 0.4 nm apart.
RADOLAN_WHERE = DE1200_WHERE | {
    "projdef": (
        "+proj=stere +lat_0=90 +lat_ts=60 +lon_0=10 +a=6378137"
        " +b=6356752.3142451802 +no_defs +x_0=543196.83521776402"
        " +y_0=3622588.8619310018 +units=m"
    ),
    "LL_lat": 45.69642538,
    "LL_lon": 3.566994635,
}

# Cells wradlib's DE1200 grid gives for these locations (the reference tier
# re-derives them; pinned here so the check also runs without wradlib).
CITIES = {
    "Hamburg": ((53.5511, 9.9937), (304, 543)),
    "Berlin": ((52.5200, 13.4050), (416, 784)),
    "Freiburg": ((47.9990, 7.8421), (951, 371)),
    "Munich": ((48.1374, 11.5755), (936, 669)),
    "Cologne": ((50.9375, 6.9603), (601, 319)),
}


@pytest.mark.parametrize("city", CITIES)
def test_cells_match_wradlib_pins(city):
    location, cell = CITIES[city]
    assert DE1200.cell(*location) == cell


def test_ll_corner_maps_to_bottom_left():
    assert DE1200.cell(DE1200_WHERE["LL_lat"], DE1200_WHERE["LL_lon"]) == (1199, 0)


def test_ur_corner_maps_near_top_right():
    row, col = DE1200.cell(55.84, 18.72)  # just inside the outer corner
    assert row <= 5 and col >= 1100 - 6


# Points 400 m and 100 m either side of the outer grid edges, from projected
# x/y via pyproj. The corner attributes are the *outer* pixel corners, so a
# point just beyond them is off the grid — rounding put it in the edge cell.
@pytest.mark.parametrize(
    ("lat", "lon", "cell"),
    [
        (50.70260195370898, 2.6576754488211547, None),          # x = -900 m
        (50.703475085889224, 2.668353517852978, (600, 0)),      # x = -100 m
        (56.22287238431419, 10.10762718326833, None),           # y = +900 m
        (56.21846556371837, 10.107612326653413, (0, 550)),      # y = +400 m
        (45.94609595982105, 10.080828049983344, None),          # y = -1 199 900 m
        (45.95272662686072, 10.080841460710587, (1199, 550)),   # y = -1 199 100 m
    ],
)
def test_grid_edges_are_outer_pixel_corners(lat, lon, cell):
    if cell is None:
        with pytest.raises(OutsideGrid):
            DE1200.cell(lat, lon)
    else:
        assert DE1200.cell(lat, lon) == cell


def test_shape_is_rows_by_columns():
    assert DE1200.shape == (1200, 1100)


def test_projection_origin_and_central_meridian():
    """The pole projects onto (x_0, y_0), and the central meridian onto x = x_0."""
    x, y = DE1200.projection.xy(90.0, 0.0)
    assert (x, y) == pytest.approx((543196.83521776402, 3622588.8619310022))
    assert DE1200.projection.xy(51.0, 10.0)[0] == pytest.approx(543196.83521776402)


# --- the same grid, spelled differently ---------------------------------------


@pytest.mark.parametrize(
    "where",
    [
        RADOLAN_WHERE,
        DE1200_WHERE | {"projdef": DE1200_WHERE["projdef"].encode()},  # bytes, as stored
        DE1200_WHERE | {"projdef": DE1200_WHERE["projdef"].replace(
            "+a=6378137 +b=6356752.3142451802", "+ellps=WGS84")},
        DE1200_WHERE | {"projdef": DE1200_WHERE["projdef"].replace(
            "+a=6378137 +b=6356752.3142451802", "+datum=WGS84 +towgs84=0,0,0")},
    ],
    ids=["radolan", "bytes", "ellps", "datum"],
)
def test_other_spellings_give_the_same_cells(where):
    grid = grid_from_where(where)
    assert grid.shape == DE1200.shape
    for location, cell in CITIES.values():
        assert grid.cell(*location) == cell


def test_one_description_is_built_once():
    assert grid_from_where(dict(DE1200_WHERE)) is DE1200


# --- what cannot be placed is refused -----------------------------------------


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("+proj=stere", "+proj=laea"),            # another projection
        ("+lat_0=90", "+lat_0=-90"),              # the south pole
        ("+lat_ts=60", ""),                       # no standard parallel
        ("+lat_ts=60", "+lat_ts=60 +k_0=0.99"),   # a parameter not understood
        ("+units=m", "+units=km"),
        ("+no_defs", "+no_defs +towgs84=10,0,0"), # a datum shift
        ("+a=6378137 +b=6356752.3142451802", ""), # no ellipsoid
        ("+a=6378137 +b=6356752.3142451802", "+ellps=clrk66"),
        ("+x_0=543196.83521776402", "+x_0=far"),
    ],
)
def test_unsupported_projections_are_refused(old, new):
    where = DE1200_WHERE | {"projdef": DE1200_WHERE["projdef"].replace(old, new)}
    with pytest.raises(UnsupportedGrid):
        grid_from_where(where)


@pytest.mark.parametrize(
    "change",
    [
        {"xsize": 0},
        {"yscale": 0.0},
        {"xsize": MAX_CELLS, "ysize": 2},  # larger than any DWD composite
    ],
)
def test_implausible_grids_are_refused(change):
    with pytest.raises(UnsupportedGrid):
        grid_from_where(DE1200_WHERE | change)


def test_an_incomplete_where_group_is_refused():
    where = dict(DE1200_WHERE)
    del where["LL_lat"]
    with pytest.raises(UnsupportedGrid):
        grid_from_where(where)
