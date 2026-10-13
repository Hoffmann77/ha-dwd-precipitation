# 0002 — RW reads the run ending on the hour, not HH:50

Status: accepted (2026.10.1)

## Context

DWD runs RW every 10 minutes, each run the hour ending at that :x0. Up to
2026.10.0 the integration read the HH:50 run. Nothing recorded why; it is
RADOLAN's traditional hour, and SF is still only published at :50 (OpenData
has no other SF minute).

Only a clock hour can be called "previous hour" (see
[0001](0001-entity-names-state-their-window.md)) and line up with HA's hourly
statistics. The question was whether the :00 run is as good as the :50 one.

`scripts/compare_rw_runs.py` compares every RW run on OpenData (48 h) with
radar-only RS `_000` for the same hour, cell for cell. If the sub-hourly runs
used fewer gauges, they would sit closer to RS. They do not: over 285 wet runs
(2026-10-10..12) every run minute departs from RS alike (mean |RW-RS|
0.53-0.58 mm, 58-62 % relative, 76-78 % of wet cells adjusted). Every run
minute is published at ~25.7 min (288 runs, 2026-10-13).

## Decision

`rw` reads the run ending on the hour. SF stays at :50, so `rw` and `sf`
windows are now 10 minutes apart.

A total stored by 2026.10.0 has a `last_release` at :50, off the new grid.
Restoring it maps it once with `counted_on_grid()` onto the :00 release before
the first window that starts after it, so counting resumes there: the 10
minutes in between are left out once, rather than 50 counted twice
(`counted_until` reads 10 minutes ahead until the next release).

## Consequences

Rerun `scripts/compare_rw_runs.py` before relying on the quality comparison
for anything new; DWD may change how the runs are adjusted.
