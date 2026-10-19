---
title: Architecture
description: The modules of DWD Precipitation, how data flows from DWD Open Data to an entity, and how failures are handled.
---

The integration fetches DWD radar composites, finds the grid cell that
contains the configured location, and exposes its values as sensors. This
page is the overview; `CLAUDE.md` in the repository states the detailed
rules, and the [ADRs](/development/adr) the reasoning behind them.

## Modules

| Module | Role |
|--------|------|
| `__init__.py` | Entry point. Builds one coordinator per product, refreshes them concurrently, and has each register its release schedule |
| `coordinator.py` | `BaseProductUpdateCoordinator`, the per-product `DataUpdateCoordinator`: release timing, the fetch/stale/retry lifecycle, the backoff |
| `products.py` | One coordinator subclass per DWD product: URL, fetch, parse, grid lookup |
| `entity.py` | `DwdCoordinatorEntity`, the base of every entity: unique id, device, availability, the description mechanism |
| `sensor.py`, `binary_sensor.py` | The entity descriptions and the special sensors (totals, dry streak, rain events) |
| `dry_streak.py`, `precipitation_total.py` | Pure logic of the dry streak and the running totals |
| `rain_events_tracker.py` | The rain events of one entry in Home Assistant: store, background fill, save policy |
| `release_grid.py` | `ReleaseGrid`: a product's release times on its own clock |
| `config_flow.py`, `options.py` | Setup and options form; `DwdOptions`, the options as one typed snapshot |
| `utils.py` | The HTTP helper, a per-entry download cache, a failure latch |
| `radar/` | The Home-Assistant-free core: ODIM_H5 readers, the grid, range reads of tar archives, nowcast and rain-event logic |

`radar/` and `release_grid.py` import nothing from Home Assistant, so the
parser and reference test tiers can test them without it.

## Data flow

There is no shared poll loop: every product is its own coordinator, on its
own schedule.

1. A time-change tracker fires at the product's release time (its nominal
   time plus `RELEASE_DELAY` plus a per-install jitter) and asks the
   coordinator to refresh.
2. The coordinator computes the latest release that should be on Open Data.
   If it already has that one, it returns the cached data untouched.
3. `_fetch_and_parse(release)` downloads the file on the event loop, then
   decodes it in the executor: decoding a 1.3-million-cell grid takes time,
   and many users run Home Assistant on a Raspberry Pi. The parser reads the
   cell holding the location on the grid the file itself describes.
4. The result is wrapped in a `CoordinatorData`: `data` and `metadata` dicts
   keyed by the same sub-keys (`KEY_*` in `const.py`).
5. Each entity reads `data[sub_key]` and `metadata[sub_key]` of its
   product's coordinator.

`_fetch_and_parse` has no side effects, so any past release can be fetched
without moving the coordinator; the totals' backfill and the dry streak's gap
check rely on it. Whatever adopting a release should also do goes into
`_async_on_new_release`, which never raises.

## Release timing

Every release computation goes through the coordinator's `ReleaseGrid`, on
the product's own clock: UTC for most products, Home Assistant's local zone
for the daily `sf_2350`, whose releases are 23 or 25 hours apart on
daylight-saving changeover days.

- `RELEASE_INTERVAL` and `RELEASE_OFFSET` describe the grid of nominal times.
- `RELEASE_DELAY` is how long after its nominal time a file is on Open Data.
  A scheduled workflow checks it against what DWD actually does.
- Each install adds a fixed jitter of up to 30 seconds, derived from the
  entry id (not drawn at random), so installs do not all fetch in the same
  second, and an install keeps its schedule across restarts.

[ADR 0007](/development/adr/0007-staleness-deadline-on-the-overdue-release)
explains why the schedule is registered on the product's own clock.

## Failure handling

Fetches fail routinely: DWD publishing a few minutes late is the normal case.

- **Retry with backoff.** The first failure arms a retry after 60 seconds,
  each further one adds 10 seconds, capped at 5 minutes (15 for `sf_2350`).
  Only a success resets it. Each retry gets ±15 % jitter, so installs that
  failed together do not retry in lockstep.
- **Staleness is a deadline on the overdue release.** A value stops being
  reported `OVERDUE_GRACE` (6 minutes; 30 for `sf_2350`) after the release
  that should have replaced it was due. `data_is_reportable` is the only
  place that decision is made. See
  [ADR 0007](/development/adr/0007-staleness-deadline-on-the-overdue-release).
- **One failing product does not take the entry down.** Setup only fails if
  every product fails.
- **A cell without data is logged on the change.** When a radar drops out of
  DWD's composite, every fetch still succeeds but the cell is empty; the
  coordinator logs one warning when data goes (naming the missing radars) and
  one message when it is back.

`_describe_fetch_error()` writes the message a user sees, once per run of
failures. It names what DWD did, says whether the configuration is involved,
and states that retries continue, in plain ASCII.

## Grid lookup

Every product reads the cell holding the location on the grid its own file
describes in its ODIM `/where` group
([ADR 0010](/development/adr/0010-cells-on-the-grid-each-file-describes)).
`radar/grid.py` builds the grid; only north-polar stereographic on an
ellipsoid is computed, and anything else that could move a cell is refused
rather than read at the wrong place.

The lookup projects the location and floors its offset from the grid's outer
lower-left corner: the corner references are pixel edges, not centres
([ADR 0008](/development/adr/0008-grid-lookup-floors-from-the-outer-corner)).

## Range reads

RS and RV archives are plain tar files of 25 members. RS needs only three of
them, so `radar/tar_range.py` reads those by HTTP range requests: a head
request finds the first member and the file size, and the rest are located by
interpolating between known headers. Anything unexpected falls back to the
whole archive, with one warning per run of fallbacks.

## The special sensors

- **Running totals** are keyed on the release, never on the value changing,
  and backfill missed releases from a stored pending list
  ([ADR 0005](/development/adr/0005-running-totals)).
- **Timespan without precipitation** binds to the coordinator of the chosen
  source; RW is counted from its 10-minute runs
  ([ADR 0003](/development/adr/0003-rw-10-minute-runs-only-for-the-dry-streak)),
  and gaps are checked against RW's hours
  ([ADR 0011](/development/adr/0011-dry-streak-gaps-checked-against-rw)).
- **Rain events** are recomputed from stored measured steps every release
  rather than accumulated
  ([ADR 0006](/development/adr/0006-rain-events-opt-in-entity)).

## Entity naming

Every entity name comes from a `translation_key` and
`translations/en.json`; Home Assistant derives the entity id from the English
name. A released id is never reused for another value, and entity keys (the
unique-id suffix) never change once released
([ADR 0001](/development/adr/0001-entity-names-state-their-window)).
