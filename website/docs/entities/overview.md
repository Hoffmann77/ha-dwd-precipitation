---
title: Entities
description: Every entity of DWD Precipitation at a glance, and how their names are built.
---

All entities belong to one **DWD Precipitation** device per configured
location, except the [rain warnings](rain-warnings.md), which are a device
each. Their ids start with the name you gave the location: with the name
`Home`, `Precipitation last 60 min` is `sensor.home_precipitation_last_60_min`.

:::note[Installed before 2026.11.0?]

Installs set up before 2026.11.0 keep their old entity ids; only the names
changed. [Upgrading](../help/upgrading.md#renamed-entities) lists the ids they
kept.

:::

## Reading the names

A name states a time window only when the window is part of the value:

| Name | Meaning | Examples |
|------|---------|----------|
| `last <N>` | measured total over the window ending at the latest DWD release | `Precipitation last 60 min`, `Precipitation last 24h` |
| `next <N>` | forecast over a window from now | `Precipitation next 60 min`, `Precipitation next 60–120 min` |
| `previous hour`, `yesterday` | the last complete clock hour or calendar day | `Precipitation previous hour`, `Precipitation yesterday` |
| `now` | the latest 5-minute radar analysis | `Precipitation intensity now`, `Precipitation type now` |

The radar nowcast states its windows in minutes, matching its 5-minute steps:
`next 60–120 min` is the *second* hour ahead. The gauge-adjusted analyses use
hours and days.

"Now" is the latest radar analysis, which covers the five minutes ending at
DWD's release time. By the time the value appears in Home Assistant, that
window ended about 3 to 10 minutes earlier. See
[Release timing](../how-it-works/release-timing.md).

## All entities

| Entity | Entity id | Unit | Updated | Details |
|--------|-----------|------|---------|---------|
| Precipitation last 60 min | `sensor.<name>_precipitation_last_60_min` | mm | 5 min | [RADVOR RS](radvor-rs.md) |
| Precipitation next 60 min | `sensor.<name>_precipitation_next_60_min` | mm | 5 min | [RADVOR RS](radvor-rs.md) |
| Precipitation next 60–120 min | `sensor.<name>_precipitation_next_60_120_min` | mm | 5 min | [RADVOR RS](radvor-rs.md) |
| Precipitation next 120 min | `sensor.<name>_precipitation_next_120_min` | mm | 5 min | [RADVOR RS](radvor-rs.md) |
| Precipitation intensity now | `sensor.<name>_precipitation_intensity_now` | mm/h | 5 min | [RADVOR RV](radvor-rv.md#precipitation-intensity-now) |
| Peak intensity next 60 min | `sensor.<name>_peak_intensity_next_60_min` | mm/h | 5 min | [RADVOR RV](radvor-rv.md#peak-intensities) |
| Peak intensity next 60–120 min | `sensor.<name>_peak_intensity_next_60_120_min` | mm/h | 5 min | [RADVOR RV](radvor-rv.md#peak-intensities) |
| Peak intensity next 120 min | `sensor.<name>_peak_intensity_next_120_min` | mm/h | 5 min | [RADVOR RV](radvor-rv.md#peak-intensities) |
| Peak hourly precipitation next 120 min | `sensor.<name>_peak_hourly_precipitation_next_120_min` | mm | 5 min | [RADVOR RV](radvor-rv.md#peak-hourly-precipitation) |
| Precipitation start | `sensor.<name>_precipitation_start` | time or min | 5 min | [RADVOR RV](radvor-rv.md#precipitation-start-and-end) |
| Precipitation end | `sensor.<name>_precipitation_end` | time or min | 5 min | [RADVOR RV](radvor-rv.md#precipitation-start-and-end) |
| Precipitation expected | `binary_sensor.<name>_precipitation_expected` | on/off | 5 min | [RADVOR RV](radvor-rv.md#precipitation-expected) |
| Precipitation type now | `sensor.<name>_precipitation_type_now` | state | 5 min | [HymecNG](hymecng.md) |
| Precipitation previous hour | `sensor.<name>_precipitation_previous_hour` | mm | hourly | [RADOLAN](radolan.md) |
| Precipitation last 24h | `sensor.<name>_precipitation_last_24h` | mm | hourly | [RADOLAN](radolan.md) |
| Precipitation yesterday | `sensor.<name>_precipitation_yesterday` | mm | daily | [RADOLAN](radolan.md) |
| Precipitation total | `sensor.<name>_precipitation_total` | mm | hourly | [Running totals](totals.md) |
| Precipitation total daily¹ | `sensor.<name>_precipitation_total_daily` | mm | daily | [Running totals](totals.md) |
| Timespan without precipitation | `sensor.<name>_timespan_without_precipitation` | d | 5 or 10 min | [Timespan without precipitation](dry-streak.md) |
| Rain events² | `sensor.<name>_rain_events` | state | 5 min | [Rain events](rain-events.md) |
| Rain warning³ | `binary_sensor.<name>_<warning>_rain_warning` | on/off | 5 min | [Rain warnings](rain-warnings.md) |
| Rain warning status³ | `sensor.<name>_<warning>_rain_warning_status` | state | 5 min | [Rain warnings](rain-warnings.md) |

¹ Disabled by default on installs set up from 2026.11.0 on.
² Only with the *Track rain events* option on.
³ One pair per rain warning you add, on its own device.

## Radar only or gauge-adjusted

- The **RADVOR** (RS, RV) and **HymecNG** values come from radar alone. They
  update every 5 minutes, and the forecasts reach two hours ahead.
- The **RADOLAN** values (`Precipitation previous hour`, `last 24h`,
  `yesterday` and the running totals) are DWD's radar analysis corrected with
  rain-gauge measurements. They arrive about 30 minutes later, but are more
  accurate.

So `Precipitation last 60 min` and `Precipitation previous hour` can differ
even for the same hour. See [The DWD products](../how-it-works/dwd-products.md).

## unknown and unavailable

- **`unknown`**: DWD's file has no value for your location (for example
  during a radar outage), or there is nothing to report, such as
  `Precipitation start` when no rain is forecast.
- **`unavailable`**: the integration has no current file for that product,
  because DWD has not published it in time or it could not be downloaded.

[Availability and staleness](../how-it-works/availability.md) explains both
in detail.
