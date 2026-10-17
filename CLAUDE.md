# DWD Precipitation — Codebase Guide

## What this is

A HomeAssistant custom component that pulls DWD (German Weather Service) radar composites and exposes per-location precipitation sensors. It fetches Cartesian grids, finds the grid cell that contains the user's configured lat/lon, and reports the cell value.

Why things are the way they are, and what they were before, is in
`docs/adr/` (architecture decision records); this guide states the rules.

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
entity.py             DwdCoordinatorEntity, the base of every entity: unique
                      id, device, availability (data_is_reportable), and the
                      description mechanism (DwdEntityDescriptionMixin:
                      product_key, sub_key, attrs_fn, metadata_attrs_fn).
sensor.py             HA SensorEntity descriptors; sub_key picks each value
                      from coordinators[product_key].data.
binary_sensor.py      "Precipitation expected" (RV), on the same descriptions;
                      its forecast_5min series is always exposed, unlike the
                      sensors' diagnostics (blueprints read it).
dry_streak.py         Pure "days without rain" logic: the persisted anchor
                      payload + threshold/downtime-correction helpers used by
                      the TimespanWithoutPrecipitationSensor in sensor.py.
precipitation_total.py
                      Pure running-total logic: the persisted total payload
                      (with its pending backfill), the reading filter, and the
                      missed-release walk used by the PrecipitationTotalSensor
                      in sensor.py.
config_flow.py        UI config flow: collects name + lat/lon; options form
                      with a collapsed Advanced section, stored flat.
options.py            DwdOptions: the entry's options as one typed snapshot,
                      with every option's default in DEFAULT_OPTIONS. Read as
                      coordinator.options / entry.runtime_data.options; never
                      entry.options.get() elsewhere.
const.py              Option keys and defaults, payload sub-keys (KEY_*),
                      HymecNG's class labels, and other HA constants.
