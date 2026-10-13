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
precipitation_total.py
                      Pure running-total logic: the persisted total payload
                      (with its pending backfill), the reading filter, and the
                      missed-release walk used by the PrecipitationTotalSensor
                      in sensor.py.
rain_events.py        Pure rain-event tracker behind the Rain events sensor
                      (see "Rain events"). HA-free,
                      no relative imports: the parser tier tests it.
config_flow.py        UI config flow: collects name + lat/lon; options form
                      with a collapsed Advanced section, stored flat.
const.py              DWD OpenData base URLs and HA constants.
utils.py              async_get() HTTP helper (headers, status, separate 206
                      cap); get_previous_multiple() for computing the most
                      recent release timestamp.
radar/                Embedded parsers (no heavy external deps).
  odim.py             ODIM_H5 (HDF5) reader for every product (RS, RV,
                      HymecNG, RW/SF in their HDF5 edition) and the DE1200
                      grid lookup.
  tar_range.py        Reads selected members of a remote tar by HTTP range
                      requests (see "Range reads"). HA-free.
```

## Data flow

One coordinator per product, each on its own schedule — there is no shared
poll loop.

1. A time-change tracker (`track_time_change_args`) fires at the product's
   release time and calls `coordinator.async_refresh()`
2. `_async_update_data()` computes `latest_release`, and returns the cached
   payload untouched if that release was already fetched
3. `_fetch_and_parse(latest_release)` downloads the file on the event loop,
   then hands the bytes to the product's blocking `_parse()` through
   `hass.async_add_executor_job`, which extracts `data[self.index]` and returns
   `(precipitation, metadata)`. Decoding never runs on the event loop: a
   radar grid is one gzip chunk of 1.3 M cells, ~6 ms to inflate even on a fast
   machine, times 25 members for RS/RV — many users run HA on a Raspberry Pi
4. The coordinator wraps those in a `CoordinatorData` — its `data`/`metadata`
   are a scalar for RADOLAN products (`None` for a nodata cell, which the ODIM
   reader returns as NaN), parallel lists for RS (`[_000, _060,
   _120, peak, next_120]`, `peak` being `None` unless `full_rolling_series`
   is on, `next_120` = `_060 + _120`),
   parallel dicts for RV
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
| `RadvorRS` | `rs` | ODIM_H5 (tar) | 5 min | RADVOR nowcast, 25 rolling 60-min accumulations; exposes the 0/60/120 min leads and the 120-min total (60 + 120), plus — only with the `full_rolling_series` option — the wettest future hour with the 25-point rolling-hour series (see "RS product specifics") |
| `RadvorRV` | `rv` | ODIM_H5 (tar) | 5 min | RV nowcast, 25×5-min grids; derives the current intensity (lead 0 × 12, mm/h, with the raw 5-min amount), peak intensity (mm/h) over the first hour, the second and both, precip start/end timing (episode/clearing end algorithm, user-selectable), a rain-within-2h flag (whose metadata carries the raw 25-point forecast series, exposed by default), and by default the wettest future hour (see "Peak hourly precipitation") |
| `HymecNG` | `hymecng` | ODIM_H5 (single .hd5) | 5 min | Precipitation-*type* composite (rain/snow/freezing rain/hail/…); one enum "Precipitation type now" sensor |
| `RadolanRW` | `rw` | ODIM_H5 (RADOLAN HDF5 edition) | 1 h | 1-hour precipitation analysis (gauge-adjusted), the run ending on the hour: one clock hour per release (see "RW 10-minute runs") |
| `RadolanRW10` | `rw_10min` | same as RW | 10 min | RW's 10-minute runs: the sliding hour ending at each :x0. Built only for a dry streak counting RW (see "RW 10-minute runs") |
| `RadolanSF` | `sf` | ODIM_H5 (RADOLAN HDF5 edition) | 1 h | 24-hour precipitation analysis |
| `RadolanSFLastYesterday` | `sf_2350` | same as SF | daily | Yesterday's 24 h total |

## Entity naming

Every entity name is set via `translation_key` + `translations/en.json` — never a
hardcoded `name=` / `_attr_name`. HA derives the entity id by slugifying the
English name, so the name is also the id: `Precipitation next 60–120 min` →
`sensor.<device>_precipitation_next_60_120_min`. Keep names slug-friendly.

A name states a window only when the window is part of the *value*. Three forms:

| form | meaning | examples |
|------|---------|----------|
| `last <N>` | measured accumulation over a sliding window ending at the latest release | `Precipitation last 60 min`, `Precipitation last 24h` |
| `next <N>` | forecast value over a future window | `Precipitation next 60 min`, `Precipitation next 60–120 min`, `Peak intensity next 60 min` |
| calendar period | the last complete clock hour / calendar day | `Precipitation previous hour`, `Precipitation yesterday` |

**Units follow the product.** The RADVOR nowcast (RS/RV) states its windows in
minutes, matching its 5-minute steps and the `minutes_until` attributes:
`next 60–120 min` says what it covers, where the old `next 1–2h` needed a note
that it is the second hour, not the coming two. RADOLAN keeps hours and days
(`last 24h`, `previous hour`, `yesterday`); `last 1440 min` would be absurd,
and none of them ever collided. `24h` keeps its released spelling (no space,
unlike `60 min`) because a space would change its slug for nothing.

`Precipitation last 60 min` is RS `_000`: the rolling hour, every 5 minutes,
from the same product as `next 60 min` / `next 60–120 min`. RW is a clock hour
(the run ending on the hour, see "RW 10-minute runs"), so it is `Precipitation
previous hour`. No two names share a window, so none needs a source qualifier:
radar vs. gauge-adjusted is explained in the README, not carried in names.
(The release branch after 2026.10.0 briefly carried `(radar)` /
`(gauge-adjusted)` suffixes; they never shipped.)

**Never reuse an old slug for a different value.** Keys did not change, so
existing installs keep their entity ids and only see new names; new installs
get the new slugs. Up to 2026.10.0 the names were: RS `_000` `Precipitation
now` (`precipitation_now`, named for its role, which hid that it is mm over the
past hour and not a rate), RW `Precipitation last 1h` (`precipitation_last_1h`),
and the forecasts `next 1h`, `next 1–2h`, `Peak intensity next 1h` /
`next 1–2h`, `Peak hourly precipitation next 2h`, and HymecNG's
`Precipitation type`. None of the new slugs is one
of those, so an id means one thing on every install, and HA's "recreate entity
ids" on an old install cannot collide (giving RS `precipitation_last_1h` was
considered and rejected for exactly that: RW still holds it there, so RS would
land on `_2`). The README lists the old ids for older installs.

`now` means the latest 5-minute analysis, ending at the release time:
`Precipitation intensity now` (RV lead 0 × 12, mm/h) and `Precipitation type
now` (HymecNG). The README states that "now" is the analysis window, which
ended 3–10 minutes before the value appears. A window total is never `now`
(that was RS `_000`'s old name, see above).

`Precipitation next 120 min` (RS `_060 + _120`) and `Peak intensity next 120
min` (RV, the max over leads 5–120) cover the whole horizon, so no sum or max
of two sensors is needed in a template. The total is RS's two forecast hours
added, not RV's 24 steps summed, so it is exactly the sum of the two sensors
shown next to it; it is `None` when either hour is, since half a forecast is
not a 120-minute total.

Everything else carries no window, and should keep it that way. The RV 2 h
horizon in particular is a property of the *algorithm*, not of the value, so it
belongs in the docs rather than in four entity names:

- `Precipitation start` / `Precipitation end` answer *when*; outside the horizon
  the state is simply `unknown`.
- `Precipitation expected` is a flag; `off` already covers "not in the horizon".

`Precipitation total` / `Precipitation total daily` are the exception to the
window rule: they hold no window at all (an ever-growing sum since setup). They
are `TOTAL_INCREASING` and keyed on the release timestamp, never on the value
changing: two equally wet hours are two releases, and a release seen twice is
counted once. RW backs `Precipitation total`, the one to use: it is up to date
within the hour, and HA's statistics see each hour one hour late (11:00-12:00
is added at ~12:28), so only the last hour of a day spills into the next.
`sf_2350` backs the daily one, whose rain every day lands in the *next* day's
statistics; it stays because 2026.10.0 shipped it (removing it would orphan
users' entities), but `entity_registry_enabled_default=False`. That only
applies when HA first registers the entity, so installs that had it keep it
enabled, and new ones get it disabled; enabling it reloads the entry and it
starts from 0, like any new total. The `sf_2350` coordinator runs either way,
for `Precipitation yesterday`. They are separate entities rather
than one with a source option, because switching the source would make a
`TOTAL_INCREASING` sensor jump. Up to 2026.10.0 they were `(hourly)` /
`(daily)`; the daily one keeps its slug (`precipitation_total_daily`), the
hourly one gets the new `precipitation_total`.

**Backfill.** Missed releases (`missed_releases`, at most `max_backfill`: 48
for RW, 7 for `sf_2350`, what OpenData keeps) go on a `pending` list stored in
the restore data with the total. `_async_backfill` fetches them oldest first
and removes each only once it has been added (or turned out to hold no data
for the cell), so a restart resumes the list (`_start_backfill` at startup)
and a failed fetch is retried with the next counted release. A new release is
the retry trigger, not every coordinator update: during a DWD outage the
coordinator's own fast-poll retries would otherwise refetch the backlog each
minute. `split_fetchable` gives up on entries older than `max_backfill`
releases, walking the grid so DST days count as one release, and logs once
per batch dropped. One round runs at a time; releases that join meanwhile are
picked up by the running round.

`Peak intensity next 60 min` / `next 60–120 min` drop the `Precipitation` head
noun on purpose: they are mm/h rather than mm, and the shorter head stops them
reading as near-duplicates of `Precipitation next 60 min` / `next 60–120 min`
in the entity list.

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
4. Override `index` (cached_property) if the grid differs from DE1200
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

The lookup returns the cell that *contains* the location: project it, then
**floor** its offset from the grid's outer lower-left corner. Never round, and
never take the nearest grid coordinate unless those coordinates are pixel
centres — the corner references below are pixel *edges*, and treating them as
centres shifts the lookup by half a cell, which picks a neighbouring cell for
~3 locations in 4. Both lookups the integration had then were wrong that way
until 2026.10; since RW/SF moved to HDF5 there is only the DE1200 one.

The reference tier checks it against wradlib's own grid (`mode="edge"`),
not against a reimplementation of our arithmetic, and pins wradlib's DE1200
grid to the fixture file's corner attributes. Fixture coordinates are cell
*centres*; a corner would sit on the boundary of four cells. The same wradlib
reference (`tests/wradlib_ref.py`) runs daily on live DWD files for every
product via `.github/workflows/live-wradlib.yml` (`tests/live_wradlib/`):
fixed locations must land on the same cell with the same value, and every
member's full grid must decode identically.

### RADOLAN (RW, SF)
Read in their **HDF5 edition** (`raa01-<p>_10000-<yymmddHHMM>-dwd---bin.hdf5`),
which is ODIM_H5 on the same DE1200 grid as RS below, so `RadolanProduct.index`
is `get_rs_grid_index` and `_parse` is `read_odim_composite_cell` (ACRR,
gain 0.1, nodata 65535 -> NaN -> `None`). DWD announced that the legacy binary
edition (.bz2, national 900x900 spherical grid) would be switched off; it is
still published, but nothing reads it any more, and its reader
(`radar/radolan.py`, `radar/georef.py`, extracted from wradlib) was removed
with its tests and fixtures. Git history has them if the binary edition is ever
needed again.

The two editions are the same analysis on different grids, not a cell-for-
cell copy: checked on live files (2026-10-12), area means over ~1100 locations
agree to 1 % (SF 0.717 vs 0.725 mm), while a location's own value differs in
~65-80 % of wet cases (median 0.1 mm, up to a few mm in sharp gradients) and
is found in the old cell's 3x3 neighbourhood only ~60 % of the time. So users
see small value changes at the switch; nothing else changes. Timing: RW's HDF5
file appears ~25.7 min after its window ends, like the binary one; SF's ~29.3
min, ~2.5 min *later* than its binary one, hence SF's `RELEASE_DELAY` of 31 min.

### RS (ODIM_H5)
`RadvorRS.index` calls `get_rs_grid_index(lat, lon)` from `radar/odim.py`.
Ellipsoidal polar-stereographic forward projection (WGS84 a=6378137m, O(1)).
Grid: 1200 rows × 1100 cols, 1km, same `+proj=stere +lat_ts=60 +lat_0=90 +lon_0=10`
family as RADOLAN but WGS84 ellipsoid, different false easting/northing, and larger extent.
The ODIM `LL_*`/`UL_*`/`UR_*`/`LR_*` attributes are the *outer* corners of the
edge pixels (LL projects to x = −500 m, y = −1 199 500 m); pixel centres sit on
whole kilometres, the north-west one at the projection origin (RV format
description §3.1). Row 0 is the north edge. `rs_grid_contains` relies on the
same floor, so a point just outside an edge is correctly rejected. This is
wradlib's `dwd-radolan-wgs84-de1200` grid.

## The radar/ directory

wradlib is not a runtime dependency (it pulls in many heavy packages that
cannot be installed in standard HA environments); it is used only by the
reference tiers. The RADOLAN binary reader once extracted from it is gone (see
"RADOLAN (RW, SF)").

`radar/odim.py` is original code that uses `h5py` directly. It exposes
`read_odim_composite` (physical quantities like RS/RV's `ACRR`, scaled by
gain/offset), `read_odim_composite_cell` (the same for one cell — what RS/RV
use, since scaling and masking the whole grid to keep one value was over half
the decode time; libhdf5 still inflates the single whole-grid chunk, so reading
fewer *cells* cannot save more) and `read_odim_classification` (HymecNG's `CLASS` quantity —
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
  `_000` is "precipitation over the past hour" — exposed as `Precipitation last
  60 min` (see "Entity naming") —
  `_060` covers T→T+60, and `_120` covers T+60→T+120.
- **Grid**: `xsize=1100`, `ysize=1200`, `xscale=yscale=1000.0 m`
- **Projection**: `+proj=stere +lat_ts=60 +lat_0=90 +lon_0=10 +x_0=543196.835... +y_0=3622588.861...` (WGS84)
- **Rolling windows**: the members in between are the same 60-minute sum sliding
  in 5-minute steps — lead L covers T+L−60 → T+L, so neighbours overlap by 55 min.
  RS is radar-only, like RV: `_060` equals the sum of RV leads 5–60 cell for cell
  (checked against live data). Only RADOLAN RW/SF are gauge-adjusted.
- **Fetching**: by default `RadvorRS._fetch_and_parse()` reads only
  `_000`/`_060`/`_120`, by range (see "Range reads"); with the
  `full_rolling_series` option it downloads the whole tar for all 25. Either
  way `_parse()` gets the members' bytes and decodes them off the loop. The
  payload list is `[_000, _060, _120, peak, next_120]`, where `peak` is
  `None` unless the option is on and `next_120` is `_060 + _120`.

## Peak hourly precipitation

`Peak hourly precipitation next 120 min` is the wettest rolling hour wholly in the
future (windows ending at +60..+120, `FUTURE_HOUR_LEADS`; ties go to the earlier
window), with the window as `data_start`/`data_end` (`None` on a dry forecast)
and the rolling-hour series as `rolling_1h`. Two products can feed it, and
`_peak_hour_sensor()` binds the entity to one at setup (options reload the entry):

- **RV (default)** sums twelve 5-minute steps per window (`rolling_hour_sums`),
  reusing the 25 members RV decodes anyway. It can only build windows wholly in
  the forecast, so the series has 13 points.
- **RS (`full_rolling_series` on)** decodes all 25 members, adding the 12
  windows that straddle now. ~+140 ms per release.

The two are interchangeable by construction: RS *is* summed RV, verified on
live data to 0.000 mm in every cell. A missing RV step counts as 0 because that
is what RS reports at the coverage edge, and both round to the ODIM 0.001 mm
resolution (`MM_DECIMALS`). Keep it that way — flipping the option must not
move the state, and a test asserts both paths give the same peak, window and
series. The entity key `radvor_peak_1h_120` is deliberately product-neutral so
the entity survives the switch.

## Dry streak source

`Timespan without precipitation` resets when a past-hour total reaches
`precipitation_reset_threshold`. The `dry_streak_source` option picks the
product, and its values are product keys, so `async_setup_entry` binds the
entity to `coordinators[source]` directly (options reload the entry, as for
`_peak_hour_sensor()`):

- `rw` — RW, gauge-adjusted, ~28 min late, counted from its **10-minute
  runs** (`rw_10min`, see "RW 10-minute runs"): the reset shows up to an hour
  sooner than with the hourly run alone, at the same adjustment. Scalar
  payload; the reset time is `metadata.source_timestamp`, the end of that
  sliding hour.
- `rs` — RS `_000`, radar only, a rolling hour every 5 min. List payload; the
  reading is `data[0]` / `metadata[0]`.

Both are 60-minute totals in mm, so the threshold means the same either way.
The unique id does not depend on the source, so the entity and its `dry_since`
survive a switch. There is deliberately no fallback to the other product when
the selected one fails: the entity follows its coordinator's availability.

The default is `rw`, but **existing installs keep `rs`**. The config entry is at
version 1.2: `async_migrate_entry` writes `dry_streak_source: "rs"` into every
1.1 entry that lacks it, and the config flow writes the default into every new
entry. So every entry stores its source, and changing
`DEFAULT_DRY_STREAK_SOURCE` later never moves an existing install.

## RW 10-minute runs

DWD runs RW every 10 minutes, each run the hour ending at that :x0.
`RadolanRW` (`rw`) reads the run ending on the hour, so every value is a clock
hour; `RadolanRW10` (`rw_10min`) is the same file family on a 10-minute grid
(same URL pattern, same parsing, HDF5 edition). Both have a `RELEASE_DELAY` of
28 min; every run minute is observed at ~25.7 min (288 runs, 2026-10-13).

- **Why :00.** Up to 2026.10.0 `rw` read the HH:50 run. Nothing recorded why;
  it is RADOLAN's traditional hour, and SF is still only published at :50
  (OpenData has no other SF minute). But RW's :00 run is as complete, as
  timely and as strongly adjusted (below), and only a clock hour can be called
  "previous hour" and line up with HA's hourly statistics. The cost is that
  `rw` and `sf` windows are now 10 minutes apart.
- **Quality.** `scripts/compare_rw_runs.py` compares every RW run on OpenData
  (48 h) with radar-only RS `_000` for the same hour, cell for cell (RW's HDF5
  edition is on the DE1200 grid). If the sub-hourly runs used fewer gauges
  they would sit closer to RS. They do not: over 285 wet runs (2026-10-10..12)
  every run minute departs from RS alike (mean |RW-RS| 0.53-0.58 mm, 58-62 %
  relative, 76-78 % of wet cells adjusted). Rerun it before relying on this
  for anything new.
- **`rw_10min` is built only when used** (`is_needed(options)`, checked in
  `async_setup_entry`): when the dry streak counts RW. Otherwise the entry
  makes no extra requests. No sensor shows the sliding RW hour: as a "last 60
  min" it would be 28-38 min behind, where RS is 4-9 min, and gauge accuracy is
  what `Precipitation previous hour` is for. A pre-release had a
  `rw_last_hour_mode` option for it; it never shipped, and a stored value is
  ignored.
- **Never for the totals.** Consecutive runs overlap by 50 minutes, so summing
  them counts each hour six times; `Precipitation total` and its
  missed-release walk stay on the hourly grid of `rw`. The startup downtime
  correction of the dry streak also keeps using `rw`.
- **The grid move.** A total stored by 2026.10.0 has a `last_release` at :50,
  off the new grid. `first_uncounted_release()` notices that
  (`_release_at_or_before` does not map it to itself) and resumes at the first
  :00 release whose window starts after it: the 10 minutes in between are left
  out once, rather than 50 counted twice. On-grid releases, including
  `sf_2350`'s 23- and 25-hour DST days, are unaffected.

## Range reads

RS/RV tars are plain ustar archives, 25 members in lead order, served as static
files with range support. `radar/tar_range.py` (`fetch_tar_members`) reads the
members a caller needs; `products.async_read_tar_members` wraps it with
`async_get`. Used by RS in its default mode (3 members) and the RV backfill (the
analysis only). Measured on 12 live archives: RS takes 4 requests and 19-20 %
of the bytes (archives are 3.5-17.5 MB), an RV analysis 1-2 requests and 4-7 %.

- A 128 KiB head gives member 0 and the file size. The last wanted member is
  found from the end of the file first, then the rest by *interpolating*
  between known headers: member sizes shrink with lead, so extrapolating from
  the head alone misses the middle member by up to a whole member.
- Windows are scanned at 512-byte alignment for blocks that start with the
  member-name prefix and pass `tarfile`'s checksum, so HDF5 data cannot pass
  for a header.
- DWD promises neither the layout nor range support. Anything unexpected — a
  200, an unexpected first member, a header not found within `MAX_REQUESTS`,
  a 206 that does not match the request, a file replaced between requests
  (`If-Range` turns that into a 200) — falls back to the whole archive. A
  failed fetch (404, network) is not a fallback case and raises as usual.
- Not worth it elsewhere: RV needs all 25 members every release, HymecNG is one
  gzip chunk, RADOLAN files are a single small HDF5 (RW ~30 KB).

## Rain events

The `Rain events` sensor (`sensor.<device>_rain_events`, key
`radvor_rv_rain_events`) publishes the tracker's view (schema 1) as its
attributes, a contract with blueprints: field names and semantics in the
README section "Rain events". `rain_events.py` holds the logic; `RadvorRV` the
glue; `RainEventsSensor` in sensor.py the entity.

- **Opt-in.** The `rain_events` option (Advanced, default off) gates all of it:
  `rain_events_enabled()` decides whether `RadvorRV` gets a `Store`, and with
  none it skips the tracker, so an entry that does not use it makes no fill
  requests and writes nothing. Turning it off removes the entity from the
  registry (rather than leaving "no longer provided") and deletes the store,
  so turning it on again starts clean. Nothing on 2026.10.0 had it, so it is
  off for existing installs as well.
- **Own entity.** It sat on `Precipitation expected` as a `rain_events`
  attribute in pre-releases; a flag is the wrong home for a few KB that change
  every release and that blueprints depend on. The state is
  `overall_status()`: `ongoing` if any event is, else `upcoming`, else `none`
  (an `unseen` event alone is `none`), so a blueprint can trigger on the state.
  All `VIEW_KEYS` are unrecorded. A tracker failure leaves the view out, so
  the state is `unknown`, not a guess.

- **Steps.** The measured step ending at T is the RV analysis (lead 0) of
  release T, and no other release has it, so the integration keeps measured
  steps itself. The published series is 12 measured + 24 forecast steps. A step
  is wet strictly above `wet_step_milli(rain_event_threshold)` thousandths
  (integer arithmetic; selects exactly the steps above option/12).
- **Recomputed, not accumulated.** The state keeps every measured step from
  the start of the oldest ongoing event (two steps earlier, which decide
  `start_clipped`) and from its onset snapshot. Each release rebuilds the
  timeline and recomputes every event's amounts and peaks from its own steps.
  This is a deliberate deviation from the spec's incremental accumulators: same
  values, but a late fill can never be counted twice and `observed` can never
  go down. A multi-day event is a few KB of store.
- **Unknown steps bridge, bounded.** An unknown step never splits a run;
  for *ending* an event it counts as dry only once it has left the window (it
  can no longer be filled), which then ends the event as `end_clipped`. More
  than `MAX_UNKNOWN_BRIDGE` (36 steps, 3 h) unknown in a row count as dry, so
  a restart mid-storm keeps the event and a multi-day outage does not glue new
  rain onto an old event.
- **Ended events** move to `last_ended` and are final; their span is kept in
  `ended_spans` while it is in view, so their rain is not picked up again.
- **Fill before matching.** `RadvorRV._async_fill_missed` fetches each unknown
  measured step in the window (analysis only, by range), newest first,
  sequentially, within `RAIN_FILL_BUDGET`; the first failure ends the round,
  with one warning per run of failures. A release without data for the cell
  is recorded as such and not refetched.
- **Persistence.** One `Store` per entry (`rain_events_store_key`). Written
  `RAIN_SAVE_DELAY` after a release while something is at stake (an event, a
  wet or unknown step, a new `last_ended`); otherwise the delayed save is
  pushed back by every release and happens at shutdown, so a dry day costs no
  writes. Unload writes it at once (an options reload must read it back),
  `async_remove_entry` deletes it, an unreadable store is discarded.
- **Isolation.** A tracker failure is logged once and leaves the attribute
  out; it never fails the RV update the other sensors depend on.
- **Threshold.** `rain_event_threshold` is independent of
  `precipitation_threshold` (no `max()`); changing it drops the events (new
  ids) but keeps the measured steps and `last_ended`.

## Options form

The options form nests rarely needed options in a collapsed `advanced_options`
section (`data_entry_flow.section`): `rain_events`, `rain_event_threshold`,
`precipitation_end_algorithm`, `full_rolling_series`, `unavailable_when_stale`.
Only the *form* is nested: `async_step_init` flattens the section before
saving, so every key stays where `entry.options.get(...)` looks for it and no
migration is needed. Translations live under
`options.step.init.sections.advanced_options`. HA 2026.10 installs `probatio`
as `voluptuous` at import time, which is why `vol.Schema` inside `section`
serializes; a script importing `voluptuous` before `homeassistant` sees the
real one and cannot serialize the form.

## HymecNG product specifics

- **URL**: `https://opendata.dwd.de/weather/radar/composite/hymecng/composite_HymecNG_YYYYMMDD_HHMM_000-hd5`
- **Archive**: none — one plain `.hd5` file per 5-minute release (single `_000` grid)
- **Format**: ODIM_H5 H5rad 2.3, `object=COMP`, `quantity=CLASS`, `gain=1`, `offset=0`
- **Grid**: identical to RS/RV (1200×1100, same projection) → reuses `get_rs_grid_index` / `RS_GRID_SHAPE`
- **Encoding**: `uint8` class index 0–10; `nodata=255` (outside coverage → sensor `unknown`), `undetect=254` (scanned, no echo → `no_precipitation`)
- **Classes** (`PRECIP_TYPE_BY_INDEX` in `const.py`): 0 no_precipitation, 1 not_classified, 2 drizzle, 3 rain, 4 freezing_drizzle, 5 freezing_rain, 6 sleet, 7 snow, 8 graupel, 9 hail, 10 large_hail
- **Sensor**: one `SensorDeviceClass.ENUM` "Precipitation type now" sensor (key `hymecng_precipitation_type`); state labels are translated via the `precipitation_type_now` entity translation key
