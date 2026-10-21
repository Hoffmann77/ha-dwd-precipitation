---
title: Availability and staleness
description: When sensors become unavailable or unknown, how long a value is kept while DWD is late, and why one failing product does not affect the others.
---

A sensor can be without a current value for two different reasons, and they
show differently:

| State | Cause | What to do |
|-------|-------|------------|
| `unavailable` | The integration has no current file for the product: DWD is late, or Open Data cannot be reached | Nothing; it recovers on the next successful fetch |
| `unknown` | The file is there, but holds no value for your location (a radar outage), or there is nothing to report (no rain forecast for `Precipitation start`) | Nothing for an outage; it recovers with the next file that has data |

## When a value goes out of date

While DWD is late, the last value is kept for a while: a file that arrives a
few minutes late should not blank your dashboard. A product's sensors turn
`unavailable` once the file that should have replaced their value is more
than **6 minutes overdue** (**30 minutes** for `Precipitation yesterday`).

The clock starts when the next file should have been on Open Data, not when
the current value was published. For RS, with the release of 14:00 shown:

- the release of 14:05 is due at about 14:09,
- if it has not arrived by about 14:15, the RS sensors turn `unavailable`,
- they come back as soon as any newer release is fetched.

The grace is the same for hourly and daily products, because it measures how
long DWD is given to publish, not how old a value may be. Retries continue
throughout, see [Release timing](release-timing.md#when-dwd-is-late).

### Keeping the last value instead

With the advanced option
[*Show sensors as unavailable when the data is out of date*](../getting-started/configuration.md#unavailable-when-out-of-date)
turned off, sensors always keep their most recent value, however old. That
suits dashboards that should never show a gap, but the value can then be
hours old without any sign of it. The technical details attributes
(`source_timestamp`) tell you how old it is.

### Exceptions

- The [running totals](../entities/totals.md) always stay available: the
  total counted so far is still correct, and missed hours are added later.
- [Timespan without precipitation](../entities/dry-streak.md) follows the
  availability of its source product.

## No data for your location

A radar dropping out of DWD's composite leaves the cells only it covered
without data, while every file still downloads fine. The sensors of that
product are then `unknown`. The log gets one warning when data goes, naming
the radar(s) missing when it can tell, and one message when it is back, and
nothing in between.

If that warning appears right after setup and data never arrives, the
location is outside the area that product covers; see
[Grid cell lookup](grid-lookup.md#which-locations-are-covered).

## One product at a time

Each DWD product is fetched on its own schedule, and its failures affect only
its own sensors. If DWD stops publishing one product, its sensors become
unavailable while all others keep working, and the log says which one
failed. The integration only fails to start if *every* product fails, for
example when there is no internet connection; Home Assistant then retries
the setup on its own.
