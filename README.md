

# DWD Precipitation

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/Hoffmann77/ha-dwd-precipitation)](https://github.com/Hoffmann77/ha-dwd-precipitation/releases/latest)
[![Tests](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml)
[![HACS Validate](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml)

Radar-based precipitation measurements and forecasts from the German Weather Service (DWD), for your exact location, directly in Home Assistant.

> [!IMPORTANT]
> This integration **only works** for locations **within Germany** and areas immediately adjacent to the German border.
> The DWD radar composites do not cover other countries.

**[Read the documentation](https://hoffmann77.github.io/ha-dwd-precipitation/)** ([Deutsch](https://hoffmann77.github.io/ha-dwd-precipitation/de/)) for every sensor, the options, how it works, and troubleshooting.

## Features

- **Location-precise:** values come from the ~1 km radar grid cell containing your coordinates
- **Live:** the nowcast sensors refresh every 5 minutes
- **Two-hour forecast:** forecast totals, peak intensity, the wettest hour ahead, and when rain starts and stops
- **Precipitation type:** rain, drizzle, snow, sleet, graupel, hail, freezing rain
- **Measured totals:** past hour, past 24 hours, yesterday, and a days-without-rain counter
- **Long-term totals:** running rain totals for Home Assistant's statistics, so weekly, monthly and yearly sums work out of the box
- **Rain events for blueprints** (optional): each burst of rain followed under one id from forecast to measurement, with forecast and measured amounts side by side
- **Customizable thresholds** for rain events to use as input for automations.

## Entities

All entities belong to one **DWD Precipitation** device per configured location:

- **Radar nowcast, every 5 minutes:** Precipitation last 60 min, next 60 min, next 60–120 min and next 120 min; Precipitation intensity now; Peak intensity next 60 min, next 60–120 min and next 120 min; Peak hourly precipitation next 120 min; Precipitation start and end; Precipitation expected; Precipitation type now
- **Gauge-adjusted analyses, hourly and daily:** Precipitation previous hour, last 24h and yesterday
- **For statistics:** Precipitation total and Precipitation total daily
- **Timespan without precipitation**, and the optional **Rain events** sensor for blueprints

The [entity overview](https://hoffmann77.github.io/ha-dwd-precipitation/entities/overview) lists every entity with its id, unit and update interval.

> [!NOTE]
> Upgrading from a version before 2026.11.0? Several entities were renamed, and existing installs keep their old entity ids. See [Upgrading](https://hoffmann77.github.io/ha-dwd-precipitation/help/upgrading).

## Screenshots

<img src="https://raw.githubusercontent.com/Hoffmann77/ha-dwd-precipitation/main/docs/assets/screenshot_config_flow.png" alt="Setup dialog — name field and location selector map." height="400"/>

<img src="https://raw.githubusercontent.com/Hoffmann77/ha-dwd-precipitation/main/docs/assets/screenshot_entities_2026-8-0.png" alt="Device page — the precipitation sensors and their current values." height="400"/>

## Installation

If you do not have HACS installed yet, visit https://hacs.xyz for installation instructions.

To add this repository to HACS in your Home Assistant instance, use this button:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=Integration)

After installation, restart Home Assistant. To add DWD Precipitation to your Home Assistant instance, use this button:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dwd_precipitation)

Enter a name and pick the location; the [configuration guide](https://hoffmann77.github.io/ha-dwd-precipitation/getting-started/configuration) explains every option. Manual installation is described in the [installation guide](https://hoffmann77.github.io/ha-dwd-precipitation/getting-started/installation).

## Data source

All data is derived from the **DWD (Deutscher Wetterdienst)**:

<img src="docs/assets/dwd-logo.png" alt="Deutscher Wetterdienst Logo" width="200"/>

**[Current status of the DWD radar stations](https://www.dwd.de/DE/leistungen/radarniederschlag/rn_info/home_freie_radarstatus_kartendaten.html)**

## License

This integration is licensed under the [Apache License 2.0](LICENSE).

It owes a lot to the contributors of the **[wradlib](https://github.com/wradlib/wradlib)** package: early versions embedded parts of it, and the test suite still checks every parser and grid lookup against it.
