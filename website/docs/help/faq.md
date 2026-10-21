---
title: FAQ
description: Frequently asked questions about DWD Precipitation.
---

## Does it work outside Germany?

Only in a band near the German border. DWD's radar composites cover Germany
and some area around it; elsewhere the files have no data. See
[Grid cell lookup](../how-it-works/grid-lookup.md#which-locations-are-covered).

## Do I need an API key or account?

No. The data comes from [DWD Open Data](https://opendata.dwd.de/), which is
free and needs no registration.

## How much data does it download?

About 1 GB a day on average: measured over three days in October 2026, an
installation downloaded about 0.9 GB a day. It depends on the weather, and not
only at your location: DWD's files cover all of Germany, and rain anywhere
makes them larger, so a dry day costs less and a day of widespread rain more.

Most of it is the RV archive, read completely every 5 minutes. RS is read
partially (about a fifth of each archive), and HymecNG and the RADOLAN files
are small. Keep it in mind on a metered connection.

## Why does "now" lag a few minutes?

A value describes DWD's window, which ends at the release time, and DWD
publishes a few minutes after that. `Precipitation intensity now` is about
4 to 10 minutes old by the time you see it. See
[Release timing](../how-it-works/release-timing.md#why-now-is-a-few-minutes-old).

## Which sensor should I use for rain statistics?

[`Precipitation total`](../entities/totals.md). It only ever grows, so Home
Assistant's statistics, the statistics graph card and the Utility Meter
helper can sum it over any period. The other sensors are snapshots of a
window and do not add up over time.

## What is the difference between "last 60 min" and "previous hour"?

`Precipitation last 60 min` is radar only, a rolling hour updated every
5 minutes. `Precipitation previous hour` is the last full clock hour,
corrected with rain gauges, available about 30 minutes after the hour ends.
The first is faster, the second more accurate. See
[RADOLAN RW and SF](../entities/radolan.md#precipitation-previous-hour).

## Why does it rain here, but the sensor says 0?

- The value may not have arrived yet: radar values are a few minutes old,
  gauge-adjusted ones about half an hour.
- The radar measures in the air above a 1 km cell. Light drizzle, or a
  shower at the edge of your cell, can be below what it detects.
- `Precipitation last 60 min` and `Precipitation previous hour` are totals:
  a short shower might add only a few tenths of a millimetre.

## Why does "Precipitation end" keep changing?

With the default *First dry gap*, it reports the end of the current burst,
which moves as showers form and dissolve. The advanced option *When
"Precipitation end" counts rain as over* can be set to *Precipitation clears
within 2 h* for a steadier answer. See
[RADVOR RV nowcast](../entities/radvor-rv.md#precipitation-start-and-end).

## Why is "Precipitation start" unknown?

No rain is forecast within the next two hours, which is as far as DWD's
nowcast reaches. `Precipitation expected` is then `off`.

## Can I use it for several locations?

Yes: add the integration once per location. See
[Configuration](../getting-started/configuration.md#several-locations).

## Is it an official DWD integration?

No. It is a community project, not affiliated with or endorsed by the
Deutscher Wetterdienst. It uses DWD's public data under their terms of use.
