# Architecture decision records

Why the integration is the way it is, and what it was before. CLAUDE.md states
the rules that follow from these; a record keeps the reasoning, the numbers it
rested on, and the alternatives that were turned down, so a later change can
weigh them rather than rediscover them.

A record is not edited once accepted, except to mark it superseded by a newer
one. Releases are named by their version (`2026.11.0`).

| # | Decision | Since |
|---|----------|-------|
| [0001](0001-entity-names-state-their-window.md) | Entity names state their window; a released id is never reused | 2026.11.0 |
| [0002](0002-rw-reads-the-clock-hour.md) | RW reads the run ending on the hour, not HH:50 | 2026.11.0 |
| [0003](0003-rw-10-minute-runs-only-for-the-dry-streak.md) | RW's 10-minute runs feed the dry streak, nothing else | 2026.11.0 |
| [0004](0004-radolan-hdf5-edition.md) | RW and SF are read in their HDF5 edition | 2026.10.1 |
| [0005](0005-running-totals.md) | Running totals are keyed on the release, and RW backs the main one | 2026.11.0 |
| [0006](0006-rain-events-opt-in-entity.md) | Rain events are their own opt-in entity, recomputed every release | 2026.11.0 |
| [0007](0007-staleness-deadline-on-the-overdue-release.md) | Staleness is a deadline on the overdue release | 2026.9.0 |
| [0008](0008-grid-lookup-floors-from-the-outer-corner.md) | The grid lookup floors from the outer corner | 2026.10.0 |
| [0009](0009-full-rolling-series-from-rv.md) | The full rolling-hour series is built from RV, not RS | 2026.11.0 |
| [0010](0010-cells-on-the-grid-each-file-describes.md) | Each product reads its cell on the grid its file describes | 2026.11.0 |
| [0011](0011-dry-streak-gaps-checked-against-rw.md) | Gaps in the dry-streak source are checked against RW's hours | 2026.11.0 |
| [0012](0012-rain-warnings-as-subentries.md) | Rain warnings are subentries that filter the rain-events view | 2026.11.0 |
