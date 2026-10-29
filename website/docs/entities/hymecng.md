---
title: Precipitation type (HymecNG)
description: Precipitation type now, from DWD's HymecNG radar classification.
---

HymecNG is DWD's classification of what is falling, derived from radar every
5 minutes. The integration reads the class of your grid cell. With
[Rain events](rain-events.md#precipitation-type) on, it also gives each
measured step of a rain event its type.

## Precipitation type now

**Precipitation type now** is an enum sensor: what is falling right now, from
the latest 5-minute analysis, like
[Precipitation intensity now](radvor-rv.md#precipitation-intensity-now).

| State | Shown as |
|-------|----------|
| `no_precipitation` | No precipitation |
| `not_classified` | Not classified |
| `drizzle` | Drizzle |
| `rain` | Rain |
| `freezing_drizzle` | Freezing drizzle |
| `freezing_rain` | Freezing rain |
| `sleet` | Sleet |
| `snow` | Snow |
| `graupel` | Graupel |
| `hail` | Hail |
| `large_hail` | Large hail |

Automations and templates use the state on the left; the dashboard shows the
translated label on the right.

## No precipitation or unknown

DWD's file tells two situations apart, and so does the sensor:

- **`no_precipitation`**: the radar scanned your location and saw no echo.
  It is dry.
- **`unknown`**: the file has no data for your location: a radar has dropped
  out of DWD's composite, or the location is outside the area HymecNG
  covers. The log says which, once.

## Example

Notify when freezing rain is classified at home:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.home_precipitation_type_now
    to:
      - freezing_drizzle
      - freezing_rain
actions:
  - action: notify.notify
    data:
      message: "Freezing rain at home: watch out for black ice."
```
