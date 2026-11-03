# 0012 — Rain events have a precipitation type only once it is measured

Status: accepted (2026.11.0)

## Context

A contributor's pull request (#103) added a rain warning that names the type
of precipitation coming, and, when the location's own cell had none, the type
of the nearest precipitation within 5 km. The type is worth having in Rain
events: a blueprint can report snow, graupel or hail rather than just "rain".

What DWD offers for it:

- **HymecNG**, the precipitation-type classification the integration already
  reads, is one file per 5 minutes for a single moment (`startdate` equals
  `enddate`). It has no forecast. OpenData keeps 48 hours of it (577 files on
  2026-10-21).
- **RADVOR** (RV, RS) forecasts amounts, not types.
- Forecast types exist only in ICON-D2 (GRIB2, which needs eccodes, a
  dependency the integration does not take) and MOSMIX (point forecasts for
  stations, hourly): other products on other scales, not a type for a 5-minute
  nowcast step.

## Decision

- Every measured step gets the HymecNG type of the moment it ends, that is of
  the HymecNG release at the same time as the RV release whose analysis it is.
  The HymecNG coordinator hands each release it adopts to the tracker, usually
  before RV adopts the same release (HymecNG is fetched at 3 min, RV at
  4 min 10 s, each plus at most 30 s of jitter). The tracker keeps the types
  by step time, so the order in which the two arrive does not matter, and a
  type that arrives after RV shows from the next release on, as the events are
  recomputed every release (ADR 0006).
- A missed type is fetched in the same background round as missed analyses,
  after them, since only then is it known which steps are wet: only wet steps,
  only within the published hour, newest first, with the same budget.
- Published as `observed.types` (wet measured steps per type) and `type` (the
  latest wet measured step's), on ongoing and ended events. The types are
  DWD's as they are: a wet step HymecNG calls `no_precipitation` is counted as
  that. A wet step without a type is not counted.
- **Nothing is estimated.** An upcoming event has `type: null`. The type of a
  neighbouring cell, a regional summary, a rule on temperature, or the type
  carried over from the last event are all not used.
- The view stays `schema: 1`, since fields are only added, and the store stays
  version 1: a state stored before reads as no type known.

## Consequences

- No warning about the type before the rain arrives can come from this
  integration. A blueprint can combine Rain events with sources of its own
  (a weather entity, a temperature sensor), on its own responsibility.
- The type appears with the first measured wet step, within about 5 minutes
  of the rain starting.
- The store holds one label per step for as long as it holds the measured
  steps, dry steps included, since a type arrives before it is known whether
  its step is wet.

## Alternatives turned down

- **The nearest type within 5 km** (#103). Rain due in an hour is usually
  tens of kilometres away, and the nearest cell need not be the one heading
  for the location.
- **The most common type of the wet cells within 30-50 km.** Plausible, as
  the type depends mostly on the temperature profile, which changes slowly,
  but it is an estimate: wrong near the snow line, in hilly terrain, behind a
  front and for hail and graupel, which are local. The integration would be
  answering for its accuracy.
- **ICON-D2 or MOSMIX.** The first needs GRIB2 decoding; the second is a
  station's hourly forecast. Either would be a forecast product of its own,
  not the type of a nowcast event.
- **Reading the HymecNG coordinator's current value when RV's release is
  processed.** Which of the two is adopted first is not guaranteed, and a
  missed HymecNG release could not be told from a late one. Recording by step
  time leaves nothing to race.
