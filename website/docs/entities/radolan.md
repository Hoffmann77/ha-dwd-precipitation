---
title: RADOLAN RW and SF
description: Precipitation previous hour, last 24h and yesterday, from DWD's gauge-adjusted radar analyses.
---

RADOLAN is DWD's radar analysis corrected with measurements from its
rain-gauge network. It is slower than the radar nowcast, but closer to what a
gauge on the ground measures. The integration reads two RADOLAN products:

- **RW**, one hour of precipitation, published hourly (and rerun every
  10 minutes).
- **SF**, 24 hours of precipitation, published hourly at :50.

## Sensors

| Sensor | Unit | Window | Arrives |
|--------|------|--------|---------|
| **Precipitation previous hour** | mm | the last full clock hour, e.g. 11:00–12:00 | about 30 minutes after the hour ends (12:28) |
| **Precipitation last 24h** | mm | the 24 hours ending at the last :50 | about 30 minutes after :50 |
| **Precipitation yesterday** | mm | the previous calendar day, German local time | once a day, around 00:20 |

### Precipitation previous hour

Rain that fell in the last full clock hour, corrected with rain-gauge data.
It updates hourly, about 30 minutes after the hour ends: the hour
11:00–12:00 arrives around 12:30. That makes it slower than
[Precipitation last 60 min](radvor-rs.md), but more accurate.

It is a clock hour because it then lines up with Home Assistant's hourly
statistics, and with what "the previous hour" means in an automation. DWD
also reruns its analysis every 10 minutes for the hour ending then; the
integration uses those runs only for
[Timespan without precipitation](dry-streak.md), where they make a reset
show up to an hour sooner.

### Precipitation last 24h

Rain that fell in the past 24 hours, updated hourly. DWD publishes this
analysis only for windows ending at :50, so its window ends 10 minutes before
the one of `Precipitation previous hour`.

### Precipitation yesterday

The total for the previous calendar day, German local time (the 24 hours
ending at 23:50). It updates once a day, around 00:20.

## No data for your location

All three are `unknown` when DWD has no data for your grid cell in that file,
for example during a radar outage, rather than reporting a placeholder value.
The log says so once per outage, and again when data is back. The
[running totals](totals.md) skip those windows.

## Running totals

`Precipitation previous hour` and `Precipitation yesterday` also feed the
two [running totals](totals.md), which are the sensors to use for long-term
statistics.
