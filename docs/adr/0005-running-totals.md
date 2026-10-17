# 0005 — Running totals are keyed on the release, and RW backs the main one

Status: accepted (2026.11.0)

## Context

2026.10.0 shipped two `TOTAL_INCREASING` sensors, `Precipitation total
(hourly)` from RW and `Precipitation total (daily)` from `sf_2350`. HA's
statistics see each hour one hour late (11:00-12:00 is added at ~12:28), so
RW's total only lets the last hour of a day spill into the next, while every
day's rain in the daily one lands in the *next* day's statistics.

## Decision

- A total is keyed on the release timestamp, never on the value changing: two
  equally wet hours are two releases, and a release seen twice is counted once.
- RW backs `Precipitation total`, the one to use (renamed from `(hourly)`, so
  new installs get `precipitation_total`; see
  [0001](0001-entity-names-state-their-window.md)).
- `Precipitation total daily` keeps its id but is disabled by default
  (`entity_registry_enabled_default=False`). Removing it would orphan users'
  entities. The default only applies when HA first registers an entity, so
  installs that had it keep it enabled; enabling it reloads the entry and it
  starts from 0, like any new total.
- Missed releases go on a `pending` list stored with the total and are
  removed only once added, so neither a restart nor a failed fetch loses one.

## Alternatives turned down

- **One total with a source option.** Switching the source would make a
  `TOTAL_INCREASING` sensor jump.
- **Removing the daily total.** See above; it costs users their entity.
