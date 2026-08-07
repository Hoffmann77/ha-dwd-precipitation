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
                      the TimespanWithoutPrecipitationSensor in sensor.py.
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
| `RadvorRS` | `rs` | ODIM_H5 (tar) | 5 min | RADVOR nowcast, 0/60/120 min lead; each grid is a 60-min accumulation (see "RS product specifics") |
| `RadvorRV` | `rv` | ODIM_H5 (tar) | 5 min | RV nowcast, 25×5-min grids; derives +1h/+2h peak intensity (mm/h), precip start/end timing (episode/clearing end algorithm, user-selectable), and a rain-within-2h flag (whose metadata carries the raw 25-point forecast series, exposed by default) |
| `HymecNG` | `hymecng` | ODIM_H5 (single .hd5) | 5 min | Precipitation-*type* composite (rain/snow/freezing rain/hail/…); one enum "Precipitation type" sensor |
| `RadvorRQ` | `rq` | RADOLAN binary (.gz) | 15 min | RADVOR nowcast (deprecated) |
| `RadolanRW` | `rw` | RADOLAN binary (.bz2) | 1 h | 1-hour precipitation analysis (gauge-adjusted; same window as RS `_000`) |
| `RadolanSF` | `sf` | RADOLAN binary (.bz2) | 1 h | 24-hour precipitation analysis |
| `RadolanSFLastYesterday` | `sf_2350` | same as SF | daily | Yesterday's 24 h total |

## Entity naming

Every entity name is set via `translation_key` + `translations/en.json` — never a
hardcoded `name=` / `_attr_name`. HA derives the entity id by slugifying the
English name, so the name is also the id: `Precipitation next 1–2h` →
`sensor.<device>_precipitation_next_1_2h`. Keep names slug-friendly.

A name states a window only when the window is part of the *value*. Two forms:

| form | meaning | examples |
|------|---------|----------|
| `last <N>` | measured accumulation over a window ending now | `Precipitation last 1h`, `Precipitation last 24h` |
| `next <N>` | forecast value over a future window | `Precipitation next 1h`, `Precipitation next 1–2h`, `Peak intensity next 1h` |

`next 1–2h` is the 60–120 min window, *not* the coming two hours.

`Precipitation now` (RS `_000`) is the deliberate exception. It is *also* a
60-minute accumulation ending now — the same window as `Precipitation last 1h`
(RW) — but it is named for its role, the live figure refreshed every 5 minutes,
rather than for its window. Two consequences worth keeping in mind:

- Because the two names no longer look alike, RW needs no distinguishing
  qualifier and is plain `Precipitation last 1h`, consistent with the rest of
  the RADOLAN family.
- The name no longer states the window, so the README entity table has to. It is
  mm accumulated over the past hour, **not** a mm/h rate — the reset-threshold
  option compares against it, so 1.0 mm means "1 mm fell in the last hour".

Everything else carries no window, and should keep it that way. The RV 2 h
horizon in particular is a property of the *algorithm*, not of the value, so it
belongs in the docs rather than in four entity names:

- `Precipitation start` / `Precipitation end` answer *when*; outside the horizon
  the state is simply `unknown`.
