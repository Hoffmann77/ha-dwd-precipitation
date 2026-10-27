---
title: Timespan without precipitation
description: The days-without-rain counter, what resets it, and how it handles restarts and outages.
---

**Timespan without precipitation** (days) counts the time since it last
rained enough at your location. It suits watering automations: "water the
garden after three dry days".

| Attribute | Meaning |
|-----------|---------|
| `hours_without_precipitation` | The same streak in hours; `null` until the counter has started |
| `dry_since` | The time the counter counts from, ISO-8601 UTC: the end of the hour that last reset it, or on a new install the start of the dry period DWD's data shows |

A new install does not start at zero: the counter starts as far back as
DWD's gauge-adjusted analyses prove it was dry, up to 24 hours (when
`Precipitation last 24h` stayed below the threshold). It keeps counting
across restarts.

## What resets it

Two options decide it:

- [**Rain that resets the count**](../getting-started/configuration.md#dry-streak-threshold)
  (default 1.0 mm): a past-hour total at or above this resets the counter. It
  is an amount within the hour, not a rate.
- [**Measured with**](../getting-started/configuration.md#dry-streak-source)
  picks which past-hour total is compared:

| Source | Updated | A reset shows | Notes |
|--------|---------|---------------|-------|
| **Radar and rain gauges (RW)** | every 10 min | 30 to 40 min after the rain | Corrected with rain gauges, more accurate. Default for new installs |
| **Radar only (RS)**, the hour of `Precipitation last 60 min` | every 5 min | a few minutes after the rain | Radar only, noisier |

Both sources are the rain of the last 60 minutes: RS a new hour every
5 minutes, RW every 10, as DWD reruns its analysis for the hour ending then.
A reset moves `dry_since` to the end of the hour that reached the threshold.
So with either source, rain keeps resetting the counter after it has
stopped, for as long as what fell inside the latest hour still reaches the
threshold: up to an hour. The counter then starts at the end of the last
such hour, at most an hour after the rain stopped.

Installs set up before the source option existed keep RS, so upgrading
changes nothing. When you switch, the counter keeps its value.

There is deliberately no fallback to the other product: while the selected
one is unavailable, so is the counter.

## Restarts and downtime

While Home Assistant is down, nothing is measured. On startup the counter
catches up from the RADOLAN analyses:

- if the latest RW hour reached the threshold, the counter restarts at the
  end of that hour;
- otherwise, if SF's past 24 hours did, it restarts at the start of those
  24 hours, since SF cannot say when within the day it rained.

The hours of the downtime are then also checked one by one, as described
next, which places rain within the downtime to the hour.

## Outages: hours without data are checked later

A reading without data (`unknown`, for example while a radar is out of DWD's
composite) cannot reset the counter, so rain in such a gap would be missed.
When the source has had no data for your location for more than an hour,
the clock hours it missed are checked against DWD's gauge-adjusted hour
(`Precipitation previous hour`) once it reports again: an hour that reached
the threshold resets the counter to that hour's end. The same check covers
the time Home Assistant was down, and time DWD failed to publish.

The hours are fetched in the background, newest first. DWD keeps them for
two days, so an older gap is not checked. See
[ADR 0011](/development/adr/0011-dry-streak-gaps-checked-against-rw) for
the reasoning.