utils.py              async_get() HTTP helper (headers, status, separate 206
                      cap, stall timeout); DownloadCache (one download per
                      URL for an entry's products); FailureLatch. HA-free.
rain_events_tracker.py
                      RainEventsTracker: one entry's rain events in HA
                      (store, background fill, save policy).
release_grid.py       ReleaseGrid: a product's release times on its own
                      clock (see "Release timing"). HA-free, no relative
                      imports: the parser and live tiers import it as is.
radar/                The HA-free core: parsers and pure domain logic (no
                      heavy external deps). Its modules import each other
                      relatively, which works both inside HA and in the
                      parser tier (which imports it as `radar`).
  __init__.py         Exports what the integration reads (the cell readers
                      and their grid errors); the whole-grid readers are for
                      the test tiers and scripts/, from radar.odim.
  urls.py             Every product's OpenData URL pattern (product_url,
                      radvor_prefix), for the products, scripts/ and the
                      live tiers alike.
  grid.py             The grid a file describes in its /where group, and
                      the cell holding a location on it (see "Grid lookup").
  odim.py             ODIM_H5 (HDF5) reader for every product (RS, RV,
                      HymecNG, RW/SF in their HDF5 edition): the cell at a
                      location, on the file's own grid.
  tar_range.py        Reads selected members of a remote tar by HTTP range
                      requests (see "Range reads").
  nowcast.py          RV lead grid and the nowcast logic: start/end
                      detection, peak intensities, rolling-hour sums.
  rain_events.py      Rain-event logic behind the Rain events sensor
                      (see "Rain events").
  isotime.py          iso()/parse_utc() for attributes and stored payloads.
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
   `hass.async_add_executor_job`, which reads the cell holding `self.coords`
   on the grid the file describes and returns `(data, metadata)`. Decoding never runs on the event loop: a
   radar grid is one gzip chunk of 1.3 M cells, ~6 ms to inflate even on a fast
   machine, times 25 members for RS/RV — many users run HA on a Raspberry Pi
   `_fetch_and_parse` has no side effects, so `async_fetch_release(ts)` can
   fetch any past release (the totals' backfill) without moving the
   coordinator. What adopting a release should also do goes in
   `_async_on_new_release(release, data, metadata)`, called once per adopted
   release before it is published, never raising: RV feeds the rain-events
   tracker there.
4. The coordinator wraps those in a `CoordinatorData`. Every product has the
   same shape: `data` and `metadata` are dicts keyed by the same sub-keys
   (`KEY_*` in `const.py`, except RV's own), `metadata` holding each value's `ProductMetadata`
   (or `None`). RADOLAN has one, `amount` (`None` for a nodata cell, which the
   ODIM reader returns as NaN); HymecNG `precipitation_type`; RS `last_60`,
   `next_60`, `next_60_120` (members `_000`/`_060`/`_120`) and `next_120`
   (`_060 + _120`); RV its derived values (`max_060`, `start_at`,
   `rain_within_2h`, `peak_1h`, ...)
5. An entity's value is `coordinator.data.data[description.sub_key]` and its
   metadata `coordinator.data.metadata[description.sub_key]`
   (`DwdCoordinatorEntity._value` / `_metadata`)

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
  `scripts/check_release_delay.py` checks.

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

  Anchoring matters: measured from the *cached* release, the tolerance
  expires exactly when some later fetch is due, so a routinely late file
  blanks the sensors (ADR 0007 has the incident). Anchored on the overdue
  release, the deadline only collides with the fetch grid if `OVERDUE_GRACE`
  is a whole multiple of `RELEASE_INTERVAL` — a rule a test enforces per
  product. Landing on a *retry* is harmless by contrast: a retry is itself the
  attempt whose failure decides the verdict.

  Every product spells out its own `OVERDUE_GRACE`, most of them as
  `DEFAULT_OVERDUE_GRACE` (6 min, defined next to the fast-poll constants);
  `sf_2350` uses 30 min, because a daily total will not be replaced today
  anyway. Note this does not scale with
  `RELEASE_INTERVAL` — the hourly and daily products give up on a missed release
  just as promptly as the 5-minute ones, because the question is how long DWD is
  given to publish, not how stale the value is allowed to be.

  The coordinator's `grid` (`ReleaseGrid`, see "Release timing") walks the
  release grid in the product's *own* time
  reference. `sf_2350` is `USE_LOCAL_TIME`, so its releases are 23 or 25 hours
  apart on DST changeover days; adding `RELEASE_INTERVAL` to a UTC timestamp
  would put the autumn deadline before the file it is waiting for could exist.

  For the same reason `async_track_releases()` registers a `USE_LOCAL_TIME`
  product with `async_track_time_change` rather than
  `async_track_utc_time_change`: `track_time_change_args` describes the
  product's own grid. The registration lives on the coordinator rather than in
  `async_setup_entry` because the grid and the clock it is read in are one
  decision (ADR 0007: registering `sf_2350` in UTC fetched it hours late).
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
| `RadvorRS` | `rs` | ODIM_H5 (tar) | 5 min | RADVOR nowcast, 25 rolling 60-min accumulations; exposes the 0/60/120 min leads, read by range, and the 120-min total (60 + 120) (see "RS product specifics") |
| `RadvorRV` | `rv` | ODIM_H5 (tar) | 5 min | RV nowcast, 25×5-min grids; derives the current intensity (lead 0 × 12, mm/h, with the raw 5-min amount), peak intensity (mm/h) over the first hour, the second and both, precip start/end timing (episode/clearing end algorithm, user-selectable), a rain-within-2h flag (whose metadata carries the raw 25-point forecast series, exposed by default), and the wettest future hour with its rolling-hour series (see "Peak hourly precipitation") |
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

A name states a window only when the window is part of the *value* (ADR 0001
has the reasoning and the names before 2026.10.1). Three forms:

| form | meaning | examples |
|------|---------|----------|
| `last <N>` | measured accumulation over a sliding window ending at the latest release | `Precipitation last 60 min`, `Precipitation last 24h` |
| `next <N>` | forecast value over a future window | `Precipitation next 60 min`, `Precipitation next 60–120 min`, `Peak intensity next 60 min` |
| calendar period | the last complete clock hour / calendar day | `Precipitation previous hour`, `Precipitation yesterday` |

**Units follow the product.** The RADVOR nowcast (RS/RV) states its windows in
minutes, matching its 5-minute steps and the `minutes_until` attributes:
`next 60–120 min` says what it covers. RADOLAN keeps hours and days
(`last 24h`, `previous hour`, `yesterday`); `last 1440 min` would be absurd,
and none of them ever collided. `24h` keeps its released spelling (no space,
unlike `60 min`) because a space would change its slug for nothing.

`Precipitation last 60 min` is RS `_000`: the rolling hour, every 5 minutes,
from the same product as `next 60 min` / `next 60–120 min`. RW is a clock hour
(the run ending on the hour, see "RW 10-minute runs"), so it is `Precipitation
previous hour`. No two names share a window, so none needs a source qualifier:
radar vs. gauge-adjusted is explained in the README, not carried in names.

**Never reuse an old slug for a different value.** A rename keeps the key, so
existing installs keep their entity ids and only see the new name; new
installs get the new slug. A new slug must not be one a released version gave
another entity: on an old install that entity still holds it, and HA's
"recreate entity ids" would put the new one on `_2`. `tests/entity_ids.py`
records the released ids by key; the setup test checks new installs against
it, and a docs test checks that the README's note for older installs names
every renamed one.

`now` means the latest 5-minute analysis, ending at the release time:
`Precipitation intensity now` (RV lead 0 × 12, mm/h) and `Precipitation type
now` (HymecNG). The README states that "now" is the analysis window, which
ended 3–10 minutes before the value appears. A window total is never `now`.

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
statistics; it stays (removing it would orphan users' entities), but
`entity_registry_enabled_default=False`. That only
applies when HA first registers the entity, so installs that had it keep it
enabled, and new ones get it disabled; enabling it reloads the entry and it
starts from 0, like any new total. The `sf_2350` coordinator runs either way,
for `Precipitation yesterday`. They are separate entities rather
than one with a source option, because switching the source would make a
`TOTAL_INCREASING` sensor jump (ADR 0005).

**Backfill.** Missed releases (`missed_releases`, at most `max_backfill`: 48
for RW, 7 for `sf_2350`, what OpenData keeps) go on a `pending` list stored in
the restore data with the total. `_async_backfill` fetches them oldest first
and removes each only once it has been added (or turned out to hold no data
for the cell), so a restart resumes the list (`_start_backfill` at startup)
and a failed fetch is retried with the next counted release. A new release is
the retry trigger, not every coordinator update: during a DWD outage the
coordinator's own fast-poll retries would otherwise refetch the backlog each
minute. Both `missed_releases` and `split_fetchable` cut at the same release,
`grid.back(current, max_backfill)`, so a DST day counts as one release and the
walk never goes further back than the window however long the outage: a gap
older than it is logged once (INFO) and left out, as is a pending entry that
aged out. One round runs at a time; releases that join meanwhile are picked up
by the running round, and the state is written once per round.

`Peak intensity next 60 min` / `next 60–120 min` drop the `Precipitation` head
noun on purpose: they are mm/h rather than mm, and the shorter head stops them
reading as near-duplicates of `Precipitation next 60 min` / `next 60–120 min`
in the entity list.

Entity `key`s are separate from names: they are the unique-id suffix, stay
product-prefixed (`radvor_*` / `radolan_*` / `hymecng_*`), and must not change
once released, since renaming one orphans the user's entity.

## Adding a new DWD product

1. Subclass a base in `products.py`: `WholeFileProduct` for one file per
   release decoded whole (HymecNG, RADOLAN), `RadvorProduct` for a RADVOR
   tar (RS, RV); `BaseProductUpdateCoordinator` itself only if neither fits
2. Set `PRODUCT_KEY`, `PRODUCT_LABEL`, `RELEASE_INTERVAL`, `RELEASE_DELAY`,
   `RELEASE_OFFSET` and `OVERDUE_GRACE` (spelled out even when it is just
   `DEFAULT_OVERDUE_GRACE` — a test enforces this), plus
   `MAX_FAST_POLL_INTERVAL` if the default does not fit
3. Add its URL pattern to `radar/urls.py` (`_get_url` derives the URL from
   `PRODUCT_KEY`). A `WholeFileProduct` implements the blocking
   `_parse(content, ts)`; the base downloads the file and runs `_parse` in the
   executor. A `RadvorProduct` implements `_fetch_and_parse` (RS reads three
   members by range, RV the whole tar). Keep `_fetch_and_parse` free of side
   effects (anything else goes in `_async_on_new_release`)
4. The cell comes from the grid each file describes in /where
   (`radar/grid.py`), so a product on another polar-stereographic grid needs
   nothing more; one in another projection needs that projection in `grid.py`
5. Add sensor descriptors in `sensor.py` (new `*_SENSORS` tuple)
6. Register the class in `__init__.py` `PRODUCT_CLASSES` tuple
7. Register sensors in `sensor.py` `async_setup_entry`, and add each
   `translation_key`'s name to `translations/en.json` and `translations/de.json`
   (the two files must keep identical keys)
8. Add it to `PRODUCTS` in `scripts/check_release_delay.py`, so its
   `RELEASE_DELAY` is checked against what DWD actually does

## Release timing

Every release computation goes through the coordinator's `grid`, a
`ReleaseGrid(RELEASE_INTERVAL, RELEASE_OFFSET, tz)` on the product's own clock
(HA's local zone for `USE_LOCAL_TIME`, else UTC): `at_or_before`,
`next_after`, `previous`, `back`, `walk`. `_get_latest_release()` is the
most-recent release that is ours to fetch:
```
latest = grid.at_or_before(now - release_delay)
       = floor((now - RELEASE_DELAY - jitter - RELEASE_OFFSET) / RELEASE_INTERVAL)
         * RELEASE_INTERVAL + RELEASE_OFFSET      (on the grid's wall clock)
```
`RELEASE_DELAY` = how long after the nominal product time it's available on OpenData.
`RELEASE_OFFSET` = minute/second alignment of nominal product times within the interval.
A wall time that occurs twice (the autumn hour) means its first occurrence;
no product sits in that hour.

`scripts/check_release_delay.py` (run by `.github/workflows/release-delay.yml`,
scheduled) averages the *observed* availability delay across a rolling window of
recent files — for each file, its `Last-Modified` header (authoritative GMT)
minus the nominal timestamp in its name — and flags any product the instant its
mean lag exceeds its configured `RELEASE_DELAY` — the harmful direction, where
the coordinator fetches before DWD has published (`--grace` defaults to 0). It
imports the product classes and checks their own constants, so it runs in the
`ha-test` environment.

The workflow only opens/updates a tracking issue (and fails the job) once a
product is flagged on **two consecutive scheduled runs** — a single flagged run
just records the streak (via `actions/cache`) without notifying, so one-off
measurement noise doesn't page anyone. The streak resets to zero as soon as a
run comes back clean.

## Grid lookup

Every product reads the cell holding the location on the grid **its own file
describes** in its ODIM `/where` group, not on a copy of DWD's grid in the
code (ADR 0010): if DWD moves or resizes a grid, the integration keeps reading
the cell that holds the location. `radar/grid.py` builds the `Grid`; the cell
readers in `radar/odim.py` take the location, read `/where`, and require the
payload to be exactly that grid (which also bounds what a crafted file can
make them inflate, with `MAX_CELLS` on the declared size).

The lookup returns the cell that *contains* the location: project it, then
**floor** its offset from the grid's outer lower-left corner. Never round, and
never take the nearest grid coordinate unless those coordinates are pixel
centres — the corner references are pixel *edges*, and treating them as
centres shifts the lookup by half a cell, which picks a neighbouring cell for
~3 locations in 4 (ADR 0008). A location off the grid raises `OutsideGrid`,
which the coordinator reports as such rather than as a DWD fault.

**Tolerant of spelling, strict on geometry.** Only north-polar stereographic
on an ellipsoid is computed. `projdef` is read in any parameter order, as
bytes or str, with the ellipsoid as `+a`/`+b` or named (`+ellps`/`+datum`
WGS84, GRS80); `+units=m`, `+no_defs`, `+type`, `+wktext` and a zero
`+towgs84` are ignored. Anything else that could move a cell (another
projection, an unknown parameter, a datum shift) raises `UnsupportedGrid`:
refused, never read at the wrong cell. RS, RV and HymecNG describe DE1200 one
way, RW and SF (the RADOLAN edition) another (parameter order, corners rounded
to 8 decimals); both give the same cells. A built grid is cached per
description (`lru_cache`), since every member of a release repeats it.

The config flow cannot read a grid before any file exists, so it only checks
a latitude/longitude box around DE1200 (`COVERAGE_LAT`/`COVERAGE_LON`, a test
checks the box holds the whole grid); a location in the box but off a
product's grid is reported when that product is read.

The reference tier checks the fixture file's grid against wradlib's own grid
(`mode="edge"`), not against a reimplementation of our arithmetic, and pins
wradlib's DE1200 grid to the fixture's corner attributes. Fixture coordinates
are cell *centres*; a corner would sit on the boundary of four cells. The same
wradlib reference (`tests/wradlib_ref.py`) runs daily on live DWD files for
every product via `.github/workflows/live-wradlib.yml` (`tests/live_wradlib/`):
each file's own grid must put fixed locations on wradlib's DE1200 cells with
the same values, and every member's full grid must decode identically. That
is where a DWD grid change shows, since the integration itself follows it.

### DE1200
The grid every product is on today: 1200 rows × 1100 cols of 1 km,
`+proj=stere +lat_ts=60 +lat_0=90 +lon_0=10` on WGS84. The ODIM
`LL_*`/`UL_*`/`UR_*`/`LR_*` attributes are the *outer* corners of the edge
pixels (LL projects to x = −500 m, y = −1 199 500 m); pixel centres sit on
whole kilometres, the north-west one at the projection origin (RV format
description §3.1). Row 0 is the north edge. This is wradlib's
`dwd-radolan-wgs84-de1200` grid; `tests/factories/odim.py` keeps its
description (`DE1200_WHERE`) as test data.

### RADOLAN (RW, SF)
Read in their **HDF5 edition** (`raa01-<p>_10000-<yymmddHHMM>-dwd---bin.hdf5`),
which is ODIM_H5 on DE1200 like RS, with `_parse` reading
`read_odim_composite_at` (ACRR, gain 0.1, nodata 65535 -> NaN -> `None`). The
legacy binary edition (.bz2, national 900x900 grid) is not read; ADR 0004 has
the switch, how the two editions compare, and why SF's `RELEASE_DELAY` is
31 min.

## The radar/ directory

wradlib is not a runtime dependency (it pulls in many heavy packages that
cannot be installed in standard HA environments); it is used only by the
reference tiers.

`radar/odim.py` is original code that uses `h5py` directly. It exposes
`read_odim_composite` (physical quantities like RS/RV's `ACRR`, scaled by
gain/offset), `read_odim_composite_at` (the same for the cell holding a
location — what RS/RV/RADOLAN use, since scaling and masking the whole grid to
keep one value was over half the decode time; libhdf5 still inflates the
single whole-grid chunk, so reading fewer *cells* cannot save more) and
`read_odim_classification` (HymecNG's `CLASS` quantity — discrete class
indices returned unscaled, with the `nodata`/`undetect` sentinels preserved so
the caller can tell "outside coverage" from "dry"), with
`read_odim_classification_at` as its one-cell form, which HymecNG uses. Both
cell readers find the cell on the file's own grid (see "Grid lookup").
`read_odim_grid` and the whole-grid readers have no runtime caller: they are
the oracle for the parser, reference and live tiers and for `scripts/`.

## Dependencies

Listed in `manifest.json` `requirements`. Only packages with binary PyPI wheels
that install cleanly in HA are acceptable. Do **not** add wradlib, pyproj, xarray,
GDAL, or other packages with complex build requirements.

Current runtime deps: `numpy`, `h5py`

## Checks

Besides the three test tiers, CI (`tests.yml`) runs ruff (F rules only) and
pyright (basic mode, settings in `pyproject.toml` `[tool.pyright]`) on the
component. Pyright checks against HA's own types, so it runs in the
`typecheck` dependency group, which is `ha-test` plus pyright. Keep it at 0
errors: fix a finding, or ignore it on its line with the reason. The one
such case is the config flow's `vol.Schema`, which HA's annotations call
`probatio.Schema`; HA installs probatio as voluptuous at runtime, and
importing probatio ourselves would break every HA from before that alias.
`reportIncompatibleVariableOverride` is off: HA entities override
`entity_description` and their cached properties by design.

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
  RS is radar-only, like RV: every member is the sum of the twelve RV 5-minute
  steps in its hour, exactly in almost every cell (ADR 0009). Only RADOLAN
  RW/SF are gauge-adjusted.
- **Fetching**: `RadvorRS._fetch_and_parse()` reads only `_000`/`_060`/`_120`,
  by range (see "Range reads"), whatever the options, and decodes them off the
  loop. The payload is keyed `last_60`/`next_60`/`next_60_120`
  (`_000`/`_060`/`_120`) and `next_120` (`_060 + _120`).

## Peak hourly precipitation

`Peak hourly precipitation next 120 min` is the wettest rolling hour wholly in the
future (windows ending at +60..+120, `FUTURE_HOUR_LEADS`; ties go to the earlier
window), with the window as `data_start`/`data_end` (`None` on a dry forecast)
and the rolling-hour series as `rolling_1h`. RV builds it: `rolling_hour_sums`
adds twelve 5-minute steps per window, from the 25 members RV decodes anyway,
and the series has the 13 windows wholly in the forecast.

With `full_rolling_series` on, the series starts an hour earlier (25 points).
The windows ending at T..T+55 also need the analyses of the 11 releases before
T: `RadvorRV._async_on_new_release` keeps each adopted release's analysis for
an hour (in memory), and `_fetch_and_parse` hands them to `_parse`
(`_past_hour`). The extra points appear only when all 11 are known, so after a
restart, or a release that was never adopted, the series has 13 points for up
to an hour. Missed analyses are not fetched: a background fill like the
rain-events tracker's is not worth it for an attribute nothing records. The
value, its window and the 13 future points are the same either way; a test
asserts it.

RS is summed RV (ADR 0009): exactly in almost every cell, while on wet
releases up to 1.8 % of the wet cells were measured off on DWD's own numbers,
a few by up to 0.54 mm. `tests/live/test_live_download.py` checks it daily by
that share (`_MIN_EXACT_WET`: same coverage, at least 90 % of wet cells
exact). So the series' first point is `Precipitation last 60 min` (RS `_000`)
in almost every cell. A missing RV step counts as 0 because that is what RS
reports at the coverage edge, and both round to the ODIM 0.001 mm resolution
(`MM_DECIMALS`). The entity key
`radvor_peak_1h_120` is product-neutral because RS used to feed it with the
option on.

## Dry streak source

`Timespan without precipitation` resets when a past-hour total reaches
`precipitation_reset_threshold`. The `dry_streak_source` option picks the
product, and its values are product keys, so `async_setup_entry` binds the
entity to `coordinators[source]` directly (options reload the entry, so
binding once at setup is enough):

- `rw` — RW, gauge-adjusted, ~28 min late, counted from its **10-minute
  runs** (`rw_10min`, see "RW 10-minute runs"): the reset shows up to an hour
  sooner than with the hourly run alone, at the same adjustment. The reading
  is `amount`; the reset time is its `source_timestamp`, the end of that
  sliding hour.
- `rs` — RS `_000`, radar only, a rolling hour every 5 min. The reading is
  `last_60`.

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
28 min, since every run minute is published alike (ADR 0002 has the measurement).

- **Why :00.** Only a clock hour can be called "previous hour" and line up
  with HA's hourly statistics, and the :00 run is as complete, as timely and
  as strongly adjusted as the :50 one (ADR 0002; `scripts/compare_rw_runs.py`
  measures it, rerun it before relying on that for anything new). SF is only
  published at :50, so `rw` and `sf` windows are 10 minutes apart.
- **`rw_10min` is built only when used** (`is_needed(options)`, checked in
  `async_setup_entry`): when the dry streak counts RW. Otherwise the entry
  makes no extra requests. When built, its :00 run is the file `rw` fetches
  too; both go through the entry's `DownloadCache` (`SHARES_FILES` on the
  RADOLAN products, which also covers `sf`/`sf_2350`), which downloads a URL
  once and keeps it for `SHARED_DOWNLOAD_TTL` (5 min). Failures are not kept,
  and the multi-MB RADVOR tars never go through it. No sensor shows the
  sliding RW hour (ADR 0003); a stored `rw_last_hour_mode` from a pre-release
  is ignored.
- **Never for the totals.** Consecutive runs overlap by 50 minutes, so summing
  them counts each hour six times; `Precipitation total` and its
  missed-release walk stay on the hourly grid of `rw`. The startup downtime
  correction of the dry streak also keeps using `rw`.
- **Off-grid restored totals.** A total stored by 2026.10.0 has a
  `last_release` at :50. `counted_on_grid()` maps it once onto the :00 release
  before the first window that starts after it (ADR 0002), so 10 minutes are
  left out once rather than 50 counted twice. On-grid releases, including
  `sf_2350`'s 23- and 25-hour DST days, map to themselves.

## Range reads

RS/RV tars are plain ustar archives, 25 members in lead order, served as static
files with range support. `radar/tar_range.py` (`fetch_tar_members`) reads the
members a caller needs; `RadvorProduct._async_read_members` wraps it with
`async_get`. Used by RS (3 members, whatever the options) and the RV backfill
(the analysis only). Measured on 12 live archives: RS takes 4 requests and 19-20 %
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
  (`If-Range` turns that into a 200) — falls back to the whole archive,
  with one WARNING per run of fallbacks and an INFO once range reads work
  again (values are unaffected, the data volume is not). A
  failed fetch (404, network) is not a fallback case and raises as usual.
- Not worth it elsewhere: RV needs all 25 members every release, HymecNG is one
  gzip chunk, RADOLAN files are a single small HDF5 (RW ~30 KB).

## Rain events

The `Rain events` sensor (`sensor.<device>_rain_events`, key
`radvor_rv_rain_events`) publishes the tracker's view (schema 1) as its
attributes, a contract with blueprints: field names and semantics in the
README section "Rain events". `radar/rain_events.py` holds the logic;
`RainEventsTracker` (`rain_events_tracker.py`) its life in HA (store, fill,
save policy, warnings); `RadvorRV` only hands it each adopted release in
`_async_on_new_release` and lends it an analysis fetch and a publish
callback; `RainEventsSensor` in sensor.py is the entity.

- **Opt-in.** The `rain_events` option (Advanced, default off) gates all of it:
  `RadvorRV.__init__` builds a tracker only when `options.rain_events` is on, and
  without one there is nothing to track, so an entry that does not use it makes no fill
  requests and writes nothing. Turning it off removes the entity from the
  registry (rather than leaving "no longer provided") and deletes the store,
  so turning it on again starts clean.
- **Own entity** (ADR 0006: not an attribute of `Precipitation expected`, as
  in pre-releases). The state is
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
  go down (ADR 0006). A multi-day event is a few KB of store.
- **Unknown steps bridge, bounded.** An unknown step never splits a run;
  for *ending* an event it counts as dry only once it has left the window (it
  can no longer be filled), which then ends the event as `end_clipped`. More
  than `MAX_UNKNOWN_BRIDGE` (36 steps, 3 h) unknown in a row count as dry, so
  a restart mid-storm keeps the event and a multi-day outage does not glue new
  rain onto an old event.
- **Ended events** move to `last_ended` and are final; their span is kept in
  `ended_spans` while it is in view, so their rain is not picked up again.
- **Fill before matching.** `RainEventsTracker._async_fill_missed` fetches each unknown
  measured step in the window (analysis only, by range), newest first,
  sequentially, within `RAIN_FILL_BUDGET`; the first failure ends the round,
  with one warning per run of failures (running out of budget is not one).
  A release without data for the cell is recorded as such and not refetched.
  The order is load-bearing: updating first and recomputing after the fill
  can swap event ids and lose `forecast_at_onset` when it rained during a
  downtime. Since setup waits for RV's first refresh, a release with steps
  to fill hands fill + update + publish to an entry background task
  (`_async_fill_and_track`), and the sensor keeps the view it showed before
  (none right after a restart). Later releases queue behind a running round,
  so the tracker always sees releases in order.
- **Persistence.** One `Store` per entry (`rain_events_store()`). Written
  `RAIN_SAVE_DELAY` after a release while something is at stake (an event, a
  wet or unknown step, a new `last_ended`); otherwise the delayed save is
  pushed back by every release and happens at shutdown, so a dry day costs no
  writes. Unload writes it at once (the tracker's own `entry.async_on_unload`;
  an options reload must read it back),
  `async_remove_entry` deletes it. A store that cannot be loaded (damaged, or
  another version's) or whose records `RainEventsState.from_dict` rejects
  (every field `update()` reads is checked) is discarded once with a warning:
  that costs the event ids and up to an hour of history, where keeping it
  would fail every release. The views are stored too, and must be: an
  `unseen` event is republished from its last view, and the stored view
  answers the same release after a restart without processing it twice.
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
saving, so every key stays flat in `entry.options` and no migration is
needed. A new option gets its key and default in `DEFAULT_OPTIONS` and a field
of the same name on `DwdOptions`, which is built from that table (a missing
field fails the first `from_options`); the form and every consumer take the
default from there. `DwdOptions` is a snapshot, which is enough because
saving the options reloads the entry. Translations live under
`options.step.init.sections.advanced_options`. HA 2026.10 installs `probatio`
as `voluptuous` at import time, which is why `vol.Schema` inside `section`
serializes; a script importing `voluptuous` before `homeassistant` sees the
real one and cannot serialize the form.

## HymecNG product specifics

- **URL**: `https://opendata.dwd.de/weather/radar/composite/hymecng/composite_HymecNG_YYYYMMDD_HHMM_000-hd5`
- **Archive**: none — one plain `.hd5` file per 5-minute release (single `_000` grid)
- **Format**: ODIM_H5 H5rad 2.3, `object=COMP`, `quantity=CLASS`, `gain=1`, `offset=0`
- **Grid**: DE1200, described in /where exactly as RS/RV describe it
- **Encoding**: `uint8` class index 0–10; `nodata=255` (outside coverage → sensor `unknown`), `undetect=254` (scanned, no echo → `no_precipitation`)
- **Classes** (`PRECIP_TYPE_BY_INDEX` in `const.py`): 0 no_precipitation, 1 not_classified, 2 drizzle, 3 rain, 4 freezing_drizzle, 5 freezing_rain, 6 sleet, 7 snow, 8 graupel, 9 hail, 10 large_hail
- **Sensor**: one `SensorDeviceClass.ENUM` "Precipitation type now" sensor (key `hymecng_precipitation_type`); state labels are translated via the `precipitation_type_now` entity translation key
