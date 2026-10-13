# 0006 — Rain events are their own opt-in entity, recomputed every release

Status: accepted (2026.10.1)

## Context

The rain-events tracker publishes a view (schema 1) that blueprints depend on:
a few KB that change every release. Its measured steps are RV analyses (lead
0); only the release whose analysis it is has one, so a missed release leaves a
gap the integration fills by fetching that analysis later.

## Decision

- **Own entity.** In pre-releases the view sat on `Precipitation expected` as
  a `rain_events` attribute; a binary flag is the wrong home for it. It is the
  `Rain events` sensor, whose state (`ongoing` / `upcoming` / `none`) a
  blueprint can trigger on.
- **Opt-in.** The `rain_events` option (Advanced, default off) gates all of
  it: no tracker, no fill requests, no store. Nothing on 2026.10.0 had it, so
  it is off for existing installs as well. Turning it off removes the entity
  from the registry and deletes the store, so turning it on again starts clean.
- **Recomputed, not accumulated.** Each release rebuilds the timeline from
  the kept measured steps and recomputes every event's amounts and peaks. This
  deviates from the spec's incremental accumulators on purpose: the values are
  the same, but a late fill can never be counted twice, and `observed` can
  never go down.
- **Fill before matching, in the background.** Updating first and filling
  after can swap event ids and lose `forecast_at_onset` when it rained during a
  downtime, so a release with steps to fill runs fill, update and publish as
  one background task. Setup waits for RV's first refresh, and must not wait
  for the fill too; meanwhile the sensor keeps the view it showed before.
  Later releases queue behind a running round.
- **Views are stored.** An `unseen` event is republished from its last view,
  and the stored view answers the same release after a restart without
  processing it twice.