- `Precipitation expected` is a flag; `off` already covers "not in the horizon".
- `Precipitation type` is the only genuinely instantaneous value, so it needs no
  qualifier (and `now` would collide with the RS sensor's name).

`Peak intensity next 1h` / `next 1–2h` drop the `Precipitation` head noun on
purpose: they are mm/h rather than mm, and the shorter head stops them reading
as near-duplicates of `Precipitation next 1h` / `next 1–2h` in the entity list.

Entity `key`s are separate from names: they are the unique-id suffix, stay
product-prefixed (`radvor_*` / `radolan_*` / `hymecng_*`), and must not change
once released, since renaming one orphans the user's entity.

## Adding a new DWD product

1. Subclass `Product` in `products.py`
2. Set `PRODUCT_KEY`, `RELEASE_INTERVAL`, `RELEASE_DELAY`, `RELEASE_OFFSET`
3. Implement `get_url(ts)` and `async update(async_client)`
4. Override `index` (cached_property) if the grid differs from RADOLAN 900×900
5. Add sensor descriptors in `sensor.py` (new `*_SENSORS` tuple)
6. Register the class in `__init__.py` `products` tuple
7. Register sensors in `sensor.py` `async_setup_entry`, and add each
   `translation_key`'s name to `translations/en.json`

## Release timing

`get_latest_release()` in `Product` computes the most-recent valid release:
```
latest = floor((now - RELEASE_DELAY) / RELEASE_INTERVAL) * RELEASE_INTERVAL + RELEASE_OFFSET
```
`RELEASE_DELAY` = how long after the nominal product time it's available on OpenData.
`RELEASE_OFFSET` = minute/second alignment of nominal product times within the interval.

`scripts/check_release_delay.py` (run by `.github/workflows/release-delay.yml`,
scheduled) averages the *observed* availability delay across a rolling window of
recent files — for each file, its `Last-Modified` header (authoritative GMT)
minus the nominal timestamp in its name — and flags (opens a tracking issue for)
any product the instant its mean lag exceeds its configured `RELEASE_DELAY` —
the harmful direction, where the coordinator fetches before DWD has published
(`--grace` defaults to 0). It reads the
constants straight from the source with `ast` (no HA import), so the configured
value is the single source of truth.

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

`radar/odim.py` is original code that uses `h5py` directly. It exposes
`read_odim_composite` (physical quantities like RS/RV's `ACRR`, scaled by
gain/offset) and `read_odim_classification` (HymecNG's `CLASS` quantity —
discrete class indices returned unscaled, with the `nodata`/`undetect`
sentinels preserved so the caller can tell "outside coverage" from "dry").

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
- **Accumulation window**: each grid is a **60-minute** sum, *not* an instantaneous
  rate — `_000`'s `what/startdate..enddate` spans T−60 min to T (verified against
  `tests/fixtures/composite_rs_sample.hd5`: 06:50 → 07:50 for a 07:50 file). So
  `_000` is "precipitation over the past hour" — exposed as `Precipitation now`,
  which is named for its role rather than this window (see "Entity naming") —
  `_060` covers T→T+60, and `_120` covers T+60→T+120.
- **Grid**: `xsize=1100`, `ysize=1200`, `xscale=yscale=1000.0 m`
- **Projection**: `+proj=stere +lat_ts=60 +lat_0=90 +lon_0=10 +x_0=543196.835... +y_0=3622588.861...` (WGS84)
- **Fetching**: `RadvorRS.update()` downloads one tar and extracts the `_000`, `_060`, `_120` members using stdlib `tarfile`

## HymecNG product specifics

- **URL**: `https://opendata.dwd.de/weather/radar/composite/hymecng/composite_HymecNG_YYYYMMDD_HHMM_000-hd5`
- **Archive**: none — one plain `.hd5` file per 5-minute release (single `_000` grid)
- **Format**: ODIM_H5 H5rad 2.3, `object=COMP`, `quantity=CLASS`, `gain=1`, `offset=0`
- **Grid**: identical to RS/RV (1200×1100, same projection) → reuses `get_rs_grid_index` / `RS_GRID_SHAPE`
- **Encoding**: `uint8` class index 0–10; `nodata=255` (outside coverage → sensor `unknown`), `undetect=254` (scanned, no echo → `no_precipitation`)
- **Classes** (`PRECIP_TYPE_BY_INDEX` in `const.py`): 0 no_precipitation, 1 not_classified, 2 drizzle, 3 rain, 4 freezing_drizzle, 5 freezing_rain, 6 sleet, 7 snow, 8 graupel, 9 hail, 10 large_hail
- **Sensor**: one `SensorDeviceClass.ENUM` "Precipitation type" sensor; state labels are translated via the `precipitation_type` entity translation key
