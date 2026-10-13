# 0001 — Entity names state their window; a released id is never reused

Status: accepted (2026.10.1)

## Context

HA derives an entity id by slugifying the English name, so a name is also an
id. Up to 2026.10.0 the names were:

| key | 2026.10.0 name | id |
|-----|----------------|----|
| `radvor_rs_000` | Precipitation now | `precipitation_now` |
| `radvor_rs_060` | Precipitation next 1h | `precipitation_next_1h` |
| `radvor_rs_120` | Precipitation next 1–2h | `precipitation_next_1_2h` |
| `radvor_peak_1h_120` | Peak hourly precipitation next 2h | `peak_hourly_precipitation_next_2h` |
| `radvor_rv_max_intensity_060` | Peak intensity next 1h | `peak_intensity_next_1h` |
| `radvor_rv_max_intensity_120` | Peak intensity next 1–2h | `peak_intensity_next_1_2h` |
| `hymecng_precipitation_type` | Precipitation type | `precipitation_type` |
| `radolan_rw` | Precipitation last 1h | `precipitation_last_1h` |
| `radolan_rw_total` | Precipitation total (hourly) | `precipitation_total_hourly` |
| `radolan_sf_yesterday_total` | Precipitation total (daily) | `precipitation_total_daily` |

`tests/entity_ids.py` is the complete record by key, including what kept its
id and what is new since.

Three things were wrong with them:

- `Precipitation now` was RS `_000`, mm over the *past hour*, named for its
  role; it read like a rate.
- `next 1–2h` needed a note that it is the second hour, not the coming two.
- RS `_000` and RW both covered "the last hour" under unrelated names, and
  nothing in either said which hour.

## Decision

A name states a window only when the window is part of the value, in three
forms: `last <N>` (a measured window ending at the latest release), `next <N>`
(a forecast window) and the calendar periods `previous hour` / `yesterday`.
The RADVOR nowcast states windows in minutes, matching its 5-minute steps and
the `minutes_until` attributes (`next 60–120 min`); RADOLAN keeps hours and
days (`last 24h` keeps its released spelling, since a space would change its
slug for nothing). `now` means the latest 5-minute analysis. Everything else
carries no window.

So RS `_000` is `Precipitation last 60 min`, RW (a clock hour, see
[0002](0002-rw-reads-the-clock-hour.md)) is `Precipitation previous hour`, and
no two names share a window, so none needs a source qualifier.

Keys did not change: existing installs keep their ids and only see new names;
new installs get the new ids. No new id is one a released version gave another
entity, so an id means one thing on every install, and HA's "recreate entity
ids" on an old install cannot collide.

## Alternatives turned down

- **RS as `precipitation_last_1h`.** On an old install RW still holds that id,
  so recreating ids would put RS on `precipitation_last_1h_2`.
- **Source suffixes**, `(radar)` / `(gauge-adjusted)`. Carried briefly on the
  release branch after 2026.10.0, never shipped: once no two names share a
  window, the source is something the README explains, not a name.
- **Renaming keys** to match. A key is the unique-id suffix; changing it
  orphans the user's entity and its history.

## Consequences

The README lists the old ids for installs from 2026.10.0; a test checks it
names every renamed one (`tests/parser/test_docs.py`). The setup test checks a
new install's ids, and that none is an old id of another key.
