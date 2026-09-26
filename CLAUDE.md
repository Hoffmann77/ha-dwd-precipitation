# DWD Precipitation — Codebase Guide

## What this is

A HomeAssistant custom component that pulls DWD (German Weather Service) radar composites and exposes per-location precipitation sensors. It fetches Cartesian grids, finds the nearest grid cell to the user's configured lat/lon, and reports the cell value.

## Architecture

```
__init__.py           Entry point. Builds one coordinator per product from
                      PRODUCT_CLASSES, refreshes them concurrently, and asks
                      each to register its own release schedule.
coordinator.py        BaseProductUpdateCoordinator: the per-product HA
                      DataUpdateCoordinator. Owns release timing, the
                      fetch/stale/retry lifecycle, and the backoff ramp.
products.py           One BaseProductUpdateCoordinator subclass per DWD
                      product. Each handles its own URL, fetch, parse, and
                      grid lookup.
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

One coordinator per product, each on its own schedule — there is no shared
poll loop.

1. A time-change tracker (`track_time_change_args`) fires at the product's
   release time and calls `coordinator.async_refresh()`
2. `_async_update_data()` computes `latest_release`, and returns the cached
   payload untouched if that release was already fetched
3. `_fetch_and_parse(latest_release)` downloads and parses the file, extracts
   `data[self.index]`, and returns `(precipitation, metadata)`
4. The coordinator wraps those in a `CoordinatorData` — its `data`/`metadata`
   are a scalar for RADOLAN products, parallel lists for RS, parallel dicts
   for RV
5. `PrecipitationSensorEntity.native_value` calls
   `description.value_fn(coordinator.data.data)`

## Failure handling

Fetches fail routinely — DWD publishes a few minutes late often enough that a
404 on the first attempt is the normal case, not an incident. Three rules keep
that from turning into noise:

- **Retry with a per-product backoff.** The first failure arms a 60 s retry,
  and each further consecutive failure adds 10 s, capped at the product's
  `MAX_FAST_POLL_INTERVAL` (5 min; 15 min for the daily `sf_2350`). Only a
  successful fetch resets the ramp — a newly-due release does not, so a long
  DWD outage settles at the cap instead of hammering OpenData every minute.
  The ramp runs whether or not the entity is currently available; it is
  cancelled only on success or config-entry unload.
- **Nothing is scheduled on a bare constant.** Every install would otherwise
  fetch on the same second and, after a shared DWD outage, retry in lockstep
  forever. Each coordinator takes a whole-second `_fetch_jitter` in
  `[0, MAX_FETCH_JITTER]` (30 s) from `fetch_jitter_for(entry_id, product_key)`
  and exposes `release_delay = RELEASE_DELAY + _fetch_jitter`. That offset is
  *derived*, not drawn, so an install keeps it across restarts and reloads: the
  schedule in a user's log is the one they saw last week, and changing an
  unrelated option does not move their fetch times. It is a sha256 digest
  rather than `hash()` or `random.seed()`, since str hashing is salted per
  process and only a digest is contractually stable across runs; a test pins
  one value, because changing the derivation reschedules every existing
  install. Retries are the opposite case and get a fresh +/-`RETRY_JITTER`
  (15%) each attempt: a fixed offset would preserve the lockstep a shared
  outage creates rather than break it.

  The fetch jitter belongs in the *delay*, not in a sleep before the request.
  The schedule, the release lookup and the staleness deadline are all derived
  from `release_delay`, so adding it there shifts them together and the margin
  between the fetch grid and the deadline is untouched — a test asserts the
  margin is identical for every jitter value. Delaying the fetch on its own
  would eat that margin instead, and the tightest one is only 60 s. The offset
  is whole seconds because `track_time_change_args` is built from a whole-second
  grid, and never negative, so a fetch is never earlier than the calibrated
  publication lag. `RELEASE_DELAY` stays the pristine class constant that
  `scripts/check_release_delay.py` reads out of the source.

- **Staleness is a deadline on the overdue release, not an age limit on the
  cached one.** `_stale_deadline()` starts its clock when the release *after*
  the cached one should have been on OpenData, and runs for
  `OVERDUE_GRACE` — so the tolerance answers "how long do we go on trying
  for a release that is already due", a property of the retrying rather than of
  the publication cadence. Entities read `coordinator.data_is_reportable` for
  their availability, so a value that ages out stops being reported even if no
  further fetch is attempted; `_schedule_stale_check()` arms a callback on the
  deadline after each success so HA looks again when nothing else would make it.

  `data_is_reportable` folds the deadline together with the
  `unavailable_when_stale` option, and is the *only* place that decision is
  made. `_async_update_data` asks it the same question to decide whether a
  failed fetch is worth an `UpdateFailed`: the two are exact complements, and
  spelling them out separately is how an entity ends up reporting a value the
  coordinator has already given up on.

  Anchoring matters. Measure the tolerance from the *cached* release and it has
  to be expressed in release intervals, so it expires exactly when some later
  fetch is due: the value is written off at the very instant of the attempt
  that might have restored it, and which of the two happens first comes down to
  event-loop latency. That is what made a routinely late file blank the sensors
  and log an ERROR every single time. Anchored on the overdue release, the
  deadline only collides with the fetch grid if `OVERDUE_GRACE` is a whole
  multiple of `RELEASE_INTERVAL` — a rule a test enforces per product. Landing
  on a *retry* is harmless by contrast: a retry is itself the attempt whose
  failure decides the verdict.

  Every product spells out its own `OVERDUE_GRACE`, most of them as
  `DEFAULT_OVERDUE_GRACE` (6 min, defined next to the fast-poll constants);
  `sf_2350` uses 30 min, because a daily total will not be replaced today
  anyway. Note this does not scale with
  `RELEASE_INTERVAL` — the hourly and daily products give up on a missed release
  just as promptly as the 5-minute ones, because the question is how long DWD is
  given to publish, not how stale the value is allowed to be.

  `_next_release_after()` walks the release grid in the product's *own* time
  reference. `sf_2350` is `USE_LOCAL_TIME`, so its releases are 23 or 25 hours
  apart on DST changeover days; adding `RELEASE_INTERVAL` to a UTC timestamp
  would put the autumn deadline before the file it is waiting for could exist.

  For the same reason `async_track_releases()` registers a `USE_LOCAL_TIME`
  product with `async_track_time_change` rather than
  `async_track_utc_time_change`. `track_time_change_args` describes the
  product's own grid, so registering `sf_2350` in UTC fetched it an offset's
  worth of hours late every day — in summer, 1.5 h after its own staleness
  deadline had already passed. The registration lives on the coordinator rather
  than in `async_setup_entry` precisely because that pairing is the thing that
  broke: the grid and the clock it is read in are one decision, and the entry
  point had only half of it.
- **One failing product must not take the entry down.** `async_setup_entry`
  refreshes all products concurrently and raises `ConfigEntryNotReady` only if
  *every* one fails. A single dead product (DWD retiring one, say) leaves its
  own entities unavailable and logs a warning, while the rest keep working.

`_describe_fetch_error()` writes the message a user actually sees. HA logs it
once per run of failures, so it is the only explanation they get: it must name
what DWD did, say whether the user's configuration is implicated (usually it is
not), and state that retries continue. Keep these strings plain ASCII — log
viewers and Windows consoles mangle typographic punctuation.

## DWD products

| Class | Key | Format | Update | Description |
|-------|-----|--------|--------|-------------|
| `RadvorRS` | `rs` | ODIM_H5 (tar) | 5 min | RADVOR nowcast, 0/60/120 min lead; each grid is a 60-min accumulation (see "RS product specifics") |
| `RadvorRV` | `rv` | ODIM_H5 (tar) | 5 min | RV nowcast, 25×5-min grids; derives +1h/+2h peak intensity (mm/h), precip start/end timing (episode/clearing end algorithm, user-selectable), and a rain-within-2h flag (whose metadata carries the raw 25-point forecast series, exposed by default) |
| `HymecNG` | `hymecng` | ODIM_H5 (single .hd5) | 5 min | Precipitation-*type* composite (rain/snow/freezing rain/hail/…); one enum "Precipitation type" sensor |
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

1. Subclass `BaseProductUpdateCoordinator` in `products.py`
2. Set `PRODUCT_KEY`, `PRODUCT_LABEL`, `RELEASE_INTERVAL`, `RELEASE_DELAY`,
   `RELEASE_OFFSET` and `OVERDUE_GRACE` (spelled out even when it is just
   `DEFAULT_OVERDUE_GRACE` — a test enforces this), plus
   `MAX_FAST_POLL_INTERVAL` if the default does not fit
3. Implement `_get_url(ts)` and `async _fetch_and_parse(ts)`
4. Override `index` (cached_property) if the grid differs from RADOLAN 900×900
5. Add sensor descriptors in `sensor.py` (new `*_SENSORS` tuple)
6. Register the class in `__init__.py` `PRODUCT_CLASSES` tuple
7. Register sensors in `sensor.py` `async_setup_entry`, and add each
   `translation_key`'s name to `translations/en.json` and `translations/de.json`
   (the two files must keep identical keys)

## Release timing

`_get_latest_release()` in `BaseProductUpdateCoordinator` computes the
most-recent valid release:
```
latest = floor((now - RELEASE_DELAY) / RELEASE_INTERVAL) * RELEASE_INTERVAL + RELEASE_OFFSET
```
`RELEASE_DELAY` = how long after the nominal product time it's available on OpenData.
`RELEASE_OFFSET` = minute/second alignment of nominal product times within the interval.

`scripts/check_release_delay.py` (run by `.github/workflows/release-delay.yml`,
scheduled) averages the *observed* availability delay across a rolling window of
recent files — for each file, its `Last-Modified` header (authoritative GMT)
minus the nominal timestamp in its name — and flags any product the instant its
mean lag exceeds its configured `RELEASE_DELAY` — the harmful direction, where
the coordinator fetches before DWD has published (`--grace` defaults to 0). It
reads the constants straight from the source with `ast` (no HA import), so the
configured value is the single source of truth.

The workflow only opens/updates a tracking issue (and fails the job) once a
product is flagged on **two consecutive scheduled runs** — a single flagged run
just records the streak (via `actions/cache`) without notifying, so one-off
measurement noise doesn't page anyone. The streak resets to zero as soon as a
run comes back clean.

## Grid lookup

### RADOLAN (RW, SF)
`RadolanProduct.index`: calls `get_radolan_grid(wgs84=True)` to get the full
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
