---
title: Upgrading
description: What changes when you upgrade DWD Precipitation, including the entities renamed in 2026.11.0.
---

Every release is described in the
[release notes on GitHub](https://github.com/Hoffmann77/ha-dwd-precipitation/releases).
This page covers the changes that need your attention, or that you might
otherwise notice as a surprise.

## 2026.11.0

### Renamed entities

Entity names now state the window they cover in a consistent way (see
[Reading the names](../entities/overview.md#reading-the-names)). Installs set
up before 2026.11.0 keep their entity ids; only the names changed, so your
automations, scripts and dashboards keep working. New installs get the new
ids:

| New name | Id on installs from before 2026.11.0 | Id on new installs |
|----------|--------------------------------------|--------------------|
| Precipitation last 60 min | `sensor.<name>_precipitation_now` | `sensor.<name>_precipitation_last_60_min` |
| Precipitation next 60 min | `sensor.<name>_precipitation_next_1h` | `sensor.<name>_precipitation_next_60_min` |
| Precipitation next 60–120 min | `sensor.<name>_precipitation_next_1_2h` | `sensor.<name>_precipitation_next_60_120_min` |
| Peak hourly precipitation next 120 min | `sensor.<name>_peak_hourly_precipitation_next_2h` | `sensor.<name>_peak_hourly_precipitation_next_120_min` |
| Peak intensity next 60 min | `sensor.<name>_peak_intensity_next_1h` | `sensor.<name>_peak_intensity_next_60_min` |
| Peak intensity next 60–120 min | `sensor.<name>_peak_intensity_next_1_2h` | `sensor.<name>_peak_intensity_next_60_120_min` |
| Precipitation type now | `sensor.<name>_precipitation_type` | `sensor.<name>_precipitation_type_now` |
| Precipitation previous hour | `sensor.<name>_precipitation_last_1h` | `sensor.<name>_precipitation_previous_hour` |
| Precipitation total | `sensor.<name>_precipitation_total_hourly` | `sensor.<name>_precipitation_total` |

All other entities kept both their names and their ids.

If you want the new ids on an older install, rename the entities in their
settings (or use **Recreate entity IDs** on the device page) and update your
automations, scripts and dashboards to match. No new id is one that an older
version gave another entity, so nothing clashes.

### New entities

- **Precipitation intensity now** (mm/h): the current rain rate. See
  [RADVOR RV](../entities/radvor-rv.md#precipitation-intensity-now).
- **Precipitation next 120 min** (mm): the whole two-hour forecast total. See
  [RADVOR RS](../entities/radvor-rs.md#precipitation-next-120-min).
- **Peak intensity next 120 min** (mm/h): the heaviest rate in the next two
  hours. See [RADVOR RV](../entities/radvor-rv.md#peak-intensities).
- **Rain events**, opt-in with the advanced option *Track rain events*. See
  [Rain events](../entities/rain-events.md).

### Precipitation previous hour is a clock hour

`Precipitation previous hour` (formerly *Precipitation last 1h*) used to be
the hour ending at :50. It is now the last full clock hour, such as
11:00–12:00, which lines up with Home Assistant's hourly statistics. It
arrives about 28 minutes after the hour.

`Precipitation total` moves to clock hours with it. A total carried over
from an older version moves on its first update and leaves the 10 minutes in
between out once, rather than counting 50 minutes twice. See
[ADR 0002](/development/adr/0002-rw-reads-the-clock-hour).

### Timespan without precipitation: choice of source

The new option *Product that resets the dry-streak counter* chooses between
DWD's gauge-adjusted hour (RW) and `Precipitation last 60 min` (RS). New
installs use RW; **existing installs keep RS**, so upgrading changes nothing.
Switch in the options if you prefer RW; the counter keeps its value. See
[Timespan without precipitation](../entities/dry-streak.md).

### Precipitation total daily disabled on new installs

`Precipitation total daily` counts each day's rain on the following day in
the statistics, so new installs get it disabled; `Precipitation total` is the
one to use. **Installs that already had it keep it enabled.** See
[Running totals](../entities/totals.md#precipitation-total-daily).
