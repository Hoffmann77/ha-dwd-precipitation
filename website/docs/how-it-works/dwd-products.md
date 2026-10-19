---
title: The DWD products
description: What RADVOR RS and RV, HymecNG and RADOLAN RW and SF are, and how they differ.
---

The German Weather Service runs a network of weather radars and combines
their scans into nationwide composites every 5 minutes. It also corrects radar
estimates with measurements from its rain-gauge network. Several of these
products are published on [DWD Open Data](https://opendata.dwd.de/), free of
charge and without registration. The integration reads five of them.

## Radar only: RADVOR and HymecNG

**RADVOR** is DWD's radar-based nowcast. It takes the latest radar
composite, tracks how the precipitation moves, and extrapolates it up to two
hours ahead. Every 5 minutes it publishes two products the integration reads:

- **RS**: 25 rolling 60-minute totals, from the hour just measured to the
  hour ending two hours ahead. Behind
  [Precipitation last 60 min and the next-hour forecasts](../entities/radvor-rs.md).
- **RV**: 25 steps of 5 minutes, the latest measured one and 24 forecast
  steps. Behind [intensity, peaks, start and end](../entities/radvor-rv.md).

RS's hours are the sums of RV's 5-minute steps, in almost every cell exactly.

**HymecNG** is DWD's hydrometeor classification: every 5 minutes it
determines from the radar measurements what type of precipitation is falling,
such as rain, drizzle, snow or hail. Behind [Precipitation type now](../entities/hymecng.md).

Radar-only values are fast and finely resolved, but a radar measures in the
air above the ground, from the strength of the echo. Its estimate can differ
from what a gauge on the ground collects, in either direction.

## Gauge-adjusted: RADOLAN

**RADOLAN** combines the radar composite with the measurements of DWD's
rain gauges, so the radar's spatial detail is adjusted to the amounts actually
measured on the ground. That takes the gauge reports, so RADOLAN is published
about half an hour after its window ends. The integration reads:

- **RW**: one hour of precipitation. DWD computes it every 10 minutes for the
  hour ending then; the integration uses the runs ending on the full hour.
  Behind [Precipitation previous hour](../entities/radolan.md) and
  [Precipitation total](../entities/totals.md).
- **SF**: 24 hours of precipitation, for windows ending at :50. Behind
  [Precipitation last 24h and yesterday](../entities/radolan.md).

## The grid

All five products are on the same grid, DWD's "DE1200": 1100 × 1200 cells
of 1 km × 1 km covering Germany and a band around it. The integration reads
the single cell that contains your location; see
[Grid cell lookup](grid-lookup.md).

## Files and data volume

| Product | Published as | Read |
|---------|--------------|------|
| RS | one archive of 25 HDF5 files every 5 min, under 1 MB to about 17 MB | the three hours it needs, by HTTP range requests (about a fifth of the archive) |
| RV | one archive of 25 HDF5 files every 5 min, under 1 MB to about 17 MB | the whole archive |
| HymecNG | one HDF5 file every 5 min | the whole file |
| RW, SF | one small HDF5 file per run | the whole file |

The radar files are decoded on your Home Assistant machine, outside its event
loop, so even a Raspberry Pi stays responsive. No other service is involved:
the integration talks to `opendata.dwd.de` only.

## Terms of use

The data is © Deutscher Wetterdienst and used under the
[DWD Open Data terms of use](https://www.dwd.de/EN/service/legal_notice/legal_notice_node.html).
DWD publishes the
[current status of its radar stations](https://www.dwd.de/DE/leistungen/radarniederschlag/rn_info/home_freie_radarstatus_kartendaten.html),
which explains most gaps in the data.
