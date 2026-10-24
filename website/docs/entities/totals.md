---
title: Running totals
description: Precipitation total and Precipitation total daily, for Home Assistant's long-term statistics.
---

Two ever-growing totals of all rain since setup. They exist for Home
Assistant's long-term statistics: use them for daily, weekly, monthly or
yearly rain sums. The other sensors are snapshots of a window and do not add
up correctly over time.

| Sensor | Unit | Adds | Grows |
|--------|------|------|-------|
| **Precipitation total** | mm | each `Precipitation previous hour` once | hourly |
| **Precipitation total daily** | mm | each `Precipitation yesterday` once | daily |

Both have the state class `total_increasing`, so they work with Home
Assistant's long-term statistics, the statistics graph card and the
[Utility Meter](https://www.home-assistant.io/integrations/utility_meter/)
helper.

## Precipitation total

Adds each [`Precipitation previous hour`](radolan.md) value once: the
gauge-adjusted total of each clock hour. It is up to date within the hour, so
it also suits "how much rain since this morning" automations. This is the one
to use.

Home Assistant's statistics see each hour about half an hour after it ends
(11:00–12:00 is added at about 12:28), so only the last hour of a day spills
into the next one.

## Precipitation total daily

Adds each [`Precipitation yesterday`](radolan.md) value once. Today's rain
only appears the next morning, and Home Assistant's statistics count it on
the day it was added, so **each day's rain shows up under the following day**.
Prefer `Precipitation total` unless you specifically want DWD's daily
analysis.

It is disabled by default on installs set up from 2026.11.0 on. Enable it on
the entity's settings page if you need it; it starts counting from then.
Installs that already had it keep it enabled.

On the two daylight-saving changeover days the 23:50 windows are 23 or 25
hours apart while each file covers 24 hours, so one hour is counted twice in
spring and missed in autumn.

## How they count

- Both start at 0 when the integration is set up, and keep their total
  across restarts.
- Each DWD release is counted once, however many times it is seen, and two
  equally wet hours are still two releases.
- A file without data for your grid cell adds nothing.
- They **stay available while DWD is not publishing**, because the total
  counted so far is still correct. The option *Show "unavailable" when the
  data is out of date* does not apply to them.

| Attribute | Meaning |
|-----------|---------|
| `counted_until` | End of the newest DWD window included in the total, ISO-8601 UTC; `null` until the first file arrives |

## Missed hours are added late

If Home Assistant was offline, or DWD failed to publish for a while, the
missed files are fetched in the background on the next update and added
late. The list of missed files is saved with the total, so a restart in the
middle resumes it, and a file that fails to download is tried again with
every new one, for as long as DWD keeps it: 48 hours for
`Precipitation total`, and only the day before for
`Precipitation total daily`. Only files DWD no longer serves are left out,
and the log says so.

Rain added late counts in Home Assistant's statistics at the time it was
added, not the hour it fell. `counted_until` does not move back for it.

## Example: rain this month

A [Utility Meter](https://www.home-assistant.io/integrations/utility_meter/)
helper that resets monthly, in `configuration.yaml`:

```yaml
utility_meter:
  rain_this_month:
    source: sensor.home_precipitation_total
    cycle: monthly
```

You can create the same helper in the UI under **Settings > Devices &
services > Helpers > Create helper > Utility Meter**.

## Why there are two

They are separate entities rather than one with a source option, because
switching the source of a `total_increasing` sensor would make it jump. See
[ADR 0005](/development/adr/0005-running-totals) for the reasoning.
