

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
- **Rain events for blueprints** (optional): each burst of rain followed under one id from forecast to measurement, with forecast and measured amounts side by side
- **Customizable thresholds** for rain events to use as input for automations.

## Entities

All entities belong to one **DWD Precipitation** device per configured location.

Names ending in **`last <N>`** are measured totals over the window ending now.

Names ending in **`next <N>`** are forecasts. The radar nowcast states its windows in minutes: `next 60–120 min` is the *second* hour ahead.

**`previous hour`** and **`yesterday`** are the last complete clock hour and calendar day.

The RADVOR values come from radar alone and update every 5 minutes. The RADOLAN values (`previous hour`, `last 24h`, `yesterday` and the running totals) are DWD's analysis corrected with rain-gauge measurements: they arrive about 30 minutes later, but are more accurate.

> [!NOTE]
> Installs set up before 2026.10.1 keep their entity ids; only the names changed. There, `Precipitation last 60 min` is `sensor.<name>_precipitation_now`, `Precipitation previous hour` is `sensor.<name>_precipitation_last_1h`, and the forecast sensors keep their hour-based ids (`…_precipitation_next_1h`, `…_precipitation_next_1_2h`, `…_peak_intensity_next_1h`, `…_peak_intensity_next_1_2h`, `…_peak_hourly_precipitation_next_2h`), `Precipitation type now` is `…_precipitation_type`, and `Precipitation total` is `…_precipitation_total_hourly`.

**RADVOR RS: radar nowcast · updated every 5 min**

