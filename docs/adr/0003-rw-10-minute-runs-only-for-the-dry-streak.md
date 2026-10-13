# 0003 — RW's 10-minute runs feed the dry streak, nothing else

Status: accepted (2026.10.1)

## Context

RW's sub-hourly runs (see [0002](0002-rw-reads-the-clock-hour.md)) are as
strongly gauge-adjusted as the hourly one, and a new one appears every 10
minutes. `Timespan without precipitation` resets when a past-hour total
reaches a threshold; counted from RW's hourly run, the reset can show up to an
hour late.

## Decision

- `RadolanRW10` (`rw_10min`) reads every run, and the dry streak counts it
  when its source is `rw`. It is built only then (`is_needed(options)`), so an
  entry that does not use it makes no extra requests.
- The dry streak's default source is `rw`, but existing installs keep `rs`:
  the config entry went to version 1.2, and `async_migrate_entry` writes
  `dry_streak_source: "rs"` into every 1.1 entry that lacks it.
- When built, `rw_10min`'s :00 run is the file `rw` fetches too; both go
  through the entry's `DownloadCache`, so it is downloaded once.

## Alternatives turned down

- **A sensor for the sliding RW hour.** As a "last 60 min" it would be 28-38
  min behind, where RS is 4-9 min, and gauge accuracy is what `Precipitation
  previous hour` is for. A pre-release had a `rw_last_hour_mode` option for
  it; it never shipped, and a stored value is ignored.
- **Totals from the 10-minute runs.** Consecutive runs overlap by 50 minutes,
  so summing them counts each hour six times. The totals and their
  missed-release walk stay on `rw`'s hourly grid, as does the dry streak's
  startup downtime correction.
- **Falling back to the other source** when the selected one fails: the
  entity follows its coordinator's availability instead.
