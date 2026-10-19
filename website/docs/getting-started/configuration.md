---
title: Configuration
description: Set up a location and choose the options of DWD Precipitation.
---

## Setup

When you add the integration, it asks for two things:

![Setup dialog with the name field and the location map](/screenshot_config_flow.png)

- **Name:** used for the device and as the prefix of every entity id. It
  defaults to the name of your Home Assistant location. With the name `Home`,
  the entities are `sensor.home_precipitation_last_60_min` and so on.
- **Location:** the point to report precipitation for. It defaults to your
  Home Assistant home location. The sensors report the radar grid cell
  containing this point, about 1 km across.

A location clearly outside Germany is rejected right away. One near the edge
of the radar coverage is accepted, and if a product turns out not to cover it,
the log says so when that product is read. See
[Grid cell lookup](../how-it-works/grid-lookup.md).

### Several locations

Add the integration once per location, for example for your home and your
holiday flat. Every entry gets its own device and its own set of entities,
so each needs a different name.

To move an existing entry to another location, delete it and add it again.

## Options

Open **Settings > Devices & services > DWD Precipitation > Configure**.
Saving the options reloads the integration; the values come back within a
few seconds.

None of the options change how often data is fetched: each product is
refreshed as soon as DWD publishes it, and failed fetches are retried
automatically.

| Option | Default | Affects |
|--------|---------|---------|
| [Add technical details to each sensor](#technical-details) | off | attributes of most sensors |
| [Rain detection threshold](#rain-detection-threshold) | 0 mm/h | Precipitation start, end, expected |
| [How "Precipitation start" and "Precipitation end" report](#start-and-end-format) | clock time | Precipitation start, end |
| [Rain needed to reset the dry-streak counter](#dry-streak-threshold) | 1.0 mm | Timespan without precipitation |
| [Product that resets the dry-streak counter](#dry-streak-source) | gauge-adjusted hour (RW) | Timespan without precipitation |

### Technical details

**Add technical details to each sensor** attaches the DWD product name, the
measurement time and the period each value covers to the sensors as
attributes. It is useful in templates, or when you report a problem; leave it
off otherwise. [Attributes](../entities/attributes.md#technical-details)
lists them.

### Rain detection threshold

**Rain detection threshold (mm per hour)** sets how much forecast rain counts
as rain for `Precipitation start`, `Precipitation end` and
`Precipitation expected`. `0` means any amount DWD detects; raise it to
around `0.5` to ignore drizzle.

The other sensors always report what DWD reports, whatever this threshold.

### Start and end format

**How "Precipitation start" and "Precipitation end" report** chooses between:

- **Clock time** (default): the sensors are timestamps, for example `14:25`.
- **Minutes from now**: the sensors are durations in minutes, for example
  `20`.

Whichever form you do not pick stays available as an attribute on the same
sensor (`at` or `minutes_until`).

### Dry-streak threshold

**Rain needed to reset the dry-streak counter (mm)** sets how much rain
resets `Timespan without precipitation` to zero. It is compared against the
past-hour total of the selected product, in millimetres accumulated over that
hour: `1` means 1 mm fell within the hour, not a rate.

### Dry-streak source

**Product that resets the dry-streak counter** picks which past-hour total
`Timespan without precipitation` compares against the threshold:

- **Gauge-adjusted hour (RW, every 10 minutes)**, the default for new
  installs: corrected with rain-gauge data and more accurate. DWD reruns this
  analysis of the latest 60 minutes every 10 minutes, so a reset shows about
  30 to 40 minutes after the rain.
- **Precipitation last 60 min (radar, RS):** radar only and updated every
  5 minutes. Faster, but noisier, and its rolling hour keeps resetting the
  counter for up to an hour after the rain stops.

Installs set up before this option existed keep `Precipitation last 60 min`,
so upgrading changes nothing; switch here if you prefer RW. The counter keeps
its value when you switch. See
[Timespan without precipitation](../entities/dry-streak.md).

## Advanced options

The **Advanced options** section is collapsed at the bottom of the form. Most
installations never need it.

| Option | Default | Affects |
|--------|---------|---------|
| [Track rain events](#track-rain-events) | off | adds the Rain events sensor |
| [Rain event threshold](#rain-event-threshold) | 0.1 mm/h | Rain events |
| [When "Precipitation end" counts rain as over](#end-algorithm) | first dry gap | Precipitation end |
| [Include the past hour in the hourly forecast series](#past-hour-in-the-series) | off | an attribute of Peak hourly precipitation next 120 min |
| [Show sensors as unavailable when the data is out of date](#unavailable-when-out-of-date) | on | availability of the sensors |

### Track rain events

**Track rain events** adds the [`Rain events`](../entities/rain-events.md)
sensor, which follows each burst of rain from the first forecast that shows
it until it has fallen, for blueprints that warn about or report rain.

With it on, the integration also fetches the radar analyses it missed (a
small part of each file) and keeps a small record of recent rain on disk.
Turning it off removes the sensor and deletes that record, so turning it on
again starts clean.

### Rain event threshold

**Rain event threshold (mm per hour)** sets how much rain a 5-minute step
needs to count towards an event of the `Rain events` sensor. `0` means any
trace forms an event. It is independent of the
[rain detection threshold](#rain-detection-threshold), so the events and
`Precipitation start` can disagree when the two differ. Only used with
*Track rain events* on.

### End algorithm

**When "Precipitation end" counts rain as over** chooses between:

- **First dry gap** (default): the end of the current burst. It moves around
  during showers.
- **Precipitation clears within 2 h:** when no more rain is forecast within
  the two-hour horizon. Steadier, but stays `unknown` longer.

DWD forecasts only two hours ahead, so beyond that the sensor is `unknown`
either way.

### Past hour in the series

**Include the past hour in the hourly forecast series** makes the
`forecast_rolling_1h` attribute of `Peak hourly precipitation next 120 min`
start one hour earlier. The first entries then include rain that has already
fallen, so a chart shows the past hour and the forecast as one curve. The
sensor's value does not change.

The earlier hour is built from the radar analyses of the past hour, without
any extra download. After a restart, or a 5-minute release DWD did not
publish in time, it appears once the integration has seen a full hour of
releases again. See [RADVOR RV nowcast](../entities/radvor-rv.md#peak-hourly-precipitation).

### Unavailable when out of date

**Show sensors as unavailable when the data is out of date:** if DWD does
not publish a new file in time, the affected sensors report `unavailable`
instead of keeping the last value. Turn it off to always keep the most recent
reading, accepting that it may be hours old. Either way the missing file
keeps being retried in the background. See
[Availability and staleness](../how-it-works/availability.md) for how long
"in time" is.
