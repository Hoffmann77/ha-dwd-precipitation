# 0007 — Staleness is a deadline on the overdue release

:::note[Noch nicht übersetzt]

Diese Seite ist noch nicht ins Deutsche übersetzt; bis dahin steht hier die englische Fassung.

:::

Status: accepted (2026.9.0)

## Context

A cached value has to stop being reported at some point while DWD fails to
publish. The first rule measured that tolerance from the *cached* release,
which forces it to be expressed in release intervals, so it expires exactly
when some later fetch is due: the value was written off at the very instant of
the attempt that might have restored it, and which happened first came down to
event-loop latency. That is what made a routinely late file blank the sensors
and log an ERROR every single time.

Separately, `sf_2350` (23:50 local time) was registered with
`async_track_utc_time_change` although its grid is on the local clock. It was
fetched an offset's worth of hours late every day — in summer 1.5 h after its
own staleness deadline had passed.

## Decision

- The deadline starts when the release *after* the cached one should have
  been on OpenData, and runs for the product's `OVERDUE_GRACE`. It answers
  "how long do we go on trying for a release that is already due".
- It only collides with the fetch grid if `OVERDUE_GRACE` is a whole multiple
  of `RELEASE_INTERVAL`; a test enforces that it is not, per product.
- `OVERDUE_GRACE` does not scale with the interval: the hourly and daily
  products give up on a missed release as promptly as the 5-minute ones,
  because the question is how long DWD is given to publish.
- A product registers its own release schedule (`async_track_releases()`), so
  the grid and the clock it is read in are one decision: the entry point had
  only half of it.
