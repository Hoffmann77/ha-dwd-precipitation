# Interpolation evaluation: design

Status: **design agreed; implementation in progress** (see "Implementation
order" at the end).

## Question

The integration reports the value of the radar cell that contains the user's
location ("nearest cell"). Would a sub-cell method — bilinear interpolation
between the surrounding cell centres, or a neighbourhood mean/max — give a
value closer to what actually falls at the location?

The evaluation answers this empirically: it logs RV nowcast values around
~150 DWD rain gauges for months, pairs them with the gauges' measurements,
and scores every method per lead time. It is an offline research tool; nothing
in it ships with the integration.

## Scope decisions

| Topic | Decision | Why |
|---|---|---|
| Product | **RV only** | RS is summed RV (verified cell for cell), so RS results follow from RV. RADOLAN RW/SF are gauge-adjusted against the same gauges and cannot be verified against them fairly. |
| Window | **5x5 cells** around the station's cell | Bilinear needs the inner 2x2 of the 3x3; the 5x5 adds a neighbourhood radius of 2 cells for the longer leads. Cannot be added retroactively. |
| Leads | **All 25** (0, 5, ..., 120 min) | Errors are reported per lead. |
| Cadence | **Every release** (5 min) | |
| Stations | **~150, selected automatically**, stratified over region and altitude, fixed seed; list committed as `stations.csv` | Representative and reproducible. |
| Ground truth | **DWD CDC 1-minute precipitation**, summed to the RV step window | Matches RV's 5-minute steps exactly; the 10-minute series would force pairs of steps. |
| Gauge source | `recent/` (daily, rolling ~500 days) | Gauge data never expires within the evaluation window, so it is fetched after the fact rather than logged live. |
| Gauge QC | **`QN = 3` only** (automatic control and correction) | `recent/` has not had DWD's manual QC; `historical/` (yearly) has. |
| Re-evaluation | **None.** Results stay as first computed from `recent/`; each result records that. | |
| Winter | **December-February reported as a separate block** | Weighing gauges under-catch snow. A split by sub-zero hours would need a second dataset (CDC air temperature) and is deferred. |
| Thresholds | **0, 0.6, 1.2, 6 mm/h** (= >0, 0.05, 0.1, 0.5 mm per 5 min) | See "Rain / no-rain scores". |
| Alerts, backups | **None** | A stalled logger shows up as reduced coverage in the next monthly result. A lost database loses only the raw data behind already-committed results. |

## Data sources

### RV nowcast

- `https://opendata.dwd.de/weather/radar/composite/rv/composite_rv_YYYYMMDD_HHMM.tar`
- One tar per 5-minute release, 25 ODIM_H5 members (`_000` to `_120`), each a
  5-minute accumulation (`ACRR`, mm). Lead L covers T+L-5 to T+L.
- **Kept on OpenData for ~48 h** (576 files per product observed on
  2026-10-09). Anything not logged within that window is lost for good.
- 0.9 to 4.9 MB per tar, 2.25 MB on average (all 576 files on OpenData on
  2026-11-09).

### Gauges

- `https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/1_minute/precipitation/recent/`
- One zip per station (`1minutenwerte_nieder_<id>_akt.zip`); 1,370 stations
  had current 1-minute data on 2026-10-09.
- Columns: `STATIONS_ID;MESS_DATUM;QN;RS_01;RS_IND_01`, UTC, mm in 0.01 steps.
- Weighing gauges (e.g. OTT Pluvio, rain[e]H3), opening 1 m above ground —
  in-situ measurements, not radar or satellite derived.
- Positions from the station description / `Metadaten_Geographie_*` (4
  decimals, ~10 m). **Not** from the instrument metadata, which has only 2
  decimals (~1 km). Stations move now and then; the selection takes only
  stations at their current position since 2025, so one position per station
  holds for the whole evaluation.
- To verify during implementation: whether `MESS_DATUM` labels the start or
  the end of each minute. An off-by-one here shifts every pairing by a minute.

## Pipeline

All on one server (Ubuntu 24, J4105), as **one Docker Compose service that
is started once and runs on its own**. There is no command-line interface:
the container runs a single long-lived Python process that schedules its
three jobs internally.

| Job | When (UTC) | What |
|---|---|---|
| Radar | every 5 min | List RV on OpenData; for every release of the last 48 h not yet in the database, download the whole tar, read each of the 25 members once, cut the 5x5 window around each station out of it, write. |
| Gauges | daily, after 03:30 | Refresh the last few days of 1-minute data from `recent/` (updated ~02:00), sum to 5-minute windows, upsert. |
| Evaluate | from the 3rd of each month, 04:00 | For every completed month without a result, score it, write `results/YYYY-MM.json` + `.md`, commit and push to the `eval-results` branch. |

**Every job is "catch up", not "run at time X".** Each one works out from the
database what is missing — unlogged releases, stale gauge days, months
without a result — and does exactly that. So a restart, a reboot or a few
hours of downtime need no special handling: on start-up the process runs all
three checks once, then follows the schedule. Only an outage longer than
~48 h loses data (the RV releases that expired meanwhile).

A tar is written to a temp file and only marked as logged once every member
has been read, so an interrupted download never looks like data. A failing
job is logged and retried on its next turn; it never stops the process.

### Reading the grid

Each member is read **whole, once** (`read_odim_composite` from
`radar/odim.py`, the reader the test tiers use as their oracle), and the
windows of all stations are cut out of that array. Reading 150 small slices
instead would make libhdf5 inflate the grid's single compressed chunk once
per slice (it is larger than h5py's default chunk cache), i.e. 150 times per
member instead of once.

The station's cell is found **on the grid the file itself describes**
(`read_odim_grid`, `Grid.cell`), as the integration does (ADR 0010), not on a
copy of DWD's grid. Each distinct grid is stored once (`grids`), with every
station's cell and its position inside the cell on it (`station_cells`), and
each release points at the grid it was read on. If DWD ever moves or resizes
the grid, old and new releases both stay correct.

## Database (SQLite, WAL mode)

```
stations(station_id PK, name, lat, lon, altitude, state)

grids(grid_id PK, description UNIQUE)   -- the file's /where, as JSON

station_cells(grid_id, station_id,
              row, col,             -- the cell holding the station
              frac_x, frac_y,       -- position inside it: 0 = west/south edge
              PRIMARY KEY (grid_id, station_id))

releases(release PK,                -- nominal release time, UTC
         grid_id, logged_at,
         n_members)                 -- n_members < 25 means a damaged release

radar(release, lead, station_id,
      c00 .. c44,                   -- 5x5 window, row-major, centre = c22
      PRIMARY KEY (release, lead, station_id))

gauge(station_id, window_end,       -- 5-minute window ending at window_end
      mm, qn, n_minutes,            -- n_minutes < 5 means incomplete
      PRIMARY KEY (station_id, window_end))
```

- Cell values are stored as **integer thousandths of a mm** (the ODIM
  resolution), so the scaled value round-trips exactly; nodata is `NULL`.
  SQLite stores 0 and 1 in zero payload bytes, so mostly-dry windows are cheap.
- **Sparse:** a radar row whose 25 cells are all 0 is not stored. For a
  release present in `releases`, a missing row *means* an all-dry window;
  for a release absent from `releases`, it means "not logged". Nothing is
  lost — misses (dry forecast, wet gauge) are reconstructed at evaluation.
- Pairing: radar row (release T, lead L) is compared with the gauge window
  ending at T+L.
- A station whose 5x5 window does not fit on the grid (too close to its edge)
  is left out of that grid's `station_cells` and so never logged.

Connection settings, applied on every open:

- `journal_mode=WAL`, so the evaluation can read while the radar job writes;
  `synchronous=NORMAL` (safe with WAL, and much faster); a `busy_timeout`, so
  concurrent access waits instead of failing.
- **One transaction per release:** all its rows and its `releases` entry are
  written together, so a release is stored completely or not at all.
- `STRICT` tables, so a value of the wrong type is refused rather than stored.
- `INSERT ... ON CONFLICT DO UPDATE` for gauge data, which `recent/` revises.
- The schema version lives in `PRAGMA user_version`; the service creates or
  migrates the schema itself on start-up.

Python's built-in `sqlite3`, plain SQL, no ORM.

Estimated size (not yet measured): ~3-5 GB per year with the sparse rule; the
gauge table is negligible. Download traffic is the larger cost: 288 tars a
day at ~2.25 MB is ~20 GB per month, independent of the window size.

## Evaluation

### Methods

| Method | Value |
|---|---|
| `nearest` | centre cell `c22` — what the integration reports today |
| `bilinear` | weighted from the 4 cell centres around the station, using `frac_x`/`frac_y` |
| `mean3`, `max3` | mean / max of the inner 3x3 |
| `mean5`, `max5` | mean / max of the full 5x5 |

`nodata` cells are dropped and the weights of the remaining ones renormalised;
a window whose centre is `nodata` is skipped and counted.

### Per method and per lead (all 25)

- **Amounts:** n, MAE, RMSE, bias (wet pairs: forecast or gauge > 0).
- **Rain / no-rain scores** at each threshold: hits, misses, false alarms,
  correct negatives, hit rate (POD), false-alarm ratio (FAR), critical success
  index (CSI).
- **Head-to-head against `nearest`:** share of pairs where the method's
  absolute error is smaller, larger, or equal; mean difference in absolute
  error with a 95% confidence interval from a **day-block bootstrap** (pairs
  within a day are correlated, so resampling single pairs would overstate the
  confidence).

### Rain / no-rain thresholds

The integration's `Precipitation expected` / start / end sensors decide
rain/no-rain per 5-minute step with `value > threshold`, the threshold being
the user's `precipitation_threshold` option in mm/h (default 0). Scoring at
exactly that default would charge the forecast for the gauge's resolution
(0.01 mm, practically ~0.05-0.1 mm), so several thresholds are reported:

| mm/h | mm per 5 min | Shows |
|---|---|---|
| 0 | > 0 | What users get with the default option |
| 0.6 | 0.05 | Around the gauge's reliable detection limit |
| 1.2 | 0.1 | Light, clearly measurable rain |
| 6 | 0.5 | Moderate to heavy rain |

This also shows whether 0 is a good *default* for the option.

### Also reported

- Neighbour statistics: distribution of |neighbour - centre| per ring (3x3,
  5x5), per lead — how much sub-cell methods can move the value at all.
- Coverage: releases expected / logged / damaged, gauge windows used /
  dropped (QN, incomplete), dry rows inferred.
- Winter (Dec-Feb) months carry a `season: "winter"` flag so they can be read
  separately.

### Result files

On the orphan branch `eval-results`, one pair per month:

- `results/YYYY-MM.json` — every number above, plus provenance: code commit,
  `stations.csv` hash, gauge source (`recent`) and QN filter, thresholds.
- `results/YYYY-MM.md` — per-lead summary tables for reading on GitHub.

A few tens of KB per month. Pushed with a deploy key that has write access to
this repository only; nothing is pushed to `main`.

## Deployment

- **`deploy/precip-eval/compose.yaml`** builds the image from the repository
  checkout and runs it with `restart: unless-stopped`. Start it once with
  `docker compose up -d`; update with `git pull` and the same command.
- Image: official **`python:3.14-slim`**, **`uv`** (copied from the
  `ghcr.io/astral-sh/uv` image, pinned), `git` and `openssh-client` for the
  push. No cron or supercronic — scheduling is in the Python process.
- Dependencies from a new `precip-eval` group in `pyproject.toml` (`numpy`,
  `h5py`, `requests`), resolved through the existing `uv.lock`. Everything
  else is standard library.
- Integration code is reused directly (`from radar.odim import ...` with
  `custom_components/dwd_precipitation` on `PYTHONPATH`, as the parser tests
  do), so Home Assistant is never imported.
- Configuration through environment variables, all with defaults, set in an
  optional `.env` file next to `compose.yaml`:

  | Variable | Default | What |
  |---|---|---|
  | `PRECIP_EVAL_DATA` | `./data` | Host directory for the SQLite database |
  | `PRECIP_EVAL_DEPLOY_KEY` | `./deploy_key` | Host path of the deploy key's private half |
  | `PRECIP_EVAL_UID` / `PRECIP_EVAL_GID` | `1000` | User the container runs as; must be able to write the data directory |

- Volumes: the data directory -> `/data`; the deploy key, read-only.
- **The data directory must be on a local disk**, not a network share
  (NFS/SMB): SQLite's WAL mode relies on file locking and shared memory that
  network file systems do not provide reliably.
- The container runs as a non-root user (the UID above).
- `TZ=UTC`; logs go to stdout (`docker compose logs`). A Docker healthcheck
  reads a heartbeat the scheduler writes each loop, so a hung process shows
  as `unhealthy` and is visible in `docker ps`.
- The code commit is baked in at build time (build arg) for the provenance
  field.

### One-time setup

1. Clone the repository on the server.
2. Create an SSH key pair; add the public key to the GitHub repository as a
   **deploy key with write access**; put the private key next to the compose
   file (path set in `compose.yaml`).
3. `docker compose up -d` in `deploy/precip-eval/`.

The station list is generated during development and committed, so nothing
has to be run by hand on the server.

## Repository layout

```
scripts/precip_eval/                 package: __main__ (the scheduler loop,
                                     the container's only entry point), db,
                                     radar_job, windows, scheduler, stations;
                                     later gauges, metrics, report, publish
scripts/precip_eval/stations.csv     the committed station list
scripts/precip_eval/select_stations.py
                                     development tool that generates it
deploy/precip-eval/                  Dockerfile, compose.yaml
tests/precip_eval/                   windows, sparse rule, database, radar
                                     job against the RV fixture; run with the
                                     parser tier in CI
```

The integration's code is not changed: the evaluation only imports
`radar.odim` and `radar.urls`.

## Implementation order

1. Windows on the file's own grid + tests against the RV fixture.
2. Station selection -> commit `stations.csv`.
3. Scheduler loop + radar job with gap-filling; tested against live OpenData.
4. Dockerfile + compose; deploy, logging starts (the 48 h window makes this
   the urgent part). Gauges and evaluate are no-ops until implemented.
5. Gauge job.
6. Evaluate job + report + push; first result once a full month is logged.
