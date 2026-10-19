---
title: Rain events
description: The Rain events sensor follows each burst of rain from forecast to measurement, for blueprints.
---

The **Rain events** sensor (`sensor.<name>_rain_events`) is meant for
blueprints that warn about or report short bursts of rain. It follows each
event from the first forecast that shows it until it has fallen, under one id,
and reports what was forecast against what was measured.

It is off by default. Turn it on with the advanced option
[*Track rain events*](../getting-started/configuration.md#track-rain-events).
With it on, the integration also fetches radar analyses it missed and keeps a
small record of recent rain on disk; turning it off removes the sensor and
that record.

## State

| State | Meaning |
|-------|---------|
| `ongoing` | a rain event is falling now |
| `upcoming` | none is falling, but one is forecast within two hours |
| `none` | neither (an `unseen` event alone also counts as `none`) |

A blueprint can trigger on the state, and read the details from the
attributes. If the tracker fails, the attributes are left out and the state is
`unknown` rather than a guess.

## What counts as rain

The sensor applies one threshold, the advanced option
[*Rain event threshold*](../getting-started/configuration.md#rain-event-threshold)
(default 0.1 mm/h): a 5-minute step is wet if its amount is above a twelfth of
it. Warning levels are up to the blueprint.

Changing the threshold starts the events over with new ids; the measured
steps and `last_ended` are kept.

## Attributes

The attributes are a contract with blueprints, versioned by `schema`. None of
them are recorded in history.

```yaml
schema: 1                              # check this; it changes only on a breaking change
base: "2026-10-12T14:30:00+00:00"      # T, the release time (= forecast_5min[0].end
                                       #   of Precipitation expected)
wet_step_mm: 0.008                     # a step is wet above this (mm per 5 min)
steps_start: "2026-10-12T13:30:00+00:00"
steps: [0.0, …, 1.5, …]                # 36 values, mm per 5 min: 12 measured ending at T,
                                       # then forecast_5min[1..24]; null = unknown
history_complete: true                 # no null among the 12 measured steps
events:                                # upcoming | ongoing | unseen, sorted by start
  - id: "20261012t1405-0"              # opaque, stable, never reused
    status: ongoing
    first_seen: "…"                    # T of the first release that showed it
    start: "…"                         # start of the first wet step
    start_clipped: false               # it may have started earlier (no data before)
    end: "…"                           # end of the last wet step, forecast while ongoing
    beyond_horizon: false              # true: still raining at the 2 h horizon
    last_wet_observed: "…"             # null while upcoming
    missing_steps: 0                   # measured steps without data inside the event
    observed_complete: true            # false: measured amounts may be too low
    observed: {mm, peak_1h: {mm, start, end}, peak_10min: {mm, start, end}}
    forecast: {mm, peak_1h, peak_10min}
    total:    {mm, peak_1h, peak_10min}
    forecast_at_onset: {base, start, end, mm, peak_1h, peak_10min,
                        expected_so_far_mm, observed_so_far_mm}   # or null
    absorbed: []                       # ids merged into this event
last_ended: {id, first_seen, start, start_clipped, end, end_clipped, missing_steps,
             observed_complete, observed, forecast_at_onset, absorbed}   # or null
```

### Steps

`steps[i]` covers 5 minutes from `steps_start + 5·i min`: 12 measured steps
ending at the release time `base`, then the 24 forecast steps. The measured
part is DWD's radar analysis of each release. Releases the integration missed
are fetched later (only their analysis, a small part of the file), so a lost
release does not leave a gap.

### Events

- Two dry steps in a row end an event; a single one does not.
- A step without data never splits or ends an event.
- An upcoming event that one release does not show stays for that release as
  `unseen`.
- When several events join, the one first seen earliest keeps its id and
  lists the others in `absorbed`. When one splits, the later part gets a new
  id.
- An id that disappears was merged if it is in some `absorbed`, ended if it
  is `last_ended.id`, and vanished otherwise.

### Amounts

- `observed` covers the event's measured steps, `forecast` its forecast steps
  within the two-hour horizon, `total` both.
- `peak_1h` is the wettest hour, `peak_10min` the wettest two steps.
- `total.peak_1h` is the wettest hour of `steps` that overlaps the event,
  *including* rain just outside it, because DWD's heavy-rain criterion is
  simply the amount within an hour.

### Forecast at onset

`forecast_at_onset` is the event's last forecast before its rain arrived,
frozen when it did. `expected_so_far_mm` and `observed_so_far_mm` cover
exactly the same steps since then, for a like-for-like "9 mm measured where
3 mm was expected". It is `null` for rain that was never forecast.

### last_ended

`last_ended` is the most recent completed event, with its measured values
frozen. It stays until the next event ends, so a report blueprint must copy it
when it first sees a new id.

## Good to know

- The amounts are radar-only, measured and forecast alike, so nothing jumps
  at "now". They differ from a rain gauge and from the gauge-adjusted sensors
  such as `Precipitation total`.
- Missed releases can be fetched up to an hour back. After a longer downtime,
  or while DWD keeps failing to serve a release, an event's measured values
  can be too low: check `observed_complete` (and `missing_steps`,
  `start_clipped`, `end_clipped`). In short, don't restart Home Assistant
  during a severe downpour.
- The record survives restarts and option changes. Deleting the integration
  entry deletes it.
- [ADR 0006](/development/adr/0006-rain-events-opt-in-entity) explains why
  the events are their own opt-in entity and are recomputed every release.
