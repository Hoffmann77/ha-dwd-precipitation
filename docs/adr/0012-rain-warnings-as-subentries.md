# 0012 — Rain warnings are subentries that filter the rain-events view

Status: accepted (2026.11.0)

## Context

The `Rain events` sensor (ADR 0006) follows each burst of rain from forecast
to measurement, and left warning levels to blueprints. Most users want only
the warning: "tell me 60 minutes before it rains on the laundry". Building
that from the view takes a blueprint or a template that compares timestamps
and amounts, and has to cope with a forecast that moves every 5 minutes.

Home Assistant 2025.3 added config subentries: user-defined items under an
entry, each with its own flow, entities and devices.

## Decision

- **A rain warning is a config subentry** of a location (`rain_warning`),
  with a name (its title), a lead time (5 to 120 min in steps of 5) and
  optional minimums for the event's total, its wettest hour and its wettest
  10 minutes, combined by "any" or "all". It is changed with the subentry's
  `reconfigure` step, not with a number entity. Its data is read with
  `rain_warning_rule()` against a table of defaults, like `DwdOptions`.
- **No event logic of its own.** A warning is a filter over the rain-events
  view (`radar/rain_warning.py`): `rain` while an ongoing event passes the
  filter, `soon` while an upcoming one that passes it starts within the lead
  time, `dry` otherwise. The amounts compared are the event's `total` block.
  Without a view the state is unknown, not dry.
- **The tracker is built when needed.** It runs for the `rain_events` option
  or for any rain warning (`tracks_rain_events`); the option controls only
  the `Rain events` entity. The store is deleted once neither uses it. This
  replaces the "the option gates all of it" part of ADR 0006: the warnings
  must not depend on an option whose stated purpose is blueprints, and the
  tracker costs no extra download in normal operation (the analysis comes
  with the RV file it already decodes; fills only follow a missed release).
- **Judged per release, not per minute.** A warning is judged when RV brings
  a new view, with the lead time measured from when that release arrived. It
  can turn on up to one release (5 min) late, which is within the 3 to 10
  minutes DWD's publication already costs. A per-minute re-check would write
  a state row every minute for an attribute countdown; the `start` attribute
  is a timestamp instead, which the frontend shows relative.
- **Two memories, in memory.** An event that passed the filter once passes
  until it ends (and the event that absorbs it in a merge inherits that), so
  an ongoing shower whose forecast shrinks does not switch the warning off.
  An event that was `soon` stays `soon` for the one release in which the
  forecast loses it (`unseen`). Both are kept per warning in a `RainWarning`
  that its two entities share and that judges each view once; a restart
  judges events afresh.
- **Two entities on a device of their own.** A binary sensor ("Rain warning",
  on for `rain` or `soon`) and an enum sensor ("Rain warning status", with
  the event's `event_id`, `start`, `mm`, `peak_1h`, `peak_10min` and a
  reserved `type`, all unrecorded). Home Assistant keeps a device in one
  subentry: adding a subentry's entities to the location's device moves that
  device into the subentry, which 2026.x reports and 2027.8 refuses. So each
  warning is a device named after the location and the warning ("Home
  Laundry"), and the entity ids are
  `binary_sensor.<location>_<warning>_rain_warning` and
  `sensor.<location>_<warning>_rain_warning_status`, independent of the UI
  language. Unique ids are `<entry_id>_<subentry_id>_rain_warning` and
  `..._rain_warning_status`.
- **Names are unique per location**, compared as slugs, so two warnings never
  fight over an entity id.
- **Home Assistant 2025.4 or newer** (`hacs.json`): the subentry flow helpers
  it uses (`_get_entry`, `_get_reconfigure_subentry`) have their final names
  from 2025.4.

## Alternatives turned down

- **The warnings on the location's device.** Home Assistant refuses it from
  2027.8 (see above).
- **A per-minute tick with a `starts_in_min` countdown.** About 1,440 state
  rows a day per warning, dry days included, for a value the frontend can
  derive from `start`.
- **A precipitation type from HymecNG's nearby cells.** An estimate; the
  `type` attribute stays `null` until the rain-events view carries a measured
  type.
- **Requiring the `rain_events` option.** It would make users turn on a
  blueprint sensor they do not want, and leave the question of what happens
  to the warnings when it is turned off.
- **Own event logic per warning.** It would duplicate the matching, merging
  and backfill of the tracker, and could disagree with `Rain events`.
