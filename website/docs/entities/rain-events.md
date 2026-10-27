---
title: Rain events
description: The Rain events sensor follows each shower at your location, from the first forecast that shows it until it has passed.
---

The **Rain events** sensor (`sensor.<name>_rain_events`) follows each shower
at your location as one *rain event*: from the first forecast that shows it,
while it is falling, until it has passed. For each event it tells you when it
starts and ends, how much rain is forecast, how much has actually fallen, and
whether it is rain, snow or hail.

It is made for blueprints and automations that warn about rain or report on
it afterwards, such as "Heavy shower in 20 minutes, 8 mm expected" or "That
shower brought 12 mm, 3 mm more than forecast".

:::tip Just want a warning?

For a plain warning such as "Laundry, 60 minutes ahead" you need neither this
sensor nor a blueprint: add a [rain warning](rain-warnings.md). It works on
the same rain events and gives you a simple on/off entity.

:::

## Turning it on

The sensor is off by default. Turn it on in the options, section *Rain
events and rain warnings*, with
[*Add the "Rain events" sensor*](../getting-started/configuration.md#track-rain-events).

While it is on, the integration keeps a small record of recent rain on disk,
and downloads radar data it missed (for example while Home Assistant was
restarting), so that an event's amounts have no gaps. Turning the sensor off
removes it; the record is deleted too, unless a rain warning still uses it.

## How it works

### Five-minute steps {#steps}

DWD's radar measures the rain every 5 minutes and forecasts it two hours
ahead, also in 5-minute steps. The integration puts the two together into one
timeline for your location: the **last hour as measured** (12 steps) and the
**next two hours as forecast** (24 steps).

Every 5 minutes DWD publishes a new update, called a *release* here. With
each release the oldest measured step drops out, the step that has just ended
is measured, and the forecast moves on by 5 minutes.

### What counts as rain {#what-counts-as-rain}

A step counts as wet when it has more rain than the option
[*Only count rain heavier than*](../getting-started/configuration.md#rain-event-threshold)
allows, in the section *Rain events and rain warnings*. The default is
0.1 mm/h, which lets through anything but the faintest trace. The option is
an intensity per hour; for a 5-minute step it is divided by 12 (the
attribute `wet_step_mm` shows the result).

Changing this setting starts the events over, with new ids. The measured
steps and `last_ended` are kept.

The sensor itself has no warning levels: whether 2 mm is worth a message is
up to your blueprint, or to a [rain warning](rain-warnings.md)'s minimums.

### From forecast to measurement {#events}

Wet steps that follow each other form a rain event. An event goes through
these stages:

1. **upcoming:** the forecast shows rain, but none has fallen yet. The event
   gets an id that it keeps until it is over.
2. **ongoing:** the radar has measured its first rain. From now on the event
   has measured amounts as well as forecast ones, and a precipitation type.
3. **ended:** two measured dry steps in a row (10 minutes) follow its last
   rain. The event moves to `last_ended`, with its final amounts.

A single dry step in between does not end an event: a short break in a
shower is still the same shower.

Forecasts change from one release to the next, and the events follow:

- **A forecast loses a shower.** Forecasts often drop a small shower for one
  release and find it again in the next. An upcoming event the latest
  forecast does not show is kept for one release as `unseen`; if the next
  forecast shows it again, it continues under its id, otherwise it is gone.
- **Two showers join.** The event that was seen first keeps its id and lists
  the others in `absorbed`.
- **A shower splits.** The earlier part keeps the id, the later part becomes
  a new event.
- **Missing data.** A measured step without data (DWD did not deliver it, or
  Home Assistant was not running) does not end or split an event, since it
  may have rained. If the step cannot be fetched later, it counts as dry
  once it has left the last hour, and an event ended that way has
  `end_clipped` set. More than 3 hours of steps without data in a row count
  as dry. A forecast step without data counts as dry.

So if an id disappears from `events`, it was merged if it is in some event's
`absorbed`, it ended if it is `last_ended.id`, and otherwise the forecast
dropped it.

### An example

At 14:00 the forecast shows a shower from 14:35 to 15:05. The times on the
left are releases; each one reaches Home Assistant a few minutes later, when
DWD has published it (see [Release timing](../how-it-works/release-timing.md)).

| Release | What happens | State |
|---------|--------------|-------|
| 14:00 | The event appears, with `start` 14:35, `end` 15:05 and a forecast of 3 mm. | `upcoming` |
| 14:10 | A newer forecast moves it to 14:40. Same id, new times. | `upcoming` |
| 14:45 | The radar measured rain from 14:40 to 14:45: the first rain. The forecast of the release before (14:40) is kept as `forecast_at_onset`. | `ongoing` |
| 15:00 | 4.2 mm have fallen so far (`observed.mm`), 0.8 mm more are forecast (`forecast.mm`). | `ongoing` |
| 15:20 | The last rain ended at 15:10, and the two steps after it were dry. The event moves to `last_ended`. | `none` |

## State

| State | Meaning |
|-------|---------|
| `ongoing` | a rain event is falling now |
| `upcoming` | none is falling, but one is forecast within two hours |
| `none` | neither (an `unseen` event alone also counts as `none`) |

An automation can trigger on the state and read the details from the
attributes. If the event tracking fails, the attributes are left out and the
state is `unknown` rather than a guess.

## Attributes

The attributes hold the details. They are meant for blueprints and
templates, and are a fixed contract: their names and meaning change only
with a new `schema` number. None of them are recorded in history, so they do
not fill your database.

All times are in UTC, in ISO format such as `2026-10-12T14:30:00+00:00`; in
a template, `as_local(as_datetime(...))` turns one into your local time. All
amounts are in mm.

This is what the attributes look like during the example above, at 15:00:

```yaml
schema: 1
base: "2026-10-12T15:00:00+00:00"
wet_step_mm: 0.008
steps_start: "2026-10-12T14:00:00+00:00"
steps: [0.0, 0.0, …, 0.6, 0.9, …, 0.3, 0.0, …]   # 36 values
history_complete: true
events:
  - id: "20261012t1400-0"
    status: ongoing
    first_seen: "2026-10-12T14:00:00+00:00"
    start: "2026-10-12T14:40:00+00:00"
    start_clipped: false
    end: "2026-10-12T15:10:00+00:00"
    beyond_horizon: false
    last_wet_observed: "2026-10-12T15:00:00+00:00"
    missing_steps: 0
    observed_complete: true
    observed:
      mm: 4.2
      peak_1h: {mm: 4.2, start: "…14:40…", end: "…15:00…"}
      peak_10min: {mm: 1.5, start: "…14:45…", end: "…14:55…"}
      types: {rain: 4}
    forecast: {mm: 0.8, peak_1h: {…}, peak_10min: {…}}
    total: {mm: 5.0, peak_1h: {…}, peak_10min: {…}}
    type: rain
    forecast_at_onset:
      base: "2026-10-12T14:40:00+00:00"
      start: "2026-10-12T14:40:00+00:00"
      end: "2026-10-12T15:05:00+00:00"
      mm: 3.0
      peak_1h: {…}
      peak_10min: {…}
      expected_so_far_mm: 2.9
      observed_so_far_mm: 4.2
    absorbed: []
last_ended: null
```

### The timeline

| Attribute | Meaning |
|-----------|---------|
| `schema` | The version of this layout, now `1`. A blueprint should check it: it changes only when something changes in a way that would break blueprints. |
| `base` | The time of the latest release: the end of the newest measured step, and "now" as far as the data goes. |
| `wet_step_mm` | How much rain a 5-minute step needs to count as wet, from the threshold option (0.1 mm/h gives `0.008`). A step is wet *above* this. |
| `steps_start` | The start of the first step in `steps`, one hour before `base`. |
| `steps` | The rain of each 5-minute step, in mm: first the 12 measured ones up to `base`, then the 24 forecast ones. `steps[i]` covers the 5 minutes from `steps_start` + 5 × i minutes. `null` means no data for that step. The forecast part is the same as the `forecast_5min` of [`Precipitation expected`](radvor-rv.md#precipitation-expected). |
| `history_complete` | `true` when all 12 measured steps have data. |
| `events` | The upcoming, ongoing and `unseen` events, earliest first. Empty when no rain is in sight. |
| `last_ended` | The most recent event that has ended, or `null`. See [last_ended](#last_ended). |

### An event

Each entry of `events` has:

| Attribute | Meaning |
|-----------|---------|
| `id` | The event's name, such as `20261012t1400-0`. It stays the same for the event's whole life and is never used for another one. Use it only to recognise an event; do not read anything into the text. |
| `status` | `upcoming`, `ongoing` or `unseen`, see [From forecast to measurement](#events). |
| `first_seen` | The release that first showed the event: how early it was announced. |
| `start` | When its rain starts: the start of its first wet step. Forecast while upcoming, measured once ongoing. |
| `start_clipped` | `true` if the rain may have started earlier than `start`, because the steps before it have no data (for example after a restart). |
| `end` | When its rain ends: the end of its last wet step, measured or forecast. While the event is ongoing this is usually still a forecast. |
| `beyond_horizon` | `true` if it is still raining at the end of the forecast, two hours ahead. `end` is then only the end of the forecast, and the rain may go on longer. |
| `last_wet_observed` | The end of the latest step in which rain was actually measured. `null` while upcoming. |
| `missing_steps` | How many measured steps of the event have no data. |
| `observed_complete` | `true` if the measured part is complete: no `missing_steps` and no `start_clipped`. If `false`, the measured amounts may be too low. |
| `observed` | The rain measured so far, see [Amounts](#amounts). |
| `forecast` | The rain still forecast for the event, within the two hours. |
| `total` | Measured and forecast together: the best guess for the whole event. |
| `type` | The precipitation type of the latest measured wet step, such as `rain` or `snow`. `null` while upcoming, see [Precipitation type](#precipitation-type). |
| `forecast_at_onset` | What the forecast said just before the rain arrived, see [Forecast at onset](#forecast-at-onset). `null` while upcoming, and for rain that was never forecast. |
| `absorbed` | The ids of events that joined this one. |

An `unseen` event shows the values it had in the last forecast that showed
it.

### Amounts

`observed`, `forecast` and `total` each have:

| Attribute | Meaning |
|-----------|---------|
| `mm` | The amount of rain. |
| `peak_1h` | The wettest 60 minutes, as `mm`, `start` and `end`. For an event shorter than an hour, the whole event. |
| `peak_10min` | The wettest 10 minutes (two steps in a row), as `mm`, `start` and `end`. Good for short heavy bursts. |

`observed` also has `types`, see below. A peak is `null` when there is
nothing to look at, for example `forecast.peak_1h` once all the rain has
fallen.

Two details for blueprints that compare against warning levels:

- `total.peak_1h` is the wettest hour of `steps` that overlaps the event,
  *including* rain just outside it. DWD's heavy-rain warnings are based
  simply on the amount within an hour, so two showers close together add up.
- Steps without data count as 0 mm in every amount.

### Precipitation type

- `observed.types` counts the event's measured wet steps by type, as DWD's
  [HymecNG](hymecng.md) classification gave it for your location at the end
  of each step. The types are the states of
  [Precipitation type now](hymecng.md#precipitation-type-now), such as
  `rain`, `snow` or `hail`. `{rain: 9, snow: 3}` means 45 minutes of rain and
  15 of snow.
- `type` is the type of the latest measured wet step that has one.
- Only measured steps have a type. DWD forecasts amounts, not types, so an
  upcoming event has `type: null` and no `types`; its type appears with its
  first measured rain. The integration does not guess one.
- The types are DWD's, as they are. HymecNG classifies separately from the
  amounts, so a wet step can come with `no_precipitation` or
  `not_classified`; it is counted under that state.
- A wet step without a type is not counted, so the counts can add up to fewer
  than the event's wet steps. That happens when HymecNG has no data for your
  location, or its file could not be fetched; a missed type is fetched later,
  like missed radar data, while the step is within the last hour.
- A step usually gets its type before its radar measurement arrives. A type
  that arrives later shows from the next release on.

### Forecast at onset

`forecast_at_onset` is the last forecast for the event before its rain
arrived, kept unchanged from then on. It answers "what were we warned
about?":

| Attribute | Meaning |
|-----------|---------|
| `base` | The release of that forecast. |
| `start`, `end` | When that forecast expected the rain to start and end. |
| `mm`, `peak_1h`, `peak_10min` | The amounts that forecast expected. |
| `expected_so_far_mm` | What that forecast expected for the steps measured since then. |
| `observed_so_far_mm` | What actually fell in those same steps. |

The last two cover exactly the same steps (at most the two hours the forecast
reached), so they compare like with like: "9 mm fell where 3 mm were
expected".

### last_ended

`last_ended` is the most recent event that has ended, with its final values:
`id`, `first_seen`, `start`, `start_clipped`, `end`, `missing_steps`,
`observed`, `type`, `forecast_at_onset` and `absorbed`, as for an event, plus:

| Attribute | Meaning |
|-----------|---------|
| `end_clipped` | `true` if the end was decided by steps without data, so the rain may have lasted longer. |
| `observed_complete` | `true` if nothing is missing: no `missing_steps`, no `start_clipped` and no `end_clipped`. |

It has no `forecast` or `total`: everything has been measured. It stays until
the next event ends, so a blueprint that reports on events should act when it
sees a new `last_ended.id`.

## Template examples

Replace `sensor.home_rain_events` with your sensor. When the next rain
starts, in local time:

```jinja
{% set events = state_attr('sensor.home_rain_events', 'events') or [] %}
{% set upcoming = events | selectattr('status', 'eq', 'upcoming') | first %}
{{ as_local(as_datetime(upcoming.start)).strftime('%H:%M') if upcoming else 'no rain in sight' }}
```

How much the current shower is expected to bring in total:

```jinja
{% set events = state_attr('sensor.home_rain_events', 'events') or [] %}
{% set now_raining = events | selectattr('status', 'eq', 'ongoing') | first %}
{{ now_raining.total.mm if now_raining else 0 }} mm
```

How the last shower compared with its forecast:

```jinja
{% set last = state_attr('sensor.home_rain_events', 'last_ended') %}
{% if last and last.forecast_at_onset %}
  {{ last.forecast_at_onset.observed_so_far_mm }} mm fell,
  {{ last.forecast_at_onset.expected_so_far_mm }} mm were forecast.
{% endif %}
```

## Good to know

- The amounts are radar only, measured and forecast alike, so nothing jumps
  at "now". They differ from a rain gauge and from the gauge-adjusted sensors
  such as `Precipitation total`.
- Missed radar data can be fetched up to an hour back. After a longer
  downtime, or while DWD keeps failing to deliver a release, an event's
  measured values can be too low: check `observed_complete` (and
  `missing_steps`, `start_clipped`, `end_clipped`). The same goes for the
  types, whose counts then miss those steps. In short, don't restart Home
  Assistant during a severe downpour.
- The record survives restarts and option changes. Deleting the integration
  entry deletes it.
- [ADR 0006](/development/adr/0006-rain-events-opt-in-entity) explains why
  the events are their own opt-in entity and are recomputed every release,
  [ADR 0012](/development/adr/0012-rain-event-types-are-measured-only) why
  they have a type only once it is measured.
