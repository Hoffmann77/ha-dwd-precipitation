

# DWD Precipitation

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/Hoffmann77/ha-dwd-precipitation)](https://github.com/Hoffmann77/ha-dwd-precipitation/releases/latest)
[![GitHub Downloads](https://img.shields.io/github/downloads/Hoffmann77/ha-dwd-precipitation/total)](https://github.com/Hoffmann77/ha-dwd-precipitation/releases)
[![Tests](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml)
[![HACS Validate](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml)

Radar-based precipitation measurements and forecasts from the German Weather Service (DWD), for your exact location, directly in Home Assistant.

> [!IMPORTANT]
> This integration **only works** for locations **within Germany** and areas immediately adjacent to the German border.
> The DWD radar composites do not cover other countries.

## Features

- **Location-precise:** values come from the ~1 km radar grid cell containing your coordinates
- **Live:** the nowcast sensors refresh every 5 minutes
- **Two-hour forecast:** forecast totals, peak intensity, and when rain starts and stops
- **Precipitation type:** rain, drizzle, snow, sleet, graupel, hail, freezing rain
- **Measured totals:** past hour, past 24 hours, yesterday, and a days-without-rain counter
- **Customizable thresholds** for rain events to use as input for automations.

## Entities

All entities belong to one **DWD Precipitation** device per configured location.

Names ending in **`last <N>`** are measured totals over the window ending now.

Names ending in **`next <N>`** are forecasts. 

> [!NOTE]
> **`next 1–2h`** is the *second* hour ahead (60–120 min), not the coming two hours.

**RADVOR RS: radar nowcast · updated every 5 min**

- **Precipitation now** (mm): rain that fell in the past 60 minutes. This is a total, not a mm/h rate.
- **Precipitation next 1h** (mm): forecast total for the next 0–60 min
- **Precipitation next 1–2h** (mm): forecast total for 60–120 min from now
- **Timespan without precipitation** (days): time since `Precipitation now` last reached the reset threshold.

**RADVOR RV: nowcast in 5-min steps · updated every 5 min**

- **Peak intensity next 1h** (mm/h): heaviest expected rain rate in the next 0–60 min
- **Peak intensity next 1–2h** (mm/h): the same for 60–120 min
- **Precipitation start** (time or min): when rain begins; `unknown` if none within 2 h
- **Precipitation end** (time or min): when rain stops; `unknown` if it lasts beyond 2 h
- **Precipitation expected** (binary sensor): `on` if rain is forecast within 2 h

**HymecNG: precipitation type · updated every 5 min**

- **Precipitation type**: what is falling right now: rain, drizzle, snow, sleet, graupel, hail, freezing rain, …

**RADOLAN RW / SF: radar + rain-gauge analysis · updated hourly / daily**

- **Precipitation last 1h** (mm): past 60 min. Arrives once an hour but is more accurate than `Precipitation now`.
- **Precipitation last 24h** (mm): rolling past 24 hours
- **Precipitation yesterday** (mm): the previous calendar day's total, available around 00:20 local time

See [Entity details](#entity-details) for the full behaviour of each sensor and its attributes.

## Screenshots

<img src="https://raw.githubusercontent.com/Hoffmann77/ha-dwd-precipitation/main/docs/assets/screenshot_config_flow.png" alt="Setup dialog — name field and location selector map." height="400"/>

<img src="https://raw.githubusercontent.com/Hoffmann77/ha-dwd-precipitation/main/docs/assets/screenshot_entities_2026-8-0.png" alt="Device page — the precipitation sensors and their current values." height="400"/>

## Installation

### Install using HACS (recommended)

If you do not have HACS installed yet, visit https://hacs.xyz for installation instructions.

To add this repository to HACS in your Home Assistant instance, use this button:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=Integration)

After installation, restart Home Assistant. To add DWD Precipitation to your Home Assistant instance, use this button:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dwd_precipitation)

<details>
<summary>Manual installation steps</summary>

### Semi-manual installation with HACS
1. Go to the HACS integrations section.
2. Click the 3 dots in the top right corner.
3. Select "Custom repositories".
4. Add the URL (https://github.com/hoffmann77/ha-dwd-precipitation) of the repository.
5. Select the integration category.
6. Click the "ADD" button.
7. Now you are able to download the integration.

### Manual installation
1. Download the ZIP file of this repository and extract its contents.
2. Copy the `dwd_precipitation` folder into `/config/custom_components/` in your Home Assistant directory.

### Restart Home Assistant
1. Restart your Home Assistant.

### Add the integration
1. Navigate to **Settings > Devices & Services**.
2. Click **Add Integration** and search for "DWD Precipitation".
3. Select the DWD Precipitation integration to start setup.

</details>

## Configuration

### Setup

- **Name**: used for the device and as the prefix of every entity id. Defaults to your Home Assistant location name.
- **Location**: the point to report precipitation for. Defaults to your Home Assistant home location; locations outside the radar coverage are rejected.

### Options

Open **Settings > Devices & Services > DWD Precipitation > Configure**. None of the options affect how often data is fetched.

- **Add technical details to each sensor:**(default: off): adds the source attributes listed under [Attributes](#attributes).
- **Show sensors as unavailable when the data is out of date** (default: on): if DWD does not publish a new file in time, sensors report `unavailable` instead of keeping the last value. See [Troubleshooting](#troubleshooting) for how long "in time" is. The missing file keeps being retried either way.
- **Rain detection threshold (mm per hour)** (default: 0): how much forecast rain counts as rain for `Precipitation start`, `Precipitation end` and `Precipitation expected`. 0 means any amount DWD detects; around 0.5 ignores drizzle.
- **How "Precipitation start" and "Precipitation end" report** (default: clock time): show a clock time or the minutes until the event. The other form is always available as an attribute.
- **When "Precipitation end" counts rain as over** (default: first dry gap): see `Precipitation end` below.
- **Rain needed to reset the dry-streak counter (mm)** (default: 1.0): `Precipitation now` at or above this value resets `Timespan without precipitation`.

## Entity details

For the full two-hour forecast total, add `Precipitation next 1h` and `Precipitation next 1–2h`.

### RADVOR RS: radar nowcast · every 5 min

- **Precipitation now** (mm): rain that fell in the past 60 minutes. This is a total, not a mm/h rate. It covers the same window as `Precipitation last 1h` but updates every 5 minutes (radar only).
- **Precipitation next 1h** (mm): forecast total for the next 0–60 min.
- **Precipitation next 1–2h** (mm): forecast total for 60–120 min from now.
- **Timespan without precipitation** (days): time since `Precipitation now` last reached the reset threshold. Survives restarts; rain during downtime is caught up from the RADOLAN totals on startup.

### RADVOR RV: nowcast in 5-min steps · every 5 min · 2 h horizon

- **Peak intensity next 1h** (mm/h): heaviest expected rain rate in the next 0–60 min. Tells drizzle from a downpour; `Precipitation next 1h` gives the amount.
- **Peak intensity next 1–2h** (mm/h): the same for 60–120 min from now.
- **Precipitation start** (time or min): when rain begins. Now / `0` if it is already raining, `unknown` if none is forecast within 2 h.
- **Precipitation end** (time or min): when rain stops. `unknown` if it continues beyond 2 h, which means "still raining in 2 hours", not "never".
  - *First dry gap*: end of the current burst. Moves around during showers.
  - *Precipitation clears within 2 h*: when no more rain is forecast within the horizon. Steadier, but stays `unknown` longer.
- **Precipitation expected** (binary sensor): `on` if rain is forecast within the next 2 h.

### HymecNG: precipitation type · every 5 min

- **Precipitation type**: what is falling right now. One of `no_precipitation`, `not_classified`, `drizzle`, `rain`, `freezing_drizzle`, `freezing_rain`, `sleet`, `snow`, `graupel`, `hail`, `large_hail`.

### RADOLAN RW / SF: radar + rain-gauge analysis · hourly / daily

- **Precipitation last 1h** (mm): rain that fell in the past 60 minutes. Arrives once an hour, but is more accurate than `Precipitation now`.
- **Precipitation last 24h** (mm): rain that fell in the rolling past 24 hours. Updated hourly.
- **Precipitation yesterday** (mm): total for the previous calendar day. Updated once a day, around 00:20 German local time.

### Attributes

Always present:

| Attribute | Entities | Description |
|-----------|----------|-------------|
| `minutes_until` / `at` | `Precipitation start`, `Precipitation end`, `Precipitation expected` | The form *not* shown as the state: whole minutes until the event, or its ISO-8601 UTC time. The binary sensor carries both, pointing at the forecast start (`null` when no rain is expected) |
| `forecast_5min` | `Precipitation expected` | The full 25-point RV forecast (0–120 min in 5-minute steps); each point has `lead`, `start`, `end`, `value` (mm) and `intensity` (mm/h). Not recorded in history |
| `hours_without_precipitation` | `Timespan without precipitation` | The dry streak in hours; `null` until the counter has started |
| `dry_since` | `Timespan without precipitation` | ISO-8601 UTC time of the rain that last reset the counter |

With **Add technical details to each sensor** enabled, every DWD sensor also has:

| Attribute | Description |
|-----------|-------------|
| `source_product` | DWD product identifier from the file header (e.g. `"RADVOR-RS"`, `"RW"`) |
| `source_timestamp` | UTC reference time of the DWD file. For RADVOR, the analysis time before the forecast lead; for RADOLAN, the end of the measurement window |
| `lead_time_minutes` | Forecast lead in minutes (`0`, `60` or `120` for RADVOR; `null` for RADOLAN) |
| `data_start` / `data_end` | ISO-8601 UTC start and end of the period the value covers; `null` for values without a period |

## Troubleshooting

**A sensor is briefly `unavailable`, or the log says a DWD file was not found.** DWD often publishes a few minutes late. The integration retries automatically, starting after 60 seconds and backing off to at most 5 minutes (15 minutes for `Precipitation yesterday`). A sensor only turns `unavailable` once its next file is more than 6 minutes overdue (30 minutes for `Precipitation yesterday`), and recovers on the next successful fetch. Your configuration is not at fault.

**Sensors stay `unavailable` after setup.** Check the Home Assistant log for errors and verify that `opendata.dwd.de` is reachable from your network. If only some sensors are affected, the other DWD products keep working independently.

**`Precipitation type` shows `unknown`.** The location is outside the HymecNG radar coverage.

**Old values persist after a DWD outage.** *Show sensors as unavailable when the data is out of date* is turned off, so the last value is kept. Turn it on to have sensors report `unavailable` instead.

## Data source

All data is derived from the **DWD (Deutscher Wetterdienst)**:

<img src="docs/assets/dwd-logo.png" alt="Deutscher Wetterdienst Logo" width="200"/>

## License

This integration is only possible thanks to the great work done by the contributors of the **[wradlib](https://github.com/wradlib/wradlib)** package.

All files in `custom_components/dwd_precipitation/radar/` are licensed under the [wradlib license](custom_components/dwd_precipitation/radar/LICENSE.txt) (MIT).
