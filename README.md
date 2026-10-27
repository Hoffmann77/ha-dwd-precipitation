# DWD Precipitation

**English** | [Deutsch](https://github.com/Hoffmann77/ha-dwd-precipitation/blob/main/README.de.md)

[![Documentation](https://img.shields.io/badge/docs-read%20online-blue.svg)](https://hoffmann77.github.io/ha-dwd-precipitation/)
[![Marketplace and HACS](https://img.shields.io/badge/Marketplace%20%26%20HACS-default%20catalog-41BDF5.svg)](https://hoffmann77.github.io/ha-dwd-precipitation/getting-started/installation)
[![GitHub Release](https://img.shields.io/github/v/release/Hoffmann77/ha-dwd-precipitation)](https://github.com/Hoffmann77/ha-dwd-precipitation/releases/latest)
[![Tests](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml)
[![HACS Validate](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml)

Radar-based precipitation measurements and forecasts from the German Weather Service (DWD), for your exact location, directly in Home Assistant.

> [!IMPORTANT]
> This integration **only works** for locations **within Germany** and areas immediately adjacent to the German border.
> The DWD radar composites do not cover other countries.

> [!TIP]
> **[Read the documentation](https://hoffmann77.github.io/ha-dwd-precipitation/)** for every sensor, every option, how it works, and help with problems. Also [in German](https://hoffmann77.github.io/ha-dwd-precipitation/de/).
>
> [Installation](https://hoffmann77.github.io/ha-dwd-precipitation/getting-started/installation) · [Configuration](https://hoffmann77.github.io/ha-dwd-precipitation/getting-started/configuration) · [Entities](https://hoffmann77.github.io/ha-dwd-precipitation/entities/overview) · [Rain warnings](https://hoffmann77.github.io/ha-dwd-precipitation/entities/rain-warnings) · [FAQ](https://hoffmann77.github.io/ha-dwd-precipitation/help/faq) · [Troubleshooting](https://hoffmann77.github.io/ha-dwd-precipitation/help/troubleshooting)

## Features

- **Location-precise:** values come from the ~1 km radar grid cell containing your coordinates
- **Live:** the nowcast sensors refresh every 5 minutes
- **Two-hour forecast:** forecast totals, peak intensity, the wettest hour ahead, and when rain starts and stops
- **Precipitation type:** rain, drizzle, snow, sleet, graupel, hail, freezing rain
- **Measured totals:** past hour, past 24 hours, yesterday, and a days-without-rain counter
- **Long-term totals:** running rain totals for Home Assistant's statistics, so weekly, monthly and yearly sums work out of the box
- **Rain warnings:** your own warnings, such as "Laundry, 60 minutes ahead", each an on/off entity for automations, optionally only for rain above a minimum
- **Rain events for blueprints** (optional): each shower followed from the first forecast until it has passed, with forecast and measured amounts side by side
- **Adjustable thresholds:** choose how much rain counts, for the forecast sensors and for rain events alike

## Entities

All entities belong to one **DWD Precipitation** device per configured location (rain warnings are a device each):

- **Radar nowcast, every 5 minutes:** Precipitation last 60 min, next 60 min, next 60–120 min and next 120 min; Precipitation intensity now; Peak intensity next 60 min, next 60–120 min and next 120 min; Peak hourly precipitation next 120 min; Precipitation start and end; Precipitation expected; Precipitation type now
- **Gauge-adjusted analyses, hourly and daily:** Precipitation previous hour, last 24h and yesterday
- **For statistics:** Precipitation total and Precipitation total daily
- **Timespan without precipitation**, and the optional **Rain events** sensor for blueprints
- **Rain warnings** you add yourself, each a device of its own with an on/off and a status entity and a lead-time slider. The status gives the event's start, end and expected precipitation type (estimated from within 5 km before the rain arrives)

The [entity overview](https://hoffmann77.github.io/ha-dwd-precipitation/entities/overview) lists every entity with its id, unit and update interval.

> [!NOTE]
> Upgrading from a version before 2026.11.0? Several entities were renamed, and existing installs keep their old entity ids. See [Upgrading](https://hoffmann77.github.io/ha-dwd-precipitation/help/upgrading).

## Blueprint and dashboard tile

Two ready-made building blocks for the rain warnings live in this repository; their texts are in German:

- **Blueprint "DWD Regenwarnung"** ([`blueprints/automation/dwd/dwd_regenwarnung.yaml`](blueprints/automation/dwd/dwd_regenwarnung.yaml)): reports each rain event once, as a notification and as a voice announcement, each with its own time window and minimum intensity (mm/h), for example to keep drizzle out of announcements. The texts ("In 20 Minuten beginnt leichter Regen für 35 Minuten.") can be changed. Import the file under **Settings > Automations & Scenes > Blueprints > Import blueprint** and pick a warning's "Rain warning status" sensor.
- **Dashboard tile** ([`dashboards/dwd_regenwarnung_kachel.yaml`](dashboards/dwd_regenwarnung_kachel.yaml)): shows the next rain as text and the two-hour forecast as a colour gradient. Needs [Mushroom](https://github.com/piitaya/lovelace-mushroom) and [card-mod](https://github.com/thomasloven/lovelace-card-mod); put your warning's status sensor in the `entity:` line.

## Screenshots

<img src="https://raw.githubusercontent.com/Hoffmann77/ha-dwd-precipitation/main/docs/assets/screenshot_config_flow.png" alt="Setup dialog — name field and location selector map." height="400"/>

<img src="https://raw.githubusercontent.com/Hoffmann77/ha-dwd-precipitation/main/docs/assets/screenshot_entities_2026-8-0.png" alt="Device page — the precipitation sensors and their current values." height="400"/>

## Installation

**Home Assistant 2026.11 and newer:** DWD Precipitation is in the built-in Marketplace. Go to **Settings > Marketplace**, search for *DWD Precipitation* and select **Install**, or use this button:

[![Open your Home Assistant instance and open a repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=integration)

Installed with HACS before? Nothing to do: the Marketplace takes it over when Home Assistant 2026.11 first starts.

**Home Assistant 2026.10 and older:** install it with [HACS](https://hacs.xyz), then restart Home Assistant:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=integration)

Then add DWD Precipitation to Home Assistant with this button:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dwd_precipitation)

Enter a name and pick the location; the [configuration guide](https://hoffmann77.github.io/ha-dwd-precipitation/getting-started/configuration) explains every option. Manual installation, updates and removal are described in the [installation guide](https://hoffmann77.github.io/ha-dwd-precipitation/getting-started/installation).

## Data source

All data is derived from the **DWD (Deutscher Wetterdienst)**:

<img src="docs/assets/dwd-logo.png" alt="Deutscher Wetterdienst Logo" width="200"/>

**[Current status of the DWD radar stations](https://www.dwd.de/DE/leistungen/radarniederschlag/rn_info/home_freie_radarstatus_kartendaten.html)**

## License

This integration is licensed under the [Apache License 2.0](LICENSE).

It owes a lot to the contributors of the **[wradlib](https://github.com/wradlib/wradlib)** package: early versions embedded parts of it, and the test suite still checks every parser and grid lookup against it.
