<p align="center">
  <img src="assets/dwd-logo.png" alt="DWD Precipitation" width="200"/>
</p>

# DWD Precipitation

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/Hoffmann77/ha-dwd-precipitation)](https://github.com/Hoffmann77/ha-dwd-precipitation/releases/latest)
[![GitHub Downloads](https://img.shields.io/github/downloads/Hoffmann77/ha-dwd-precipitation/total)](https://github.com/Hoffmann77/ha-dwd-precipitation/releases)
[![Tests](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml)
[![HACS Validate](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml)

Radar-based precipitation forecasts and data from the German Weather Service (DWD).

Real-time location based precipitation analysis, forecasts, and historical accumulations — directly in Home Assistant.

## Features

- 5-minute precipitation nowcast and 1-hour / 2-hour radar forecasts from **RADVOR RS**
- Hourly and 24-hour precipitation accumulations from **RADOLAN RW/SF** (radar + weather station blend)
- Yesterday's 24-hour total updated once daily — ideal for irrigation or energy automations
- Per-location extraction: the nearest radar grid cell to your exact latitude/longitude
- Staleness guard: sensors can report `unavailable` when DWD data is stale, preventing automations from acting on outdated values
- Lightweight: only `numpy` and `h5py` required — no wradlib or heavy GIS dependencies

## Screenshots

<!-- TODO: add screenshot at docs/screenshots/config_flow.png -->
*Setup dialog — name field and location selector map.*

<!-- TODO: add screenshot at docs/screenshots/entities.png -->
*Device page — the six precipitation sensors and their current values.*

## Prerequisites

> [!IMPORTANT]
> This integration only works for locations **within Germany** and areas immediately adjacent to the German border. The DWD radar composites do not cover other countries.

- Home Assistant 2024.1 or later
- No API key or DWD account required
- Internet access from your HA instance to [opendata.dwd.de](https://opendata.dwd.de)

## Installation

### HACS (recommended)

[HACS](https://hacs.xyz) must be installed in your Home Assistant instance. Then click the button below to add this repository as a custom integration:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=Integration)

After the download completes, restart Home Assistant. Then click the button below to set up the integration:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dwd_precipitation)

### Manual Installation

1. Download the [latest release](https://github.com/Hoffmann77/ha-dwd-precipitation/releases/latest) ZIP and extract it.
2. Copy the `dwd_precipitation` folder into `config/custom_components/` in your Home Assistant directory.
3. Restart Home Assistant.
4. Navigate to **Settings > Devices & Services > Add Integration** and search for "DWD Precipitation".

## Configuration

### Setup

When adding the integration, you are prompted for:

| Field | Description |
|-------|-------------|
| **Name** | A label for this integration instance (defaults to your HA location name) |
| **Location** | Latitude/longitude map picker — defaults to your HA home location |

### Options

After setup, open the integration's **Configure** dialog (**Settings > Devices & Services > DWD Precipitation > Configure**) to adjust:

| Option | Default | Description |
|--------|---------|-------------|
| Enable diagnostic state attributes | Off | Adds per-sensor metadata attributes (see below) |
| Mark sensors unavailable when data is stale | On | Sensors become `unavailable` once cached data exceeds the product's release interval; prevents automations from acting on stale values |

When diagnostic state attributes are enabled, each sensor exposes:

| Attribute | Description |
|-----------|-------------|
| `source_product` | DWD internal product identifier read from the file header (e.g. `"RADVOR-RS"`, `"RW"`) |
| `source_timestamp` | UTC ISO-8601 reference time of the DWD product — for RADVOR forecasts this is the analysis time before the lead offset; for RADOLAN products it is the end of the measurement window |
| `lead_time_minutes` | Forecast lead time in minutes (`0` for the nowcast, `60` or `120` for RADVOR forecasts, `null` for RADOLAN products which have no lead time) |
| `data_start` | ISO-8601 UTC start of the accumulation window (e.g. T−60 min for "last hour"); `null` for products without an accumulation window |
| `data_end` | ISO-8601 UTC end of the accumulation window; for RADOLAN products this equals `source_timestamp` |

## Entities

All sensors belong to a single **DWD Precipitation** device per configured location.

| Entity | Data source | Unit | Update interval | Description |
|--------|-------------|------|-----------------|-------------|
| `Precipitation now` | RADVOR RS | mm | 5 min | Calibrated radar analysis for the current 5-minute window |
| `Precipitation +1 hour` | RADVOR RS | mm | 5 min | Calibrated radar forecast for the next 0–60 minutes |
| `Precipitation +2 hours` | RADVOR RS | mm | 5 min | Calibrated radar forecast for the 60–120 minute window |
| `Precipitation last hour` | RADOLAN RW | mm | 1 h | Radar + station-blended analysis for the past hour |
| `Precipitation last 24 hours` | RADOLAN SF | mm | 1 h | Radar + station-blended total for the rolling past 24 hours |
| `Precipitation yesterday` | RADOLAN SF | mm | Daily (~00:18 UTC+1) | Previous calendar day's 24-hour accumulated total |

All data is served from [DWD OpenData](https://opendata.dwd.de) (no account required):

- **[RADVOR RS](https://www.dwd.de/EN/ourservices/radvor/radvor.html)** — Real-time radar nowcast with 0 / 60 / 120-minute lead times, updated every 5 minutes.
- **[RADOLAN RW/SF](https://www.dwd.de/DE/leistungen/radolan/radolan.html)** — Hourly and 24-hour precipitation analyses blending radar and surface station data.

## Troubleshooting

**Sensors show `unavailable` immediately after setup** — the integration fetches data on startup; if DWD OpenData is temporarily unreachable the first refresh fails. Check your HA logs for HTTP errors and verify that `opendata.dwd.de` is reachable from your network.

**Sensors always show `unavailable`** — confirm that your configured coordinates are within Germany. Coordinates outside the radar composite coverage area produce a `NaN` from the grid lookup, which surfaces as `unavailable`.

**`extra_state_attributes` are not appearing** — enable the option in **Settings > Devices & Services > DWD Precipitation > Configure**.

**Old values persist after a DWD outage** — if *Mark sensors unavailable when data is stale* is disabled, the last cached value is kept indefinitely. Enable the option so that sensors go `unavailable` once the staleness window expires.

## Contributing & Support

Bug reports and feature requests go to the [GitHub issue tracker](https://github.com/Hoffmann77/ha-dwd-precipitation/issues). Please include your HA version, integration version, and relevant log output.

Pull requests are welcome. Please open an issue first to discuss the change. When adding a new DWD product, follow the pattern documented in [`CLAUDE.md`](CLAUDE.md).

## License

This integration is made possible by the radar parsing code extracted from **[wradlib](https://github.com/wradlib/wradlib)**. All files in `custom_components/dwd_precipitation/radar/` are licensed under the [wradlib license](custom_components/dwd_precipitation/radar/LICENSE.txt) (MIT).