- **Precipitation last 60 min** (mm): rain that fell in the past 60 minutes, from radar alone. This is a total, not a mm/h rate.
- **Precipitation next 60 min** (mm): forecast total for the next 0–60 min
- **Precipitation next 60–120 min** (mm): forecast total for 60–120 min from now
- **Precipitation next 120 min** (mm): forecast total for the whole next 2 hours (the two above added)
- **Peak hourly precipitation next 120 min** (mm): the wettest 60-minute window forecast within the next 2 h
- **Timespan without precipitation** (days): time since the selected source (DWD's gauge-adjusted hour on new installs) last reached the reset threshold.

**RADVOR RV: nowcast in 5-min steps · updated every 5 min**

- **Precipitation intensity now** (mm/h): how hard it is raining, from the latest 5-minute radar analysis
- **Peak intensity next 60 min** (mm/h): heaviest expected rain rate in the next 0–60 min
- **Peak intensity next 60–120 min** (mm/h): the same for 60–120 min
- **Peak intensity next 120 min** (mm/h): the same for the whole next 2 hours
- **Precipitation start** (time or min): when rain begins; `unknown` if none within 2 h
- **Precipitation end** (time or min): when rain stops; `unknown` if it lasts beyond 2 h
- **Precipitation expected** (binary sensor): `on` if rain is forecast within 2 h

**HymecNG: precipitation type · updated every 5 min**

- **Precipitation type now**: what is falling right now: rain, drizzle, snow, sleet, graupel, hail, freezing rain, …

**RADOLAN RW / SF: radar + rain-gauge analysis · updated hourly / daily**

- **Precipitation previous hour** (mm): the last full clock hour, e.g. 11:00–12:00, available about 30 minutes after it ends. Slower than `Precipitation last 60 min`, but more accurate
- **Precipitation last 24h** (mm): rolling past 24 hours
- **Precipitation yesterday** (mm): the previous calendar day's total, available around 00:20 local time
- **Precipitation total** (mm): running total of all rain since setup, grows once an hour. The one to use for statistics and "rain this week" or same-day automations
- **Precipitation total daily** (mm): the same, built from `Precipitation yesterday`, grows once a day

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

- **Add technical details to each sensor** (default: off): adds the source attributes listed under [Attributes](#attributes).
- **Rain detection threshold (mm per hour)** (default: 0): how much forecast rain counts as rain for `Precipitation start`, `Precipitation end` and `Precipitation expected`. 0 means any amount DWD detects; around 0.5 ignores drizzle.
- **How "Precipitation start" and "Precipitation end" report** (default: clock time): show a clock time or the minutes until the event. The other form is always available as an attribute.
- **Rain needed to reset the dry-streak counter (mm)** (default: 1.0): the selected product's past-hour total at or above this value resets `Timespan without precipitation`.
- **Product that resets the dry-streak counter**: which past-hour total `Timespan without precipitation` compares against the threshold.
  - *Gauge-adjusted hour* (RW, default for new installs): more accurate. DWD reruns its gauge-adjusted analysis of the latest 60 minutes every 10 minutes, and the counter follows those runs, so a reset shows about 30 to 40 minutes after the rain.
  - `Precipitation last 60 min` (RS): updated every 5 minutes. Faster, but noisier, and its rolling hour keeps resetting the counter for up to an hour after the rain stops.

  Installs set up before this option existed keep `Precipitation last 60 min`, so upgrading changes nothing; switch here if you prefer RW. The counter keeps its value when you switch, and is unavailable while the selected product is.

#### Advanced options

Collapsed at the bottom of the form; most installations never need them.

- **Track rain events** (default: off): adds the [`Rain events`](#rain-events) sensor. With it on, the integration also fetches the radar analyses it missed (a small part of each file) and keeps a small record of recent rain on disk; turning it off removes the sensor and that record.
- **Rain event threshold (mm per hour)** (default: 0.1): how much rain a 5-minute step needs to count towards an event in the [`Rain events`](#rain-events) sensor. 0 means any trace forms an event. It is independent of the rain detection threshold above, so the events and `Precipitation start` can disagree when the two differ.
- **When "Precipitation end" counts rain as over** (default: first dry gap): see `Precipitation end` below.
- **Include the past hour in the hourly forecast series** (default: off): makes the `forecast_rolling_1h` attribute of `Peak hourly precipitation next 120 min` start one hour earlier, so the first entries also include rain that has already fallen and a chart shows the past hour and the forecast as one curve. The sensor's value does not change. Roughly doubles the processing time per update, which can matter on small devices such as a Raspberry Pi.
- **Show sensors as unavailable when the data is out of date** (default: on): if DWD does not publish a new file in time, sensors report `unavailable` instead of keeping the last value. See [Troubleshooting](#troubleshooting) for how long "in time" is. The missing file keeps being retried either way.

## Entity details


### RADVOR RS: radar nowcast · every 5 min

- **Precipitation last 60 min** (mm): rain that fell in the past 60 minutes, from radar alone, updated every 5 minutes. This is a total, not a mm/h rate. For the gauge-adjusted value of a clock hour see `Precipitation previous hour`; for how hard it is raining at the moment, `Precipitation intensity now`.
- **Precipitation next 60 min** (mm): forecast total for the next 0–60 min.
- **Precipitation next 60–120 min** (mm): forecast total for 60–120 min from now.
- **Precipitation next 120 min** (mm): forecast total for the whole next 2 hours, exactly `Precipitation next 60 min` plus `Precipitation next 60–120 min`. `unknown` if either is.
- **Peak hourly precipitation next 120 min** (mm): the most rain forecast to fall in any 60-minute window within the next 2 h, checked in 5-minute steps. Calculated from the RV 5-minute forecast by default, and from RS when *Include the past hour in the hourly forecast series* is on; the value is identical either way, so switching the option keeps the entity and its history. A downpour that straddles the one-hour mark shows here in full, where `Precipitation next 60 min` and `next 1–2h` each only see part of it. This matches how DWD's heavy-rain warnings are defined (amount per hour), so it suits alert automations. `0` when no rain is forecast. The hours it compares are listed in the `forecast_rolling_1h` attribute.
- **Timespan without precipitation** (days): time since the selected source (DWD's gauge-adjusted hour on new installs; see *Product that resets the dry-streak counter*) last reached the reset threshold. Survives restarts; rain during downtime is caught up from the RADOLAN totals on startup. A reading without data (`unknown`) does not reset it.

### RADVOR RV: nowcast in 5-min steps · every 5 min · 2 h horizon

- **Precipitation intensity now** (mm/h): the rain rate in the latest radar analysis, the 5 minutes ending at DWD's release time, scaled to an hourly rate (1 mm in 5 minutes = 12 mm/h). Updated every 5 minutes; the window it describes ended about 4 to 10 minutes earlier. `unknown` when the radar has no data for your location.
- **Peak intensity next 60 min** (mm/h): heaviest expected rain rate in the next 0–60 min. Tells drizzle from a downpour; `Precipitation next 60 min` gives the amount.
- **Peak intensity next 60–120 min** (mm/h): the same for 60–120 min from now.
- **Peak intensity next 120 min** (mm/h): the same for the whole next 2 hours, the larger of the two above. Suits a single "heavy rain ahead" trigger.
- **Precipitation start** (time or min): when rain begins. Now / `0` if it is already raining, `unknown` if none is forecast within 2 h.
- **Precipitation end** (time or min): when rain stops. `unknown` if it continues beyond 2 h, which means "still raining in 2 hours", not "never".
  - *First dry gap*: end of the current burst. Moves around during showers.
  - *Precipitation clears within 2 h*: when no more rain is forecast within the horizon. Steadier, but stays `unknown` longer.
- **Precipitation expected** (binary sensor): `on` if rain is forecast within the next 2 h.
- **Rain events** (only with *Track rain events* on): `ongoing` while a rain event is falling, otherwise `upcoming` if one is forecast, otherwise `none`. Its attributes follow each event from forecast to measurement; see [Rain events](#rain-events).

### HymecNG: precipitation type · every 5 min

- **Precipitation type now**: what is falling right now, from the latest 5-minute analysis like `Precipitation intensity now`. One of `no_precipitation`, `not_classified`, `drizzle`, `rain`, `freezing_drizzle`, `freezing_rain`, `sleet`, `snow`, `graupel`, `hail`, `large_hail`.

### RADOLAN RW / SF: radar + rain-gauge analysis · hourly / daily

- **Precipitation previous hour** (mm): rain that fell in the last full clock hour, corrected with rain-gauge data. Updated hourly, about 30 minutes after the hour ends (11:00–12:00 arrives around 12:30), but more accurate than `Precipitation last 60 min`.
- **Precipitation last 24h** (mm): rain that fell in the rolling past 24 hours. Updated hourly.
- **Precipitation yesterday** (mm): total for the previous calendar day. Updated once a day, around 00:20 German local time.

All three are `unknown` when DWD has no data for your grid cell in that file (for example during a radar outage), rather than reporting a placeholder value.

### Running totals: for statistics · hourly / daily

Two ever-growing totals (state class `total_increasing`), for Home Assistant's long-term statistics, the statistics graph card, and the [Utility Meter](https://www.home-assistant.io/integrations/utility_meter/) helper. Use them for daily, weekly, monthly or yearly rain sums; the other sensors are snapshots and do not add up correctly over time. Both start at 0 when the integration is set up and keep their total across restarts. They stay available while DWD is not publishing, because the total counted so far is still correct; *Show sensors as unavailable when the data is out of date* does not apply to them. Files without data for your grid cell add nothing.

- **Precipitation total** (mm): adds each `Precipitation previous hour` value once. Up to date within the hour, so it suits "how much rain since this morning" automations. Up to 2026.10.0 it added hours ending at :50; a total carried over from then moves to clock hours on its first update and leaves the 10 minutes in between out once, rather than counting 50 minutes twice.
- **Precipitation total daily** (mm): adds each `Precipitation yesterday` value once. Today's rain only appears the next morning, and Home Assistant's statistics count it on the day it was added, so each day's rain shows up under the following day. Prefer `Precipitation total` unless you specifically want DWD's daily analysis. On the two DST changeover days the 23:50 windows are 23 or 25 hours apart while each file covers 24 hours, so one hour is counted twice in spring and missed in autumn.

If Home Assistant was offline, or DWD failed to publish for a while, the missed files are fetched in the background on the next update and added late. The list of missed files is saved with the total, so a restart in the middle resumes it, and a file that fails to download is tried again with every new one, for as long as DWD keeps it: 48 hours for `Precipitation total`, 7 days for `Precipitation total daily`. Only files DWD no longer serves are left out. Rain added late counts in Home Assistant's statistics at the time it was added, not the hour it fell.

### Attributes

Always present:

| Attribute | Entities | Description |
|-----------|----------|-------------|
| `minutes_until` / `at` | `Precipitation start`, `Precipitation end`, `Precipitation expected` | The form *not* shown as the state: whole minutes until the event, or its ISO-8601 UTC time. The binary sensor carries both, pointing at the forecast start (`null` when no rain is expected) |
| `forecast_5min` | `Precipitation expected` | The full 25-point RV forecast (0–120 min in 5-minute steps); each point has `lead` (minutes from now), `start`, `end`, `value` (mm in those 5 minutes) and `intensity` (mm/h). `value` and `intensity` are `null` for a step without data. Not recorded in history |
| `schema`, `events`, `steps`, … | `Rain events` | The rain around your location split into events, each with a stable id, measured and forecast amounts and their peaks. See [Rain events](#rain-events). Not recorded in history |
| `window_start` / `window_end` | `Peak hourly precipitation next 120 min` | ISO-8601 UTC start and end of the wettest hour; `null` when no rain is forecast. If two windows tie, the earlier one |
| `window_start` / `window_end` | `Precipitation intensity now` | ISO-8601 UTC start and end of the 5-minute radar analysis the rate comes from |
| `amount_5min` | `Precipitation intensity now` | The rain in that window in mm, before it is scaled to mm/h; `null` without data |
| `forecast_rolling_1h` | `Peak hourly precipitation next 120 min` | The hourly forecast series the sensor picks its value from: one entry every 5 minutes, each the mm of rain in the hour from `start` to `end`. At 14:00 the entries run from 14:00–15:00 to 15:00–16:00 (13 entries); the sensor shows the largest. With *Include the past hour in the hourly forecast series* on, the series starts one hour earlier, at 13:00–14:00 (25 entries); the first entry then equals `Precipitation last 60 min`. `lead` is the minutes from now to `end`. Not recorded in history |
| `hours_without_precipitation` | `Timespan without precipitation` | The dry streak in hours; `null` until the counter has started |
| `dry_since` | `Timespan without precipitation` | ISO-8601 UTC time of the rain that last reset the counter |
| `counted_until` | `Precipitation total`, `Precipitation total daily` | ISO-8601 UTC end of the newest DWD window included in the total; `null` until the first file arrives. Missed files fetched later are added without moving it back |

With **Add technical details to each sensor** enabled, every DWD sensor except `Precipitation expected`, the two running totals and `Timespan without precipitation` also has:

| Attribute | Description |
|-----------|-------------|
| `source_product` | DWD product identifier from the file header (e.g. `"RADVOR-RS"`, `"RW"`) |
| `source_timestamp` | UTC reference time of the DWD file. For RADVOR, the analysis time before the forecast lead; for RADOLAN, the end of the measurement window |
| `lead_time_minutes` | Forecast lead in minutes (`0`, `60` or `120` for RADVOR, the end of the wettest hour for `Peak hourly precipitation next 120 min`, `null` there when no rain is forecast; `null` for RADOLAN) |
| `data_start` / `data_end` | ISO-8601 UTC start and end of the period the value covers (for `Peak hourly precipitation next 120 min`, the wettest hour, same as `window_start` / `window_end`); omitted for values without a period |

### Rain events

The `Rain events` sensor (`sensor.<name>_rain_events`, enabled with the *Track rain events* option) is meant for blueprints that warn about short bursts of rain. Its state is `ongoing`, `upcoming` or `none` (an `unseen` event alone counts as `none`), and its attributes are the view below. It follows each event from the first forecast that shows it until it has fallen, under one id, and reports what was forecast against what was measured. It applies one threshold, the *Rain event threshold* option (a 5-minute step is wet if its amount is above a twelfth of it); levels and warnings are up to the blueprint.

```yaml
schema: 1                              # check this; it changes only on a breaking change
base: "2026-10-12T14:30:00+00:00"      # T, the release time (= forecast_5min[0].end
                                       #   of Precipitation expected)
wet_step_mm: 0.008                     # a step is wet above this (mm per 5 min)
steps_start: "2026-10-12T13:30:00+00:00"
steps: [0.0, …, 1.5, …]                # 36 values, mm per 5 min: 12 measured ending at T,
                                       # then forecast_5min[1..24]; null = unknown
history_complete: true                 # no null among the 12 measured steps
events:                                # upcoming | ongoing | unseen, sorted by start
  - id: "20261012t1405-0"              # opaque, stable, never reused
    status: ongoing
    first_seen: "…"                    # T of the first release that showed it
    start: "…"                         # start of the first wet step
    start_clipped: false               # it may have started earlier (no data before)
    end: "…"                           # end of the last wet step, forecast while ongoing
    beyond_horizon: false              # true: still raining at the 2 h horizon
    last_wet_observed: "…"             # null while upcoming
    missing_steps: 0                   # measured steps without data inside the event
    observed_complete: true            # false: measured amounts may be too low
    observed: {mm, peak_1h: {mm, start, end}, peak_10min: {mm, start, end}}
    forecast: {mm, peak_1h, peak_10min}
    total:    {mm, peak_1h, peak_10min}
    forecast_at_onset: {base, start, end, mm, peak_1h, peak_10min,
                        expected_so_far_mm, observed_so_far_mm}   # or null
    absorbed: []                       # ids merged into this event
last_ended: {id, first_seen, start, start_clipped, end, end_clipped, missing_steps,
             observed_complete, observed, forecast_at_onset, absorbed}   # or null
```

- **Steps.** `steps[i]` covers 5 minutes from `steps_start + 5·i min`. The measured part is DWD's radar analysis of each release; releases the integration missed are fetched later (only their analysis, a small part of the file), so a lost release does not leave a gap.
- **Events.** Two dry steps in a row end an event; a single one does not. A step without data never splits or ends an event. An upcoming event that one release does not show stays for that release as `unseen`. When several events join, the one first seen earliest keeps its id and lists the others in `absorbed`; when one splits, the later part gets a new id. An id that disappears was merged if it is in some `absorbed`, ended if it is `last_ended.id`, and vanished otherwise.
- **Amounts.** `observed` covers the event's measured steps, `forecast` its forecast steps within the 2 h horizon, `total` both. `peak_1h` is the wettest hour, `peak_10min` the wettest two steps. `total.peak_1h` is the wettest hour of `steps` that overlaps the event, *including* rain just outside it, because DWD's heavy-rain criterion is simply the amount within an hour.
- **Forecast at onset.** The event's last forecast before its rain arrived, frozen when it did. `expected_so_far_mm` and `observed_so_far_mm` cover exactly the same steps since then, for a like-for-like "9 mm measured where 3 mm was expected". `null` for rain that was never forecast.
- **`last_ended`** is the most recent completed event, with its measured values frozen. It stays until the next event ends, so a report blueprint must copy it when it first sees a new id.

Notes:

- The amounts are radar-only, measured and forecast alike, so nothing jumps at "now". They will differ from a rain gauge and from the gauge-adjusted sensors such as `Precipitation total`.
- Missed releases can be fetched up to an hour back. After a longer downtime, or while DWD keeps failing to serve a release, an event's measured values can be too low: check `observed_complete` (and `missing_steps`, `start_clipped`, `end_clipped`). In short, don't restart Home Assistant during a severe downpour.
- Changing the *Rain event threshold* starts the events over with new ids; the measured steps and `last_ended` are kept.

## Troubleshooting

**A sensor is briefly `unavailable`, or the log says a DWD file was not found.** DWD often publishes a few minutes late. The integration retries automatically, starting after 60 seconds and backing off to at most 5 minutes (15 minutes for `Precipitation yesterday`). A sensor only turns `unavailable` once its next file is more than 6 minutes overdue (30 minutes for `Precipitation yesterday`), and recovers on the next successful fetch. Your configuration is not at fault.

**Sensors stay `unavailable` after setup.** Check the Home Assistant log for errors and verify that `opendata.dwd.de` is reachable from your network. If only some sensors are affected, the other DWD products keep working independently.

**`Precipitation type now` shows `unknown`.** The location is outside the HymecNG radar coverage.

**`Precipitation previous hour`, `last 24h` or `yesterday` shows `unknown`.** DWD's file has no data for your grid cell, usually because of a radar outage. The next file normally fills it again; the running totals skip that window.

**Old values persist after a DWD outage.** *Show sensors as unavailable when the data is out of date* is turned off, so the last value is kept. Turn it on to have sensors report `unavailable` instead.

## Data source

All data is derived from the **DWD (Deutscher Wetterdienst)**:

<img src="docs/assets/dwd-logo.png" alt="Deutscher Wetterdienst Logo" width="200"/>

## License

This integration is only possible thanks to the great work done by the contributors of the **[wradlib](https://github.com/wradlib/wradlib)** package.

All files in `custom_components/dwd_precipitation/radar/` are licensed under the [wradlib license](custom_components/dwd_precipitation/radar/LICENSE.txt) (MIT).
