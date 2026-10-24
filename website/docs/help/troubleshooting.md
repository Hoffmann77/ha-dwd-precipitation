---
title: Troubleshooting
description: What the log messages of DWD Precipitation mean, and what to do when sensors are unavailable or unknown.
---

Most messages from this integration describe something DWD did, not a
problem with your setup. Each one says whether your configuration is
involved (usually it is not) and that retries continue.

## A sensor is briefly unavailable, or a file was not found

> DWD has not published the … release yet (HTTP 404). DWD OpenData is late;
> nothing is wrong with your setup. Retrying in …

DWD often publishes a few minutes late. The integration retries
automatically, starting after 60 seconds and slowing down to at most every
5 minutes (15 minutes for `Precipitation yesterday`). A sensor only turns
`unavailable` once its next file is more than 6 minutes overdue (30 minutes
for `Precipitation yesterday`), and recovers on the next successful fetch.

Nothing to do. See [Release timing](../how-it-works/release-timing.md) and
[Availability and staleness](../how-it-works/availability.md).

## Sensors stay unavailable after setup

> Could not reach DWD OpenData for the … release (…). Check this machine's
> internet access.

Home Assistant cannot reach `opendata.dwd.de`. Check the machine's internet
connection, DNS, and any firewall or proxy between Home Assistant and the
internet. Open <https://opendata.dwd.de/weather/radar/composite/> in a
browser on the same network to see whether DWD is up.

If only some sensors are unavailable, the other DWD products keep working
independently; the log names the product that fails.

## A sensor shows unknown: no radar data for your location

> …: no radar data for your location in the … release (radar(s) missing from
> the DWD composite: depro). … this is a DWD outage, not a configuration
> problem.

DWD's file has no data for your grid cell, usually because a radar has
dropped out of DWD's composite; the warning names the missing radar(s)
(`depro` is Prötzel, near Berlin) when it can tell. The sensors recover on
their own, and the log says so once data is back. It is logged once per
outage, not for every file. DWD shows the
[current status of its radar stations](https://www.dwd.de/DE/leistungen/radarniederschlag/rn_info/home_freie_radarstatus_kartendaten.html).

> …: no radar data for your location in the … release, the first one read.
> Either the location is outside the area this product covers, or a DWD radar
> is out.

Logged right after setup or a restart. If data never arrives, the location is
outside the area that product covers; see
[Grid cell lookup](../how-it-works/grid-lookup.md#which-locations-are-covered).

This applies to every product, including `Precipitation type now` and the
RADOLAN sensors. The running totals skip the windows without data.

## The location is not on the grid

> The configured location is not on the grid of the … release (…): DWD's
> radar does not cover it.

The location passed the coarse check at setup, but lies outside the area
DWD's files cover. Delete the entry and set the integration up again with a
location inside Germany.

## A file could not be read

> Could not read the … release (…). This is likely a change on DWD's side or
> a bug in the integration; please report it if it keeps happening.

DWD served something this version cannot read. If it keeps happening,
[open an issue](#reporting-a-problem).

## Range downloads did not work

> Reading whole DWD … archives: partial (range) downloads of … did not work.
> Values are not affected, but each update now downloads several times the
> data …

The integration normally downloads only the parts of the RADVOR archives it
needs. Something between you and DWD (or DWD itself) did not allow that, so it
falls back to whole archives. The values are the same; only the data volume
grows. A proxy that rewrites requests can cause this. The log says when
partial downloads work again.

## Old values persist after a DWD outage

The advanced option *Show "unavailable" when the data is out of date*
is off, so the last value is kept. Turn it on to have sensors report
`unavailable` instead. See
[Availability and staleness](../how-it-works/availability.md#keeping-the-last-value-instead).

## The values differ from my rain gauge

Radar estimates rain in the air above a 1 km cell; a gauge collects it at one
point on the ground. Differences of tens of percent in a single shower are
normal, and summer showers can miss a gauge a few hundred metres away. The
gauge-adjusted RADOLAN sensors (`Precipitation previous hour`,
`Precipitation total`) usually come closer than the radar-only ones. See
[The DWD products](../how-it-works/dwd-products.md).

## Debug logging

To see what the integration does in detail:

1. Go to **Settings > Devices & services > DWD Precipitation**.
2. Select **Enable debug logging** in the menu.
3. Wait for the problem to occur, then select **Disable debug logging**.
   Home Assistant offers the log file for download.

Or, in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.dwd_precipitation: debug
```

## Reporting a problem

[Open an issue on GitHub](https://github.com/Hoffmann77/ha-dwd-precipitation/issues)
with:

- the integration and Home Assistant versions,
- the log messages, ideally with debug logging,
- for a wrong value: the sensor, its value and the time, and the attributes
  shown with *Add technical details to the sensors* on, which say exactly
  which DWD file the value came from.

You do not need to post your exact location; the nearest town is enough.
