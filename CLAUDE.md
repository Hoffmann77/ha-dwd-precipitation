# DWD Precipitation — Codebase Guide

## What this is

A HomeAssistant custom component that pulls DWD (German Weather Service) radar composites and exposes per-location precipitation sensors. It fetches Cartesian grids, finds the nearest grid cell to the user's configured lat/lon, and reports the cell value.

## Architecture

```
__init__.py           Entry point. Instantiates products and coordinator.
coordinator.py        HA DataUpdateCoordinator. Polls every 90s; calls
                      product.update() when product.requires_update is True.
products.py           One class per DWD product. Each class handles its own
                      URL, fetch, parse, and grid lookup.
sensor.py             HA SensorEntity descriptors. value_fn pulls from
                      coordinator.data[product_key].
dry_streak.py         Pure "days without rain" logic: the persisted anchor
                      payload + threshold/downtime-correction helpers used by
                      the DaysWithoutRainSensor in sensor.py.
config_flow.py        UI config flow: collects name + lat/lon.
const.py              DWD OpenData base URLs and HA constants.
utils.py              async_get() HTTP helper; get_previous_multiple() for
                      computing the most recent release timestamp.
radar/                Embedded parsers (no heavy external deps).
  radolan.py          Extracted wradlib binary parser for RADOLAN/RADVOR formats.
  georef.py           Extracted wradlib polar-stereographic grid transform.
  odim.py             ODIM_H5 (HDF5) reader for RS Cartesian composites.
```

## Data flow

1. `coordinator._async_update_data()` iterates `products`
2. Each `product.update()` fetches the DWD file, parses it, extracts
   `data[product.index]`, stores result in `product.data`
3. Coordinator builds `data = {product.PRODUCT_KEY: product.data, ...}`
4. `PrecipitationSensorEntity.native_value` calls `description.value_fn(data)`

## DWD products

| Class | Key | Format | Update | Description |
|-------|-----|--------|--------|-------------|
| `RadvorRS` | `rs` | ODIM_H5 (tar) | 5 min | RADVOR nowcast, 0/60/120 min lead |
| `RadvorRQ` | `rq` | RADOLAN binary (.gz) | 15 min | RADVOR nowcast (deprecated) |
| `RadolanRW` | `rw` | RADOLAN binary (.bz2) | 1 h | 1-hour precipitation analysis |
| `RadolanSF` | `sf` | RADOLAN binary (.bz2) | 1 h | 24-hour precipitation analysis |
| `RadolanSFLastYesterday` | `sf_2350` | same as SF | daily | Yesterday's 24 h total |

## Adding a new DWD product

1. Subclass `Product` in `products.py`
2. Set `PRODUCT_KEY`, `RELEASE_INTERVAL`, `RELEASE_DELAY`, `RELEASE_OFFSET`
3. Implement `get_url(ts)` and `async update(async_client)`
4. Override `index` (cached_property) if the grid differs from RADOLAN 900×900
5. Add sensor descriptors in `sensor.py` (new `*_SENSORS` tuple)
6. Register the class in `__init__.py` `products` tuple
7. Register sensors in `sensor.py` `async_setup_entry`

## Release timing

`get_latest_release()` in `Product` computes the most-recent valid release:
```
latest = floor((now - RELEASE_DELAY) / RELEASE_INTERVAL) * RELEASE_INTERVAL + RELEASE_OFFSET
```
`RELEASE_DELAY` = how long after the nominal product time it's available on OpenData.
`RELEASE_OFFSET` = minute/second alignment of nominal product times within the interval.

## Grid lookup

### RADOLAN (RQ, RW, SF)
`Product.index` (base class): calls `get_radolan_grid(wgs84=True)` to get the full
900×900 WGS84 lon/lat grid, then finds the nearest cell via minimum squared distance.
Grid is in `radar/georef.py` (spherical polar-stereographic, Earth radius 6370.040 km).

### RS (ODIM_H5)
`RadvorRS.index` calls `get_rs_grid_index(lat, lon)` from `radar/odim.py`.
Direct spherical polar-stereographic forward projection (WGS84 a=6378137m, O(1)).
Grid: 1200 rows × 1100 cols, 1km, same `+proj=stere +lat_ts=60 +lat_0=90 +lon_0=10`
family as RADOLAN but WGS84 ellipsoid, different false easting/northing, and larger extent.

## The radar/ directory

`radar/radolan.py` and `radar/georef.py` are extracted from
[wradlib](https://github.com/wradlib/wradlib) (MIT licence) to avoid requiring
wradlib as a runtime dependency (wradlib pulls in many heavy packages that cannot
be installed in standard HA environments).

`radar/odim.py` is original code that uses `h5py` directly.

## Dependencies

Listed in `manifest.json` `requirements`. Only packages with binary PyPI wheels
that install cleanly in HA are acceptable. Do **not** add wradlib, pyproj, xarray,
GDAL, or other packages with complex build requirements.

Current runtime deps: `numpy`, `h5py`

## RS product specifics

- **URL**: `https://opendata.dwd.de/weather/radar/composite/rs/composite_rs_YYYYMMDD_HHMM.tar`
- **Archive**: one `.tar` per 5-minute release, containing 25 `.hd5` files (`_000-hd5` to `_120-hd5`)
- **Format**: ODIM_H5 H5rad 2.3, `object=COMP` (Cartesian composite)
- **Quantity**: `ACRR` (accumulated rainfall, mm), `gain=0.001`, `offset=-0.001`
- **Grid**: `xsize=1100`, `ysize=1200`, `xscale=yscale=1000.0 m`
- **Projection**: `+proj=stere +lat_ts=60 +lat_0=90 +lon_0=10 +x_0=543196.835... +y_0=3622588.861...` (WGS84)
- **Fetching**: `RadvorRS.update()` downloads one tar and extracts the `_000`, `_060`, `_120` members using stdlib `tarfile`
