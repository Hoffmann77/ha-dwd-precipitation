---
title: RADVOR RS nowcast
description: Precipitation last 60 min, next 60 min, next 60–120 min and next 120 min.
---

RADVOR RS is DWD's radar nowcast of hourly totals. Every 5 minutes DWD
publishes a set of rolling 60-minute totals: the hour that has just been
measured, and forecasts for the hours ahead. The integration reads three of
them and exposes four sensors.

All four are totals in millimetres, not rates. For how hard it is raining,
see [Precipitation intensity now](radvor-rv.md#precipitation-intensity-now).

## Sensors

| Sensor | Unit | Window, for a release at 14:00 |
|--------|------|--------------------------------|
| **Precipitation last 60 min** | mm | 13:00–14:00, measured |
| **Precipitation next 60 min** | mm | 14:00–15:00, forecast |
| **Precipitation next 60–120 min** | mm | 15:00–16:00, forecast |
| **Precipitation next 120 min** | mm | 14:00–16:00, forecast |

The windows are counted from DWD's release time, which is a multiple of
5 minutes. The release of 14:00 reaches Home Assistant at about 14:04 to
14:05, so "next 60 min" then covers roughly the next 55 minutes.

### Precipitation last 60 min

Rain that fell in the past 60 minutes, from radar alone, updated every
5 minutes. Because the hour rolls on in 5-minute steps, a short shower stays
in it for a full hour after it has passed.

For the gauge-adjusted total of a clock hour, see
[Precipitation previous hour](radolan.md); it arrives later, but is more
accurate.

### Precipitation next 60 min

The forecast total for the next hour.

### Precipitation next 60–120 min

The forecast total for the second hour ahead.

### Precipitation next 120 min

The forecast total for the whole next two hours: exactly
`Precipitation next 60 min` plus `Precipitation next 60–120 min`, so there
is no need to add the two in a template. It is `unknown` if either of them
is, since half a forecast is not a two-hour total.

## Related sensors

- [Peak hourly precipitation next 120 min](radvor-rv.md#peak-hourly-precipitation)
  finds the wettest hour *anywhere* in the next two hours. A downpour that
  straddles the one-hour mark shows there in full, where
  `Precipitation next 60 min` and `next 60–120 min` each only see part of it.
- [Timespan without precipitation](dry-streak.md) can count
  `Precipitation last 60 min` as its source.

## Good to know

- **Radar only.** RS is not corrected with rain gauges, so it can differ from
  a gauge on the ground, and from the [RADOLAN](radolan.md) sensors.
- **No data:** a sensor is `unknown` when DWD's file has no value for your
  location, for example while a nearby radar is out of service. The log says
  so once, and again when data is back.
- **Data volume:** DWD publishes all 25 rolling hours in one archive of up to
  about 17 MB. The integration downloads only the three hours it needs, about a
  fifth of the file.
