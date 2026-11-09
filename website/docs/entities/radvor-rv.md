---
title: RADVOR RV nowcast
description: Precipitation intensity now, peak intensities, start and end of rain, Precipitation expected and the wettest hour ahead.
---

RADVOR RV is DWD's radar nowcast in 5-minute steps. Every 5 minutes DWD
publishes 25 steps: the latest measured 5 minutes (the analysis) and 24
forecast steps reaching two hours ahead. From those, the integration derives
how hard it is raining, how hard it will rain, when rain starts and stops, and
the wettest hour ahead.

## Precipitation intensity now

**Precipitation intensity now** (mm/h) is the rain rate in the latest radar
analysis: the 5 minutes ending at DWD's release time, scaled to an hourly rate
(1 mm in 5 minutes = 12 mm/h). It updates every 5 minutes; the window it
describes ended about 4 to 10 minutes before the value appears.

It is `unknown` when the radar has no data for your location.

| Attribute | Meaning |
|-----------|---------|
| `window_start` / `window_end` | Start and end of the 5-minute analysis, ISO-8601 UTC |
| `amount_5min` | The rain in that window in mm, before scaling to mm/h; `null` without data |

## Peak intensities

The heaviest rain rate (mm/h) expected in a window. They tell drizzle from a
downpour; the [RS sensors](radvor-rs.md) give the amounts.

| Sensor | Window |
|--------|--------|
| **Peak intensity next 60 min** | the next hour |
| **Peak intensity next 60–120 min** | the second hour ahead |
| **Peak intensity next 120 min** | the whole two hours: the larger of the two above |

`Peak intensity next 120 min` suits a single "heavy rain ahead" trigger.

## Peak hourly precipitation

**Peak hourly precipitation next 120 min** (mm) is the most rain forecast to
fall in any 60-minute window within the next two hours, checked in 5-minute
steps. It is `0` when no rain is forecast.

A downpour that straddles the one-hour mark shows here in full, where
`Precipitation next 60 min` and `Precipitation next 60–120 min` each only see
part of it. This matches how DWD defines its heavy-rain warnings (an amount
per hour), so it suits alert automations.

It is calculated from the RV 5-minute forecast, which adds up to the RS
rolling hours. In the rare cells where DWD's two products differ, it can read
below `Precipitation next 60 min` (by up to about half a millimetre), which it
otherwise never does.

| Attribute | Meaning |
|-----------|---------|
| `window_start` / `window_end` | Start and end of the wettest hour, ISO-8601 UTC; `null` when no rain is forecast. If two windows tie, the earlier one |
| `forecast_rolling_1h` | The series of hours the sensor picks from, see below |

### The rolling-hour series

`forecast_rolling_1h` has one entry every 5 minutes, each the rain in the
hour from its `start` to its `end` (in mm); `lead` is the minutes from the
release time to `end`. At 14:00 the entries run from 14:00–15:00 to
15:00–16:00, 13 entries, and the sensor shows the largest.

With the option
[*Add the past hour to the hourly rain series*](../getting-started/configuration.md#past-hour-in-the-series)
on, the series starts one hour earlier, at 13:00–14:00 (25 entries), so a
chart shows the past hour and the forecast as one curve. The first entry is
then the same hour as `Precipitation last 60 min`, added up from DWD's
5-minute analyses, so in rare cells the two differ slightly. The earlier
entries appear once the integration has seen a full hour of releases, so
for up to an hour after a restart the series has 13 entries.

## Precipitation start and end

**Precipitation start** is when rain begins, **Precipitation end** when it
stops, within the two-hour forecast.

- `Precipitation start` is now (or `0` minutes) if it is already raining,
  and `unknown` if no rain is forecast within two hours.
- `Precipitation end` is `unknown` if rain continues beyond two hours. That
  means "still raining in two hours", not "never".

What counts as rain is set by the
option [*Only count rain heavier than*](../getting-started/configuration.md#rain-detection-threshold)
in the *Rain forecast* section. By default, any amount DWD detects counts.

**Format.** The option
[*Show start and end as*](../getting-started/configuration.md#start-and-end-format)
makes both sensors either timestamps (the default) or durations in minutes.
The other form is always available as an attribute:

| Attribute | Meaning |
|-----------|---------|
| `at` | The time of the event, ISO-8601 UTC (when the state is minutes) |
| `minutes_until` | Whole minutes until the event (when the state is a time) |

**When rain counts as over.** The option
[*"Precipitation end" shows*](../getting-started/configuration.md#end-algorithm)
picks one of two answers:

- **The first dry break** (default): the end of the current burst. During showers
  it moves around, since each gap between two cells is an end.
- **When no more rain is forecast:** the end of the last rain in the
  forecast, after which nothing more is expected within the horizon.
  Steadier, but it stays `unknown` longer.

## Precipitation expected

**Precipitation expected** is a binary sensor: `on` if rain is forecast
within the next two hours, using the same
[*Only count rain heavier than*](../getting-started/configuration.md#rain-detection-threshold)
setting as `Precipitation start`.

| Attribute | Meaning |
|-----------|---------|
| `at` / `minutes_until` | When the forecast rain starts; `null` when none is expected |
| `forecast_5min` | The full 25-step forecast, see below |

`forecast_5min` lists the analysis and the 24 forecast steps (0 to 120
minutes in 5-minute steps). Each step has `lead` (minutes from the release
time), `start`, `end`, `value` (mm in those 5 minutes) and `intensity` (mm/h).
`value` and `intensity` are `null` for a step without data. It is always
present, so blueprints and charts can use it, and it is not recorded in
history.

A template that sums the forecast rain of the next 30 minutes:

```jinja2
{{ state_attr('binary_sensor.home_precipitation_expected', 'forecast_5min')
   | selectattr('lead', 'gt', 0) | selectattr('lead', 'le', 30)
   | map(attribute='value') | reject('none') | sum | round(2) }}
```

## Good to know

- **Radar only**, like RS: the values can differ from a rain gauge and from
  the [RADOLAN](radolan.md) sensors.
- **Two-hour horizon.** DWD's nowcast ends two hours ahead. Anything later is
  not known to these sensors, which is why start and end can be `unknown`.
- [Rain events](rain-events.md), if turned on, are built from the same RV
  steps.
