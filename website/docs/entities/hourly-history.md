---
title: Hourly precipitation history
description: The gauge-adjusted rain of each past hour at your location, for blueprints that look at rain over several hours or days.
---

The **Hourly precipitation history** sensor
(`sensor.<name>_hourly_precipitation_history`) keeps the rain of each past
clock hour at your location: by default the last 72 hours, each with its
time. It is made for blueprints that judge rain over several hours or days,
such as warnings of continuous rain, or a report of how much fell since
yesterday.

Each hour is DWD's gauge-adjusted analysis, the value
[`Precipitation previous hour`](radolan.md) shows for that hour. A template
sensor that captures that value would miss every hour Home Assistant was
off; this sensor keeps them on disk and fills them in afterwards.

## Turning it on

The sensor is off by default. Turn it on in the options, section *Hourly
precipitation history*, with
[*Add the "Hourly precipitation history" sensor*](../getting-started/configuration.md#hourly-history),
and choose there how many hours it keeps. Turning it off removes the sensor
and deletes the hours it kept.

It is a diagnostic sensor, so it appears under *Diagnostic* on the device
page rather than with the other sensors.

## State and attributes

The state is the end of the newest hour held, as a time. It changes once an
hour, about 30 minutes after the hour ends, when DWD publishes it.

| Attribute | Meaning |
|-----------|---------|
| `hours` | Every hour held, oldest first: the end of the hour (UTC) and its rain in mm. `null` when DWD's file had no data for your location (a radar outage). |
| `missing` | The hours of the window that are not held, oldest first, by their end. |
| `hours_kept` | How many hours the window holds (the option *Hours to keep*). |

```yaml
# state: 2026-11-17T14:00:00+00:00
hours:
  "2026-11-14T17:00:00+00:00": 0.4
  "2026-11-14T18:00:00+00:00": null
  …
missing:
  - "2026-11-15T03:00:00+00:00"
hours_kept: 72
```

The window always ends at the newest hour DWD should have published by now.
If DWD is late, that hour shows in `missing` rather than being left out, so a
blueprint can tell an incomplete window from a dry one: a window is complete
when none of its hours is in `missing`.

The sensor stays available while DWD is late, since the hours already held
are still correct. None of its attributes is stored in Home Assistant's
history database.

## Missing hours

An hour is missing when Home Assistant was off when DWD published it, or
DWD did not publish it in time. With
[*Fetch missing data from DWD*](../getting-started/configuration.md#hourly-history-fetch)
on (the default), the integration downloads missing hours, about 30 KB
each, in the background after each new hour, newest first. A failed download
is retried with the next hour.

DWD keeps only the last 48 hours on its server. An hour older than that
which was missed stays in `missing` until it leaves the window; with the
default of 72 hours, a downtime of more than two days leaves a gap.

With the option off, only hours the integration reads anyway are kept: the
current one each hour, and those
[`Precipitation total`](totals.md) or
[`Timespan without precipitation`](dry-streak.md) download for themselves
after a downtime. Hours the history already holds are never downloaded again
for those sensors.

## Together with Rain events

The newest hour ends about 30 to 90 minutes before now. For the time after
it, the [`Rain events`](rain-events.md) sensor has the radar's 5-minute steps
of the last two hours in its `measured` attribute, and its forecast in
`steps`. A blueprint that needs the rain up to now, or up to two hours ahead,
adds those after the newest hour: the hours end on the full hour and the
steps on 5-minute marks, so nothing is counted twice.

With *Fetch missing data from DWD* on, radar steps missed after the newest
hour (for example during a restart) are fetched too. Steps in `measured`
before the newest hour may stay `null`; the hour covers them.

## Example: the rain of the last 6 hours

```jinja
{% set h = state_attr('sensor.home_hourly_precipitation_history', 'hours') %}
{% set ends = (h | list)[-6:] %}
{{ ends | map('extract', h) | reject('none') | sum | round(1) }}
```

Check `missing` as well if the result must cover all six hours.
