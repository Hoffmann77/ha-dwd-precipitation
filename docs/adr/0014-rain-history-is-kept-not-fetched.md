# 0014 — Rain history is kept from what is read, and filled only from what DWD still serves

Status: accepted (2026.12.0)

## Context

Blueprints that judge rain over many hours (DWD's continuous-rain warnings
look at 6 to 72 hours, ending at any time up to two hours ahead) need the
rain of each past hour at the location. The integration published only the
newest value of each product: one RW clock hour, a running total without
per-hour values, and the last 60 minutes of measured radar steps on `Rain
events`. RW for an hour arrives about 28 minutes after it, so just before the
next one the newest RW hour ended up to about 85 minutes before the latest
radar step, and 25 of those minutes were in neither.

Blueprints cannot keep this themselves: a template sensor capturing each RW
value misses every hour Home Assistant was down, which is what a report
blueprint did for its gauge-adjusted follow-up.

## Decision

- **Kept, not refetched.** The RW coordinator keeps every clock hour it
  reads, in a store per entry (`HourlyHistory`): the release it adopts, and
  every past hour another sensor downloads through `async_fetch_release`
  (the total's backfill, the dry streak's gap check). An hour already held
  is answered from the history there instead of downloaded again. This
  makes `RadolanRW.async_fetch_release` the one fetch path with a side
  effect, on purpose: it is the one place every caller of a past hour goes
  through.
- **Filled only from what DWD still serves.** With the fetch option, the
  history also fetches the hours it lacks, newest first, but never further
  back than OpenData keeps them (`RW_KEPT`, 47 hours): a new install or a
  long downtime is repaired within two days, at about 30 KB an hour, and
  anything older stays in `missing`. Without the option nothing is
  downloaded for it.
- **On the RW coordinator, not an entity.** The running total can be
  disabled and the dry streak may count RS; the history must not depend on
  either.
- **Its own diagnostic entity** (`Hourly precipitation history`), not an
  attribute of `Precipitation previous hour`: that entity turns unavailable
  minutes after an RW release is overdue (`unavailable_when_stale`, on by
  default), and Home Assistant drops an unavailable entity's attributes,
  which would empty the history exactly during a DWD outage. The history
  stays available, and its window ends at the newest hour *due*, so a late
  hour shows in `missing` rather than vanishing. Each hour is published with
  its end time (`hours`), and `null` only means "no data for the cell": an
  hour not obtained is in `missing`, never `null`.
- **Opt-in, three options**: the sensor, the hours to keep (1-168, default
  72) and whether missing data may be fetched (default on). Turning it off
  deletes the store, like Rain events (ADR 0006).
- **Two hours of measured radar steps, kept by the rain-events tracker.**
  `Rain events` publishes 24 measured steps as `measured`, enough to reach
  back to the newest RW hour. The steps stay in the tracker's store, which
  also holds the events recomputed from them (ADR 0006): a separate store
  for the steps could be restored from another moment than the events,
  which would then lose rain they had already counted. The longer retention
  is used by nothing but `measured`; the events still see the published hour.
- **Steps filled late stay out of the events.** With the hourly history
  allowed to fetch, the tracker's fill round also fetches missed steps of
  `measured` after the newest RW hour (older ones are covered by RW), after
  the steps the events need. They arrive after the events were judged
  without them, so they are marked `late`: shown in `measured`, unknown to
  every event computation, so a published start or amount never moves.
- **Writes on a fixed deadline.** Both stores write idle data at the entry's
  `SaveDeadline`, 6 h after the first unsaved change, which later releases
  do not move: Home Assistant's `async_delay_save` restarts its timer on every
  call, so a delay renewed with each release never fires before shutdown.
  The two stores share one deadline and write together, four times a dry
  day.

## Alternatives turned down

- **Fetch the hours a blueprint needs on demand.** It would download up to 72
  files for every evaluation, and OpenData does not keep the oldest 24 of
  them.
- **RW history as an attribute of `Precipitation previous hour`.** Lost
  whenever that entity is unavailable (see above), and the attributes would
  be recorded with a sensor whose history users keep.
- **The radar steps in an RV-owned store of their own,** shared by the
  tracker and the full rolling-hour series. Two stores restored from
  different moments break the events' recomputation, a rainy release would
  write both, and the RV store could not prune without asking the tracker
  what an ongoing event still needs.
- **Fill all 24 measured steps.** Up to 12 more range reads after each
  restart for steps that RW covers and no blueprint reads.
- **One store for the history and the rain events.** The two are turned on
  and off separately and delete their own data; one damaged part would
  discard the other, and every write would rewrite both.
