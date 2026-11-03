# 0011 — Gaps in the dry-streak source are checked against RW's hours

Status: accepted (2026.11.0)

## Context

`Timespan without precipitation` resets only on a reading at or above the
threshold, so a reading without data counts as dry. On 2026-10-13 the Proetzel
radar was missing from the RS analysis from 11:40 to 17:40 UTC, and Berlin had
no RS data for six hours during a large rain event (#109, #114). Rain in such a
gap never reset the streak. Rain while HA was *down* was already caught at
startup from the current RW hour and SF's 24 hours, but nothing checked a gap
while HA was running.

DWD's archive (CDC `RW-hdf5-261013`, `SF-hdf5-261013`) for that day shows:

- RW and SF had data for Berlin Mitte throughout the gap, and every hour was
  0.0 mm, so that outage did not hide a reset there.
- RADOLAN lost Proetzel too, but only in some runs: the :00 and :30 RW runs
  from 11:30 to 16:30 have a hole of 3731 cells up to ~90 km around the radar,
  reaching to 28 km from Berlin Mitte; some :10 runs a smaller one; the :20,
  :40 and :50 runs and SF are complete. RW can therefore fill an RS gap where
  its own runs have the cell, and has none where they do not.

## Decision

- The sensor keeps `watched_until`, the end of the newest hour the source
  reported. A new reading whose hour starts after it left time unwatched: the
  RW clock hours overlapping that stretch (`unwatched_hours`) are fetched from
  OpenData in the background, and one at or above the threshold moves
  `dry_since` to its end. A gap shorter than the source's hour needs nothing,
  since the new reading covers it.
- `watched_until` and the hours still to fetch are stored with the anchor, so
  a downtime is a gap like any other, and a restart resumes the check. The
  startup correction from RW/SF stays as it was.
- Only RW, as far back as OpenData keeps it (the latest hour and the 47
  before it, the same window as the RW total's backfill). Newest first; an
  hour leaves the list once fetched; the first failure ends the round, and
  only a new reading retries.

## Alternatives turned down

- **RW and SF on recovery only** (the issue's proposal: run the startup
  correction when the source returns). The current RW hour covers only the
  last hour of a longer gap, and SF can only place rain to within a day:
  a six-hour gap with rain in it would move `dry_since` to about 24 hours back.
  It also mixes in a 24-hour total compared against an hourly threshold.
- **Listening to RW's releases during the gap.** Accurate to the hour too, but
  it needs the sensor subscribed to a second coordinator, misses the hours RW
  itself failed to fetch, and does nothing for a downtime. Fetching the hours
  afterwards covers all three with the mechanism the totals already use.
- **Treating unknown as wet.** Any outage would reset a long dry streak.
