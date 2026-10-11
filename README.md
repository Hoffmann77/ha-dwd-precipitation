

# DWD Precipitation

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/Hoffmann77/ha-dwd-precipitation)](https://github.com/Hoffmann77/ha-dwd-precipitation/releases/latest)
[![Tests](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/tests.yml)
[![HACS Validate](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml/badge.svg)](https://github.com/Hoffmann77/ha-dwd-precipitation/actions/workflows/validate.yaml)

Radar-based precipitation measurements and forecasts from the German Weather Service (DWD), for your exact location, directly in Home Assistant.

> [!IMPORTANT]
> This integration **only works** for locations **within Germany** and areas immediately adjacent to the German border.
> The DWD radar composites do not cover other countries.

## Features

- **Location-precise:** values come from the ~1 km radar grid cell containing your coordinates
- **Live:** the nowcast sensors refresh every 5 minutes
- **Two-hour forecast:** forecast totals, peak intensity, the wettest hour ahead, and when rain starts and stops
- **Precipitation type:** rain, drizzle, snow, sleet, graupel, hail, freezing rain
- **Measured totals:** past hour, past 24 hours, yesterday, and a days-without-rain counter
- **Long-term totals:** running rain totals for Home Assistant's statistics, so weekly, monthly and yearly sums work out of the box
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
- **Peak hourly precipitation next 2h** (mm): the wettest 60-minute window forecast within the next 2 h
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
- **Precipitation total (hourly)** (mm): running total of all rain since setup, grows once an hour. For "rain this week" and same-day automations
- **Precipitation total (daily)** (mm): the same, built from `Precipitation yesterday`, grows once a day. For monthly and yearly statistics

See [Entity details](#entity-details) for the full behaviour of each sensor and its attributes, and [How DWD data is interpreted](#how-dwd-data-is-interpreted) for what the underlying DWD files contain.

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

- **Add technical details to each sensor** (default: off): adds the source attributes listed under [Attributes](#attributes).
- **Show sensors as unavailable when the data is out of date** (default: on): if DWD does not publish a new file in time, sensors report `unavailable` instead of keeping the last value. See [Troubleshooting](#troubleshooting) for how long "in time" is. The missing file keeps being retried either way.
- **Rain detection threshold (mm per hour)** (default: 0): how much forecast rain counts as rain for `Precipitation start`, `Precipitation end` and `Precipitation expected`. 0 means any amount DWD detects; around 0.5 ignores drizzle.
- **How "Precipitation start" and "Precipitation end" report** (default: clock time): show a clock time or the minutes until the event. The other form is always available as an attribute.
- **When "Precipitation end" counts rain as over** (default: first dry gap): see `Precipitation end` below.
- **Rain needed to reset the dry-streak counter (mm)** (default: 1.0): `Precipitation now` at or above this value resets `Timespan without precipitation`.
- **Include the past hour in the hourly forecast series** (default: off): makes the `forecast_rolling_1h` attribute of `Peak hourly precipitation next 2h` start one hour earlier, so the first entries also include rain that has already fallen and a chart shows the past hour and the forecast as one curve. The sensor's value does not change. Roughly doubles the processing time per update, which can matter on small devices such as a Raspberry Pi.

## Entity details

For the full two-hour forecast total, add `Precipitation next 1h` and `Precipitation next 1–2h`.

### RADVOR RS: radar nowcast · every 5 min

- **Precipitation now** (mm): rain that fell in the past 60 minutes. This is a total, not a mm/h rate. It covers the same window as `Precipitation last 1h` but updates every 5 minutes (radar only).
- **Precipitation next 1h** (mm): forecast total for the next 0–60 min.
- **Precipitation next 1–2h** (mm): forecast total for 60–120 min from now.
- **Peak hourly precipitation next 2h** (mm): the most rain forecast to fall in any 60-minute window within the next 2 h, checked in 5-minute steps. Calculated from the RV 5-minute forecast by default, and from RS when *Include the past hour in the hourly forecast series* is on; the value is identical either way, so switching the option keeps the entity and its history. A downpour that straddles the one-hour mark shows here in full, where `Precipitation next 1h` and `next 1–2h` each only see part of it. This matches how DWD's heavy-rain warnings are defined (amount per hour), so it suits alert automations. `0` when no rain is forecast. The hours it compares are listed in the `forecast_rolling_1h` attribute.
- **Timespan without precipitation** (days): time since `Precipitation now` last reached the reset threshold. Survives restarts; rain during downtime is caught up from the RADOLAN totals on startup. A reading without data (`unknown`) does not reset it.

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

All three are `unknown` when DWD has no data for your grid cell in that file (for example during a radar outage), rather than reporting a placeholder value.

### Running totals: for statistics · hourly / daily

Two ever-growing totals (state class `total_increasing`), for Home Assistant's long-term statistics, the statistics graph card, and the [Utility Meter](https://www.home-assistant.io/integrations/utility_meter/) helper. Use them for daily, weekly, monthly or yearly rain sums; the other sensors are snapshots and do not add up correctly over time. Both start at 0 when the integration is set up and keep their total across restarts. They stay available while DWD is not publishing, because the total counted so far is still correct; *Show sensors as unavailable when the data is out of date* does not apply to them. Files without data for your grid cell add nothing.

- **Precipitation total (hourly)** (mm): adds each `Precipitation last 1h` value once. Up to date within the hour, so it suits "how much rain since this morning" automations.
- **Precipitation total (daily)** (mm): adds each `Precipitation yesterday` value once. Today's rain only appears the next morning, but a single file a day makes it the most robust choice for monthly and yearly figures. On the two DST changeover days the 23:50 windows are 23 or 25 hours apart while each file covers 24 hours, so one hour is counted twice in spring and missed in autumn.

If Home Assistant was offline, or DWD failed to publish for a while, the missed files are fetched in the background on the next update (up to 48 hours for the hourly total, 7 days for the daily one) and added late. Files DWD no longer serves are left out.

### Attributes

Always present:

| Attribute | Entities | Description |
|-----------|----------|-------------|
| `minutes_until` / `at` | `Precipitation start`, `Precipitation end`, `Precipitation expected` | The form *not* shown as the state: whole minutes until the event, or its ISO-8601 UTC time. The binary sensor carries both, pointing at the forecast start (`null` when no rain is expected) |
| `forecast_5min` | `Precipitation expected` | The full 25-point RV forecast (0–120 min in 5-minute steps); each point has `lead` (minutes from now), `start`, `end`, `value` (mm in those 5 minutes) and `intensity` (mm/h). `value` and `intensity` are `null` for a step without data. Not recorded in history |
| `window_start` / `window_end` | `Peak hourly precipitation next 2h` | ISO-8601 UTC start and end of the wettest hour; `null` when no rain is forecast. If two windows tie, the earlier one |
| `forecast_rolling_1h` | `Peak hourly precipitation next 2h` | The hourly forecast series the sensor picks its value from: one entry every 5 minutes, each the mm of rain in the hour from `start` to `end`. At 14:00 the entries run from 14:00–15:00 to 15:00–16:00 (13 entries); the sensor shows the largest. With *Include the past hour in the hourly forecast series* on, the series starts one hour earlier, at 13:00–14:00 (25 entries); the first entry then equals `Precipitation now`. `lead` is the minutes from now to `end`. Not recorded in history |
| `hours_without_precipitation` | `Timespan without precipitation` | The dry streak in hours; `null` until the counter has started |
| `dry_since` | `Timespan without precipitation` | ISO-8601 UTC time of the rain that last reset the counter |
| `counted_until` | `Precipitation total (hourly)`, `Precipitation total (daily)` | ISO-8601 UTC end of the newest DWD window included in the total; `null` until the first file arrives. Missed files fetched later are added without moving it back |

With **Add technical details to each sensor** enabled, every DWD sensor except `Precipitation expected`, the two running totals and `Timespan without precipitation` also has:

| Attribute | Description |
|-----------|-------------|
| `source_product` | DWD product identifier from the file header (e.g. `"RADVOR-RS"`, `"RW"`) |
| `source_timestamp` | UTC reference time of the DWD file. For RADVOR, the analysis time before the forecast lead; for RADOLAN, the end of the measurement window |
| `lead_time_minutes` | Forecast lead in minutes (`0`, `60` or `120` for RADVOR, the end of the wettest hour for `Peak hourly precipitation next 2h`, `null` there when no rain is forecast; `null` for RADOLAN) |
| `data_start` / `data_end` | ISO-8601 UTC start and end of the period the value covers (for `Peak hourly precipitation next 2h`, the wettest hour, same as `window_start` / `window_end`); omitted for values without a period |

## Troubleshooting

**A sensor is briefly `unavailable`, or the log says a DWD file was not found.** DWD often publishes a few minutes late. The integration retries automatically, starting after 60 seconds and backing off to at most 5 minutes (15 minutes for `Precipitation yesterday`). A sensor only turns `unavailable` once its next file is more than 6 minutes overdue (30 minutes for `Precipitation yesterday`), and recovers on the next successful fetch. Your configuration is not at fault.

**Sensors stay `unavailable` after setup.** Check the Home Assistant log for errors and verify that `opendata.dwd.de` is reachable from your network. If only some sensors are affected, the other DWD products keep working independently.

**`Precipitation type` shows `unknown`.** The location is outside the HymecNG radar coverage.

**`Precipitation last 1h`, `last 24h` or `yesterday` shows `unknown`.** DWD's file has no data for your grid cell, usually because of a radar outage. The next file normally fills it again; the running totals skip that window.

**Old values persist after a DWD outage.** *Show sensors as unavailable when the data is out of date* is turned off, so the last value is kept. Turn it on to have sensors report `unavailable` instead.

## How DWD data is interpreted

This section describes how we understand the DWD files behind each sensor. It is based on the files' own metadata and on comparisons against live data, not on an official DWD statement. Each point says whether it was **verified** or is our **reading**.

### The products at a glance

| Product | One grid cell holds | Window per value | Measured or forecast | Rain gauges used | New file |
|---------|---------------------|------------------|----------------------|------------------|----------|
| **RV** | rain amount (mm) | 5 min | lead 0 measured, leads 5–120 forecast | no | every 5 min, 25 members |
| **RS** | rain amount (mm) | 60 min, rolling | mixed (see below) | no | every 5 min, 25 members |
| **HymecNG** | precipitation *type* class | none (snapshot) | measured | no | every 5 min, 1 member |
| **RADOLAN RW** | rain amount (mm) | 60 min, ending HH:50 | measured | **yes** | hourly |
| **RADOLAN SF** | rain amount (mm) | 24 h, ending HH:50 | measured | **yes** | hourly |

A *lead* is the member's offset in minutes from the release time **T** (the time in the file name). Each member names its own window in its `startdate`/`starttime` and `enddate`/`endtime` attributes. Each member also carries DWD's `how/simulated` flag: `False` for observations, `True` for forecasts. **Verified** on live files: in both RV and RS only `_000` has `simulated=False`.

### RV: one measured step, then the forecast

```
composite_rv_YYYYMMDD_HHMM.tar          release T
├── _000   T-5    -> T        measured   simulated=False   <- "the last 5 minutes"
├── _005   T      -> T+5      forecast   simulated=True
├── _010   T+5    -> T+10     forecast
│   ...
└── _120   T+115  -> T+120    forecast
```

Each member is the rain amount in its 5 minutes. Multiply it by 12 to get a rate in mm/h, which is how the `Peak intensity` sensors and the `intensity` field of `forecast_5min` are computed. Lead 0 is the most current *measured* rain the integration receives. Today it appears only as the first entry (`lead` 0) of the `forecast_5min` attribute.

### RS: RV summed into rolling hours

Each RS member is a 60-minute total ending at T + lead, so neighbouring members overlap by 55 minutes. DWD builds the past part from the **measured lead 0 of earlier RV releases**, not from a forecast shifted back in time:

```
RS release T = 16:10 UTC

            the past hour (measured)               |            the next hour (forecast)
          15:10                              16:10 | 16:10                              17:10
5-min     [m][m][m][m][m][m][m][m][m][m][m][m]     | [f][f][f][f][f][f][f][f][f][f][f][f]
steps      ^                                ^      |  ^                                ^
           lead 0 of RV 15:15      lead 0 of RV    |  RV 16:10 lead 5     RV 16:10 lead 60
                                   16:10           |

RS _000 = [m] x 12                 15:10 -> 16:10     simulated=False   "Precipitation now"
RS _030 = [m] x 6  + [f] x 6       15:40 -> 16:40     simulated=True
RS _060 = [f] x 12                 16:10 -> 17:10     simulated=True    "Precipitation next 1h"
RS _120 = RV 16:10 leads 65..120   17:10 -> 18:10     simulated=True    "Precipitation next 1-2h"

[m] = a 5-minute radar measurement, the lead 0 of the RV release ending at that step
[f] = a 5-minute forecast step from the current RV release
```

**Verified** on 2026-10-11 against every cell of the German grid, for the RS releases at 12:05 and 16:10 UTC:

| Comparison | 16:10 | 12:05 |
|------------|-------|-------|
| RS `_000` = sum of RV lead 0 from the 12 releases T-55 ... T | identical in every cell | identical except 0.10 % of cells, max 0.024 mm |
| RS `_060` = sum of RV leads 5–60 of release T | identical | identical except 0.06 % of cells, max 0.011 mm |
| RS `_030` = 6 past lead-0 steps + RV leads 5–30 of T | identical | identical except 0.12 % of cells, max 0.024 mm |
| RS `_120` = sum of RV leads 65–120 of release T | identical | identical except 0.06 % of cells, max 0.010 mm |

"Identical" means equal within the 0.001 mm resolution of the files. The few small differences appear in the purely forecast `_060` as well, so they don't come from reprocessed measurements. Our guess is that DWD sums values that have not yet been rounded to 0.001 mm. Re-run the check with [`scripts/verify_rs_rv.py`](scripts/verify_rs_rv.py) on any of the files DWD currently keeps (about the last two days).

What this means for the sensors:

- **`Precipitation now` is a measured value**, but it is the total of the **last hour**, not the rain falling right now. A shower that began 5 minutes ago barely shows; one that ended 50 minutes ago still counts. That is why it suits the reset threshold of `Timespan without precipitation`, where a short radar blip should not count as rain.
- **`Peak hourly precipitation next 2h` gives the same value from RV or RS** because RS *is* summed RV. With *Include the past hour in the hourly forecast series* on, the first entries of `forecast_rolling_1h` are the measured/forecast mixtures shown for `_030` above.
- At the edge of radar coverage, RV marks a forecast step as "no data" where RS reports 0. The integration counts such a step as 0, the same as RS does.

### HymecNG: a snapshot, not a period

```
composite_HymecNG_YYYYMMDD_HHMM_000-hd5    release T
└── _000   starttime = endtime = T        measured   simulated=False
```

Each cell holds a class (rain, snow, sleet, hail, ...) for the moment T. **Verified:** the file's start and end time are the same. There is no forecast of precipitation type, so `Precipitation type` describes the latest radar scan and changes in 5-minute steps.

### RADOLAN RW / SF: radar corrected with rain gauges

RW and SF are analyses: radar estimates corrected against DWD's network of rain gauges. They are the most accurate measured totals available here. The cost is speed: an RW window ends at HH:50 and the file arrives about 28 minutes later. So `Precipitation last 1h` can describe an hour that ended up to about 90 minutes ago. RS `_000` covers the same 60 minutes, radar only, but is never more than about 5 minutes old.

### How fresh each value is

| Sensor | Window of the value | Available on OpenData |
|--------|---------------------|-----------------------|
| `Precipitation now` | T-60 -> T | about 4 min after T |
| RV lead 0 (`forecast_5min`, lead 0) | T-5 -> T | about 4 min after T |
| `Precipitation type` | at T | about 2–3 min after T |
| `Precipitation last 1h` | HH-1:50 -> HH:50 | about 28 min after HH:50 |
| `Precipitation last 24h` | 24 h ending HH:50 | about 28 min after HH:50 |

On top of this, each installation waits a fixed extra 0–30 s before fetching, so that not every installation hits DWD at the same second.

### Accuracy

DWD doesn't attach an accuracy figure to these files, and we don't quote one. What we can say:

- **RV, RS and HymecNG are radar-only.** Radar measures reflectivity, which is converted to a rain rate. That conversion is the main source of error, together with:
  - signal loss behind heavy rain cells
  - mountains blocking the beam
  - the beam overshooting low drizzle far from a radar
  - melting snow at the freezing level ("bright band") reading as heavy rain
  - snow amounts generally
  
  For one grid cell over one hour, expect radar-only totals to be off by tens of percent at times, in either direction.
- **RW and SF are gauge-adjusted** and are the better choice for "how much really fell". This is why the running totals are built from them, not from RS.
- **The forecast leads (`simulated=True`)** move the current rain field forward in time. They grow less reliable with lead time, and they cannot predict showers that have not formed yet.
- **Radar outages:** every ODIM file lists the radar sites it used (`nodes`) and any that were down (`missing_nodes`, `incomplete_nodes`). A missing radar near your location is the most common reason one reading is clearly wrong.

## Data source

All data is derived from the **DWD (Deutscher Wetterdienst)**:

<img src="docs/assets/dwd-logo.png" alt="Deutscher Wetterdienst Logo" width="200"/>

## License

This integration is only possible thanks to the great work done by the contributors of the **[wradlib](https://github.com/wradlib/wradlib)** package.

All files in `custom_components/dwd_precipitation/radar/` are licensed under the [wradlib license](custom_components/dwd_precipitation/radar/LICENSE.txt) (MIT).
