---
title: Rain warnings
description: Your own warnings, such as "Laundry, 60 minutes ahead", each with an on/off and a status entity.
---

A **rain warning** turns on shortly before rain reaches your location and
stays on while it rains. You set how early, and optionally how much rain is
worth a warning: "Laundry, 60 minutes ahead", "Windows, 15 minutes ahead,
only for a heavy burst". Add as many as you like.

Rain warnings need no blueprint and no template: each one is a device with
two entities that an automation can trigger on.

## Adding a warning

Open **Settings > Devices & services > DWD Precipitation**, then select
**Add rain warning** on the location's entry. The form asks for:

| Field | Default | Meaning |
|-------|---------|---------|
| Name | | What the warning is for, such as `Laundry`. Each warning of a location needs its own name |
| Lead time | 30 min | How many minutes before the rain the warning turns on, from 5 to 120 in steps of 5 |
| Minimum rain in total | empty | Only warn about a rain event that brings at least this much, measured and forecast (mm) |
| Minimum rain in the wettest hour | empty | Only warn about an event whose wettest hour brings at least this much (mm) |
| Minimum rain in the wettest 10 minutes | empty | Only warn about an event whose wettest 10 minutes bring at least this much (mm), for short heavy bursts |
| With several minimums | one is enough | Whether an event has to reach one of the minimums you set, or all of them |

Leave all minimums empty to be warned about every rain event.

To change a warning later, open its menu on the entry and select
**Reconfigure**. Deleting it removes its device and entities. Adding,
changing or deleting a warning reloads the integration; the values come back
within a few seconds.

## Entities

Each warning is a device of its own, named after the location and the
warning: a warning `Laundry` at the location `Home` is the device
`Home Laundry` with:

| Entity | Entity id | States |
|--------|-----------|--------|
| Rain warning | `binary_sensor.home_laundry_rain_warning` | `on` while it rains or is about to, `off` otherwise |
| Rain warning status | `sensor.home_laundry_rain_warning_status` | `dry`, `soon` or `rain` |

The status sensor has the details as attributes; the on/off entity has none.

| Status | Meaning |
|--------|---------|
| `rain` | a rain event that passes the warning's minimums is falling now |
| `soon` | none is, but one that passes them starts within the lead time |
| `dry` | neither |

Renaming a warning renames its device and entities; the entity ids stay as
they were, so your automations keep working.

Both entities are `unknown` while there is nothing to judge yet, for example
for a few seconds after a restart, and `unavailable` when the radar forecast
is out of date, like the other forecast sensors.

## Attributes

| Attribute | Description |
|-----------|-------------|
| `event_id` | The id of the rain event the warning is about, as in [Rain events](rain-events.md#events) |
| `start` | When that event starts (or started), ISO-8601 in UTC |
| `mm` | Its total: measured so far plus forecast, in mm |
| `peak_1h` | The rain in its wettest hour, in mm |
| `peak_10min` | The rain in its wettest 10 minutes, in mm |
| `type` | Reserved for the measured precipitation type; always `null` for now |

All of them are `null` while the status is `dry`, and none is recorded in
history.

## How a warning decides

A warning has no rain logic of its own: it reads the rain events the
integration tracks for the location, the same events the
[Rain events](rain-events.md) sensor shows. So what counts as rain is the
advanced option
[*Rain event threshold*](../getting-started/configuration.md#rain-event-threshold),
and the forecast reaches two hours ahead.

- The lead time counts from when the radar data arrives in Home Assistant.
  The data comes every 5 minutes, so a warning can turn on up to 5 minutes
  later than the lead time says. DWD's data is already a few minutes old when
  it arrives (see [Release timing](../how-it-works/release-timing.md)), so a
  short lead time leaves less time than it suggests: use at least 10 or
  15 minutes for anything that takes a while.
- The minimums are compared with the event's total: what has fallen so far
  plus what is forecast. An upcoming event has only its forecast.
- Once an event has reached the minimums, it keeps counting until it has
  ended, even if a later forecast makes it smaller. A shower does not switch
  the warning off and on again just because its forecast changed.
- A forecast often loses a small shower for one release and finds it again
  in the next. A warning that was `soon` stays `soon` for that one release;
  if the shower is still missing in the next one, the warning goes back to
  `dry`.
- These two memories are kept in memory only. After a restart, an event is
  judged again on its current values.

## Good to know

- Rain warnings use the rain-events tracker, but not the `Rain events`
  sensor: they work with the option *Track rain events* off. While a
  location has a warning, the integration fetches the radar analyses it
  missed (a small part of each file) and keeps a small record of recent rain
  on disk. Deleting the last warning, with *Track rain events* off, deletes
  that record.
- The amounts are radar only, like the [Rain events](rain-events.md#good-to-know)
  they come from.
- Rain warnings need Home Assistant 2025.4 or newer.
