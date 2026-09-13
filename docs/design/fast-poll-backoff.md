# Fast-poll retry: per-product backoff instead of give-up

Status: agreed design, **not implemented yet**. This is a handoff document for
whoever picks up the implementation.

## Problem

`BaseProductUpdateCoordinator` (`coordinator.py`) is event-driven
(`update_interval=None`): it only re-fetches at wall-clock times computed from
each product's `RELEASE_INTERVAL`/`RELEASE_DELAY`/`RELEASE_OFFSET`
(`track_time_change_args`, wired up in `__init__.py`).

On a fetch failure, `_async_update_data()` currently does this
(`coordinator.py:271-283`):

```python
try:
    data, metadata = await self._fetch_and_parse(latest_release)
except Exception as err:
    unavailable_when_stale = self.config_entry.options.get(
        CONF_UNAVAILABLE_WHEN_STALE, True
    )
    if self.data is None or (unavailable_when_stale and self._data_is_stale(now)):
        self._stop_fast_polling()
        raise UpdateFailed(_describe_fetch_error(err, latest_release)) from err

    # Data is still fresh enough — retry silently
    self._start_fast_polling()
    return self.data
```

`_start_fast_polling()` / `_stop_fast_polling()` (`coordinator.py:221-240`)
today wrap a fixed 60-second `async_track_time_interval` timer.

The bug: once cached data crosses into "stale" (`_data_is_stale()`,
`coordinator.py:144-152`), fast-poll is cancelled outright. Recovery is then
bottlenecked entirely by the product's own `RELEASE_INTERVAL` — fine for the
5-minute products, but for `RadolanRW`/`RadolanSF` (hourly) or
`RadolanSFLastYesterday` (daily) a single mistimed request (e.g. the file
consistently lands a few seconds after the scheduled request) can leave the
entity `unavailable` for up to a full release cycle, repeatedly, with no
faster path back.

This was found by inspecting a third-party fork
(`evgparen/ha-dwd-precipitation`, branch `reliable-fetch`, commit `ffbc841`)
that "fixes" it by simply calling `_start_fast_polling()` instead of
`_stop_fast_polling()` in the stale branch — i.e. an unconditional 60s retry
forever. That trades the bug for a different problem: during a genuine
multi-hour DWD outage it would hit DWD OpenData every 60 seconds indefinitely
for every product, including the 24h one. We are not adopting that patch
as-is; the design below is the agreed middle ground.

## Agreed design

**Fast-poll never stops once started** (except on success or config-entry
unload) — but its interval backs off over time, scaled per product, instead
of staying fixed at 60s.

- **Start:** 60s.
- **Ramp:** linear, **+10s per consecutive failure**:
  `60, 70, 80, 90, 100, …` seconds.
- **Cap:** a new per-product `ClassVar[timedelta]`, e.g.
  `MAX_FAST_POLL_INTERVAL`, defined alongside the existing
  `RELEASE_INTERVAL` / `RELEASE_DELAY` / `RELEASE_OFFSET` / `STALE_AFTER`
  ClassVars on each `Product` / coordinator subclass. Agreed values for the
  current products:

  | Product | `RELEASE_INTERVAL` | `MAX_FAST_POLL_INTERVAL` |
  |---|---|---|
  | `RadvorRS` | 5 min | 5 min |
  | `RadvorRV` | 5 min | 5 min |
  | `HymecNG` | 5 min | 5 min |
  | `RadvorRQ` | 15 min | 5 min |
  | `RadolanRW` | 1 h | 5 min |
  | `RadolanSF` | 1 h | 5 min |
  | `RadolanSFLastYesterday` | 24 h | 15 min |

- **Reset** the interval back to 60s (and the consecutive-failure counter to
  0) on:
  1. a successful fetch, or
  2. `latest_release` advancing to a new boundary (a newly-due release is
     treated as a fresh problem, not a continuation of the previous one).
- **Availability semantics are unchanged.** `unavailable_when_stale` /
  `_data_is_stale()` / raising `UpdateFailed` still work exactly as they do
  today — that governs when HA shows the entity as unavailable. The backoff
  only governs the retry cadence running underneath; it is orthogonal.

## Implementation notes

- The interval now varies over time, so `_start_fast_polling` /
  `_stop_fast_polling` can no longer wrap a single fixed
  `async_track_time_interval`. Replace with a self-rescheduling loop
  (`async_call_later`, re-armed after each attempt with the next computed
  delay).
- New per-coordinator instance state needed: current fast-poll interval
  (or equivalently, consecutive-failure count, from which the interval is
  derived: `min(60 + 10 * consecutive_failures, MAX_FAST_POLL_INTERVAL)`).
- The stale-failure branch in `_async_update_data()` drops its
  `self._stop_fast_polling()` call; it should instead ensure fast-polling is
  running (it always will be by that point, since it can only be reached
  after at least one prior failure started it — but double check the
  `self.data is None` / very-first-ever-failure path still starts it).
- Reset-on-new-release-boundary needs comparing the freshly computed
  `latest_release` against whatever release the backoff state was last
  computed for — likely just compare against `self.curr_release` or track a
  separate `_fast_poll_release` marker updated each time the interval is
  reset.
- `config_entry.async_on_unload(self._stop_fast_polling)` must still cancel
  cleanly on entry unload/reload — preserve this.
- Update `_describe_fetch_error()`'s HTTP 404 message if needed — it
  currently asserts "this is normal near release time," which is only true
  for the fast, tight part of the ramp; consider whether it should stay
  generic once well into backoff (not required for correctness, just a nice
  wording nit while touching this code).

## Testing

Mirror the structure `tests/integration/test_coordinator_timing.py` already
uses for `_data_is_stale()`. New coverage should include:

- Interval sequence: 60, 70, 80, … up to and pinned at the cap, per product
  (or via a synthetic `MAX_FAST_POLL_INTERVAL`).
- Reset to 60s on success.
- Reset to 60s when `latest_release` advances, even mid-backoff.
- Fast-poll keeps running (never cancelled) through the transition into
  `_data_is_stale() == True` / `UpdateFailed`.
- `_stop_fast_polling()` still called on success and on config-entry unload.

The third-party fork's `tests/integration/test_retry_regression.py` (not in
this repo — see the fork at `evgparen/ha-dwd-precipitation`) is a useful
reference for scenario shapes (late-file recovery, first-failure-at-stale-
boundary, error-type coverage, hour-long outage), even though its actual
fix (unconditional 60s-forever) is not what we're implementing.
