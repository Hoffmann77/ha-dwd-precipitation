---
title: Introduction
slug: /
description: Radar precipitation measurements and forecasts from the German Weather Service (DWD), for your exact location, in Home Assistant.
---

**DWD Precipitation** is a custom integration for [Home Assistant](https://www.home-assistant.io/)
that brings the precipitation radar of the German Weather Service
(Deutscher Wetterdienst, DWD) to your exact location: how much rain fell, how
much is coming in the next two hours, how hard it is raining, and what is
falling.

:::warning[Germany only]

The integration **only works for locations in Germany** and a narrow band
beyond its borders. The DWD radar composites do not cover other countries.

:::

## Features

- **Location-precise:** every value comes from the radar grid cell of about
  1 km × 1 km that contains your coordinates.
- **Live:** the nowcast sensors refresh every 5 minutes.
- **Two-hour forecast:** forecast totals, peak intensity, the wettest hour
  ahead, and when rain starts and stops.
- **Precipitation type:** rain, drizzle, snow, sleet, graupel, hail, freezing
  rain.
- **Measured totals:** the past hour, the past 24 hours, yesterday, and a
  days-without-rain counter.
- **Long-term totals:** running rain totals for Home Assistant's statistics,
  so daily, weekly, monthly and yearly sums work out of the box.
- **Rain warnings:** your own warnings, such as "Laundry, 60 minutes
  ahead", each an on/off entity for automations, optionally only for rain
  above a minimum.
- **Rain events for blueprints** (optional): each burst of rain followed
  under one id from forecast to measurement, with forecast and measured
  amounts side by side.
- **No account, no API key:** the data comes from
  [DWD Open Data](https://opendata.dwd.de/), which anyone can download.

## The DWD products it reads

The integration reads five DWD products. Each one has its own update
schedule, and the entities are grouped by product in these docs.

| Product | What it is | Updated | Entities |
|---------|------------|---------|----------|
| **RADVOR RS** | Radar nowcast: rolling 60-minute totals, measured and forecast | every 5 min | [Precipitation last / next 60 min, …](entities/radvor-rs.md) |
| **RADVOR RV** | Radar nowcast in 5-minute steps, two hours ahead | every 5 min | [Intensity, peaks, start and end, …](entities/radvor-rv.md) |
| **HymecNG** | Precipitation type classified from radar | every 5 min | [Precipitation type now](entities/hymecng.md) |
| **RADOLAN RW** | Radar analysis of one hour, corrected with rain gauges | hourly | [Precipitation previous hour, Precipitation total](entities/radolan.md) |
| **RADOLAN SF** | Radar analysis of 24 hours, corrected with rain gauges | hourly / daily | [Precipitation last 24h, yesterday](entities/radolan.md) |

The RADVOR and HymecNG values come from radar alone and are fast. The RADOLAN
values are corrected with rain-gauge measurements: they arrive about
30 minutes later, but are more accurate. [The DWD products](how-it-works/dwd-products.md)
explains the difference.

## Where to go next

- [Install the integration](getting-started/installation.md), then
  [set it up and pick your options](getting-started/configuration.md).
- [Entities](entities/overview.md) lists every sensor, with its unit and
  update interval.
- Something looks wrong? See [Troubleshooting](help/troubleshooting.md) and
  the [FAQ](help/faq.md).
- Upgrading from a version before 2026.11.0? [Upgrading](help/upgrading.md)
  lists what changed, including renamed entities.

:::info

This is a community project. It is not affiliated with or endorsed by the
Deutscher Wetterdienst. All data is © DWD and used under the
[DWD Open Data terms of use](https://www.dwd.de/EN/service/legal_notice/legal_notice_node.html).

:::
