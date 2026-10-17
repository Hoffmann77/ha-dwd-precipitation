# 0009 — The full rolling-hour series is built from RV

Status: accepted (2026.10.1)

## Context

`full_rolling_series` extends the `forecast_rolling_1h` attribute of
`Peak hourly precipitation next 120 min` by the 12 hours that started before
the release. RS used to feed the sensor with the option on, decoding all 25
members, so RS downloaded its whole archive every 5 minutes instead of reading
three members by range. Measured on the 576 RS archives on OpenData from 11 to
13 Oct 2026, that was 4.6 MB a release against 0.9 MB, about 1.3 GB a day
(0.66 GB on the dry day, 2.1 GB on the wet one), and it doubled an install's
traffic, from about 0.93 to 2.0 GB a day.

Earlier live checks had shown that RS's forecast hours are RV's 5-minute steps
added up. On 13 and 14 Oct 2026, every RS member of two releases (one wet, one
moderate) matched, cell for cell on the whole grid, the sum of the twelve RV
steps in its hour: the RV analyses (`_000`) of the releases up to T, then RV
T's forecast. That includes the members whose hour started before T. A missing
step counts as 0, and RS has no data exactly where all twelve steps have none.

## Decision

RV builds the whole series. It keeps the analysis of each release it adopts
for an hour, in memory, and with the option on adds the 12 earlier windows
from them. RS always reads its three members by range. A live test
(`test_live_rs_is_summed_rv`) checks the identity daily.

The 12 points appear only when all 11 earlier analyses are known. Missed ones
are not fetched, so after a restart, or a release that was never adopted, the
series has the 13 future points for up to an hour.

## Alternatives

- Fetch the missed analyses in a background round, as the rain-events tracker
  does: a complete series right after a restart, for about 2 MB and the
  ordering care such a round needs. Not worth it for an attribute that is not
  recorded.
- Keep RS for the series, reading only members `_000`–`_055` (the first 12,
  about half the archive) by range: halves the cost instead of removing it.
- Drop RS altogether and build `Precipitation last 60 min` from RV's analyses
  too, about 260 MB a day less. Not done: it changes the source of released
  sensors, and would make them depend on RV and on an hour of history.

## Consequences

With the option on, an install downloads what it does with the option off,
and RS no longer decodes 25 members a release. The option no longer changes
the peak's value, window or future points: they come from RV either way. An
install that had the option on read them from RS before, so in the rare cells
where DWD's RS and summed RV differ (see the later measurement below) its
peak may move slightly with this change. If DWD stops publishing RS as summed RV, the live
test fails; the series' first point and `Precipitation last 60 min` would then
disagree.

## Later measurement (17 Oct 2026)

The identity is not exact on every release. Twelve releases 4 h apart from
15 to 17 Oct matched in every cell while dry. On the wet morning of 17 Oct,
48 consecutive releases of RS lead 0 matched summed RV exactly in 98.2 to
100 % of the wet cells; at most 0.44 % differed by more than 0.01 mm and
0.11 % by more than 0.05 mm, the largest by 0.54 mm. A step that differs stays
in the sums for the hour it covers. The forecast leads deviate the same way,
less often. RS and RV never disagreed about which cells have data.

The decision stands: the deviations are DWD's own, in a percent or two of the
wet cells, on an attribute that is not recorded. The live test checks the
identity by its share rather than exactly (the same cells have data, and at
least 90 % of wet cells match), so DWD's deviations do not fail it and a
systematic change, which would put most wet cells off, still does.
