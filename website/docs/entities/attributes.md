---
title: Attributes
description: The attributes of the DWD Precipitation entities, and the technical details option.
---

## Always present

| Attribute | Entities | Description |
|-----------|----------|-------------|
| `minutes_until` / `at` | `Precipitation start`, `Precipitation end`, `Precipitation expected` | The form *not* shown as the state: whole minutes until the event, or its ISO-8601 UTC time. The binary sensor carries both, pointing at the forecast start (`null` when no rain is expected) |
| `forecast_5min` | `Precipitation expected` | The full 25-step RV forecast (0 to 120 min in 5-minute steps); each step has `lead` (minutes from the release time), `start`, `end`, `value` (mm in those 5 minutes) and `intensity` (mm/h). `value` and `intensity` are `null` for a step without data |
| `window_start` / `window_end` | `Precipitation intensity now` | Start and end of the 5-minute radar analysis the rate comes from |
| `amount_5min` | `Precipitation intensity now` | The rain in that window in mm, before it is scaled to mm/h; `null` without data |
| `window_start` / `window_end` | `Peak hourly precipitation next 120 min` | Start and end of the wettest hour; `null` when no rain is forecast. If two windows tie, the earlier one |
| `forecast_rolling_1h` | `Peak hourly precipitation next 120 min` | The hourly series the sensor picks its value from, see [the rolling-hour series](radvor-rv.md#the-rolling-hour-series) |
| `hours_without_precipitation` | `Timespan without precipitation` | The dry streak in hours; `null` until the counter has started |
| `dry_since` | `Timespan without precipitation` | The time the counter counts from: the end of the hour that last reset it, or on a new install the start of the dry period DWD's data shows |
| `counted_until` | `Precipitation total`, `Precipitation total daily` | End of the newest DWD window included in the total; `null` until the first file arrives. Missed files fetched later are added without moving it back |
| `schema`, `events`, `steps`, … | `Rain events` | The rain around your location split into events, see [Rain events](rain-events.md#attributes) |
| `event_id`, `start`, `mm`, `peak_1h`, `peak_10min`, `type` | `Rain warning status` | The rain event the warning is about; all `null` while dry, see [Rain warnings](rain-warnings.md#attributes) |

Times are ISO-8601 in UTC, for example `2026-10-12T14:30:00+00:00`;
templates turn them into local time with `as_local(as_datetime(...))`.

## Not recorded in history

Some attributes are large and change every 5 minutes, so Home Assistant's
recorder leaves them out of the history database: `forecast_5min`,
`forecast_rolling_1h`, `window_start` / `window_end`, and every attribute of
`Rain events` and `Rain warning status`. They are always available on the current state, so templates,
automations and blueprints can read them; only the history graph does not
keep them.

## Technical details

With the option
[*Add technical details to each sensor*](../getting-started/configuration.md#technical-details)
on, every DWD sensor except `Precipitation expected`, the two running totals,
`Timespan without precipitation`, `Rain events` and the rain warnings also
has:

| Attribute | Description |
|-----------|-------------|
| `source_product` | DWD product identifier from the file header (e.g. `"RS_top_view"`, `"RV"`, `"RW"`) |
| `source_timestamp` | UTC reference time of the DWD file. For RADVOR, the analysis time before the forecast lead; for RADOLAN, the end of the measurement window |
| `lead_time_minutes` | Forecast lead in minutes: `0`, `60` or `120` for RADVOR, the end of the wettest hour for `Peak hourly precipitation next 120 min` (`null` there when no rain is forecast), `null` for `Precipitation start` and `end`, HymecNG and RADOLAN |
| `data_start` / `data_end` | Start and end of the period the value covers, ISO-8601 UTC (for `Peak hourly precipitation next 120 min`, the wettest hour, the same as `window_start` / `window_end`); omitted for values without a period |

They are useful in templates and when reporting a problem, since they say
exactly which DWD file a value came from.
