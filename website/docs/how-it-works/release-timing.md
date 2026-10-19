---
title: Release timing
description: When each DWD product is published and fetched, why values arrive minutes after their time, and how failed fetches are retried.
---

The integration does not poll on a fixed interval. Each product is fetched
when DWD is expected to have published its next file, and retried if it has
not.

## When each product is fetched

Every DWD file has a nominal time: the end of the window it measures, or the
analysis time a forecast starts from. It appears on Open Data some minutes
later. The integration fetches each product at its nominal time plus that
delay:

| Product | Nominal times | Published about | Fetched at |
|---------|---------------|-----------------|------------|
| RADVOR RS, RV | every 5 min (:00, :05, …) | 4 min later | :04, :09, … |
| HymecNG | every 5 min | 3 min later | :03, :08, … |
| RADOLAN RW | hourly, on the hour | 28 min later | :28 |
| RADOLAN RW, 10-minute runs¹ | every 10 min | 28 min later | :08, :18, … |
| RADOLAN SF | hourly at :50 | 31 min later | :21 |
| RADOLAN SF, yesterday | daily at 23:50 German local time | 31 min later | 00:21 local time |

¹ Only fetched when [Timespan without precipitation](../entities/dry-streak.md)
counts RW.

On top of that, every installation gets its own fixed offset of up to
30 seconds, so that not every Home Assistant in Germany asks DWD in the same
second. The offset is derived from the config entry, so it stays the same
across restarts.

The delays are checked against what DWD actually does by a scheduled job in
the project's CI, which raises an issue if DWD starts publishing later than
the integration expects.

## Why "now" is a few minutes old

A value describes its DWD window, not the moment it appears in Home
Assistant. `Precipitation intensity now` from the release of 14:00 describes
13:55–14:00 and appears at about 14:04, so it is roughly 4 to 10 minutes old
by the time you see it, depending on when within the 5 minutes you look. The
same holds for `Precipitation type now` and `Precipitation last 60 min`.

The forecasts are counted from the release time as well: at 14:04,
`Precipitation next 60 min` still covers 14:00–15:00.

## When DWD is late

DWD often publishes a few minutes late, so a file that is not there yet on
the first attempt is normal, not an error. The integration then retries:

- the first retry after 60 seconds,
- each further one 10 seconds later than the one before,
- up to every 5 minutes (15 minutes for `Precipitation yesterday`), and at
  that pace for as long as the outage lasts.

Each retry is varied by up to 15 %, so installations that failed together do
not retry together. Only a successful fetch resets the pace, so a long DWD
outage settles at the slowest retry rather than asking every minute.

The log gets one message per run of failures, saying what DWD did, for
example that a release was not published yet. Whether the sensors stay
available meanwhile is explained in
[Availability and staleness](availability.md).
