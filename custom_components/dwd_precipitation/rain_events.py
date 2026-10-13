"""Domain logic for the ``rain_events`` attribute (schema 1).

Splits the rain around one location into events and keeps each event's id
stable from the first forecast that shows it until it has fallen, so that
blueprints can warn about a burst of rain and follow it as forecast turns into
measurement. Everything here is a measurement that needs no threshold except
the one that decides where rain is (``rain_event_threshold``); levels,
warnings and messages are the blueprint's.

Steps are 5 minutes, named by their end time. The *measured* step ending at T
is the RV analysis (lead 0) of release T; each release holds exactly one, so
the integration keeps them itself and fills the ones it missed later
(products.py). Forecast steps are leads 5..120 of the current release.

The state keeps every measured step from the start of the oldest ongoing event
(and at least the last hour), so an event's amounts are recomputed from its
own steps on every release rather than accumulated: a step filled late is
simply there next time, and nothing can be counted twice.

Pure and HA-free like dry_streak.py / precipitation_total.py: the coordinator
owns fetching, filling and persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

SCHEMA = 1

STEP = timedelta(minutes=5)
STEPS_PER_HOUR = 12
WINDOW_STEPS = STEPS_PER_HOUR  # measured steps published: the hour ending at T
FORECAST_STEPS = 24  # leads 5..120
PAIR_STEPS = 2
MM_DECIMALS = 3

# An upcoming event continues as the run whose window overlaps its own,
# widened by this much on either side.
MATCH_SLACK = timedelta(minutes=10)

# Unknown steps bridge rain on either side of them, but not forever: after a
# downtime this long an event is over, whatever fell meanwhile. 3 h covers a
# restart or a DWD outage mid-storm, and keeps a multi-day outage from gluing
# tomorrow's rain onto last week's event.
MAX_UNKNOWN_BRIDGE = 36

WET, DRY, UNKNOWN = "wet", "dry", "unknown"
UPCOMING, ONGOING, UNSEEN = "upcoming", "ongoing", "unseen"

# The keys of the published view (see update), each a state attribute of the
# "Rain events" sensor.
VIEW_KEYS = (
    "schema",
    "base",
    "wet_step_mm",
    "steps_start",
    "steps",
    "history_complete",
    "events",
    "last_ended",
)

# The sensor's state when no event is upcoming or ongoing.
NO_EVENT = "none"



def wet_step_milli(threshold_mmh: float) -> int:
    """Return the wet-step threshold in thousandths of a mm per 5-minute step.

    ``floor(threshold / 12)`` at the data's 0.001 mm resolution, computed in
    integers so float noise cannot move it. Because amounts are whole
    thousandths, "more than this many thousandths" selects exactly the steps
    above ``threshold / 12``.
    """
    return int(round(threshold_mmh * 1000)) // STEPS_PER_HOUR


def is_wet(value: float | None, milli: int) -> bool:
    """Return whether a 5-minute amount counts as rain (strictly above)."""
    return value is not None and round(value * 1000) > milli


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _parse(raw: str | None) -> datetime | None:
    return datetime.fromisoformat(raw) if raw else None


def _mm(value: float) -> float:
    return round(value + 0.0, MM_DECIMALS)


@dataclass
class RainEventsState:
    """Everything the tracker needs across releases (and restarts)."""

    # T of the last processed release.
    base: datetime | None = None
    # wet_step_milli the events were split with; a change drops them.
    wet_milli: int | None = None
    # Measured steps by end time; None = unknown (missed, or no data).
    measured: dict[datetime, float | None] = field(default_factory=dict)
    # Steps fetched and found without data for the cell: not worth refetching.
    nodata: set[datetime] = field(default_factory=set)
    # Upcoming, ongoing and unseen events (internal records).
    events: list[dict[str, Any]] = field(default_factory=list)
    last_ended: dict[str, Any] | None = None
    # (start, end) of ended events still in view, so their rain is not
    # picked up again as a new event.
    ended_spans: list[tuple[datetime, datetime]] = field(default_factory=list)
    # The attribute as last published.
    view: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize for homeassistant.helpers.storage.Store."""
        start = min(self.measured) if self.measured else None
        steps = []
        if start is not None:
            t = start
            while t <= max(self.measured):
                steps.append(self.measured.get(t))
                t += STEP
        return {
            "base": _iso(self.base),
            "wet_milli": self.wet_milli,
            "measured_start": _iso(start),
            "measured": steps,
            "nodata": sorted(_iso(t) for t in self.nodata),
            "events": [_event_to_json(e) for e in self.events],
            "last_ended": self.last_ended,
            "ended_spans": [[_iso(a), _iso(b)] for a, b in self.ended_spans],
            "view": self.view,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RainEventsState:
        """Rebuild the state saved by :meth:`as_dict`."""
        measured: dict[datetime, float | None] = {}
        if (start := _parse(raw.get("measured_start"))) is not None:
            for i, value in enumerate(raw.get("measured") or []):
                measured[start + i * STEP] = value
        return cls(
            base=_parse(raw.get("base")),
            wet_milli=raw.get("wet_milli"),
            measured=measured,
            nodata={_parse(t) for t in raw.get("nodata") or []},
            events=[_event_from_json(e) for e in raw.get("events") or []],
            last_ended=raw.get("last_ended"),
            ended_spans=[
                (_parse(a), _parse(b)) for a, b in raw.get("ended_spans") or []
            ],
            view=raw.get("view"),
        )


_EVENT_TIMES = ("first_seen", "start", "end", "last_wet")


def _event_to_json(event: dict[str, Any]) -> dict[str, Any]:
    return {k: _iso(v) if k in _EVENT_TIMES else v for k, v in event.items()}


def _event_from_json(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: _parse(v) if k in _EVENT_TIMES else v for k, v in raw.items()}


# ---------------------------------------------------------------------------
# Filling missed measured steps
# ---------------------------------------------------------------------------


def window_start(base: datetime) -> datetime:
    """Return the end of the oldest published measured step (T - 55 min)."""
    return base - (WINDOW_STEPS - 1) * STEP


def steps_to_fill(state: RainEventsState, base: datetime) -> list[datetime]:
    """Return the unknown measured steps before ``base`` worth fetching, newest first.

    Only the published window can be filled: a step that has left it no longer
    changes anything. A step whose release had no data for the cell is not
    refetched.
    """
    t = base - STEP
    out = []
    while t >= window_start(base):
        if state.measured.get(t) is None and t not in state.nodata:
            out.append(t)
        t -= STEP
    return out


def record_measured(
    state: RainEventsState, step_end: datetime, value: float | None
) -> None:
    """Store a measured step; ``None`` means the release had no data for the cell."""
    if value is None:
        state.measured[step_end] = None
        state.nodata.add(step_end)
    else:
        state.measured[step_end] = _mm(value)
        state.nodata.discard(step_end)


# ---------------------------------------------------------------------------
# The timeline: measured history, then the current forecast
# ---------------------------------------------------------------------------


@dataclass
class _Timeline:
    first_end: datetime  # end of step 0
    values: list[float | None]
    kinds: list[str]
    last_measured: int  # index of the step ending at T

    def end(self, i: int) -> datetime:
        return self.first_end + i * STEP

    def start(self, i: int) -> datetime:
        return self.end(i) - STEP

    @property
    def series_start(self) -> int:
        return self.last_measured - (WINDOW_STEPS - 1)

    @property
    def last(self) -> int:
        return len(self.values) - 1

    def final_unknown(self, i: int) -> bool:
        """Whether step ``i`` is unknown and has left the window for good.

        It can no longer be filled: it still bridges rain, but counts as dry
        for ending an event. Forecast steps are never unknown.
        """
        return self.kinds[i] == UNKNOWN and i < self.series_start


def _keep_from(state: RainEventsState, base: datetime) -> datetime:
    """Return the oldest measured step still needed."""
    keep = window_start(base)
    for event in state.events:
        if event["status"] != ONGOING:
            continue
        # Two steps before the start decide whether it is clipped.
        keep = min(keep, event["start"] - STEP)
        if (onset := event.get("onset")) is not None:
            keep = min(keep, _parse(onset["base"]) + STEP)
    return keep


def _build_timeline(
    state: RainEventsState,
    base: datetime,
    forecast: list[float | None],
    milli: int,
) -> _Timeline:
    first = _keep_from(state, base)
    values: list[float | None] = []
    kinds: list[str] = []

    t = first
    while t <= base:
        value = state.measured.get(t)
        values.append(value)
        kinds.append(
            UNKNOWN if value is None else WET if is_wet(value, milli) else DRY
        )
        t += STEP
    last_measured = len(values) - 1

    for value in forecast:
        values.append(value)
        # A forecast step without data (coverage edge) counts as dry.
        kinds.append(WET if is_wet(value, milli) else DRY)

    return _Timeline(first, values, kinds, last_measured)


def _runs(tl: _Timeline) -> list[tuple[int, int]]:
    """Return the (first wet, last wet) index of every run of rain.

    Two consecutive dry steps end a run; a single one does not. An unknown
    step never ends one: it might have been wet. More than
    MAX_UNKNOWN_BRIDGE of them in a row count as dry.
    """
    runs: list[tuple[int, int]] = []
    first = last = None
    dry = unknown = 0
    for i, kind in enumerate(tl.kinds):
        if kind == UNKNOWN:
            unknown += 1
            if unknown <= MAX_UNKNOWN_BRIDGE:
                dry = 0
                continue
            kind = DRY
        else:
            unknown = 0
        if kind == WET:
            if first is None:
                first = i
            last = i
            dry = 0
        elif first is not None:
            dry += 1
            if dry >= 2:
                runs.append((first, last))
                first = last = None
                dry = 0
    if first is not None:
        runs.append((first, last))
    return runs


# ---------------------------------------------------------------------------
# Amounts and peaks
# ---------------------------------------------------------------------------


def _peak(tl: _Timeline, lo: int, hi: int, width: int) -> dict[str, Any] | None:
    """Return the wettest ``width`` consecutive steps within [lo, hi].

    A part shorter than ``width`` is its own only window. Ties go to the
    earlier window. Unknown steps count as 0.
    """
    if hi < lo:
        return None
    width = min(width, hi - lo + 1)
    best: tuple[float, int] | None = None
    for i in range(lo, hi - width + 2):
        total = _mm(sum(tl.values[k] or 0.0 for k in range(i, i + width)))
        if best is None or total > best[0]:
            best = (total, i)
    mm, i = best
    return {"mm": mm, "start": _iso(tl.start(i)), "end": _iso(tl.end(i + width - 1))}


def _block(tl: _Timeline, lo: int, hi: int) -> dict[str, Any]:
    """Return {mm, peak_1h, peak_10min} for the steps [lo, hi] (may be empty)."""
    if hi < lo:
        return {"mm": 0.0, "peak_1h": None, "peak_10min": None}
    return {
        "mm": _mm(sum(tl.values[k] or 0.0 for k in range(lo, hi + 1))),
        "peak_1h": _peak(tl, lo, hi, STEPS_PER_HOUR),
        "peak_10min": _peak(tl, lo, hi, PAIR_STEPS),
    }


def _total_peak_1h(tl: _Timeline, first: int, last: int) -> dict[str, Any] | None:
    """Return the wettest hour of the published series that overlaps the event.

    Rain outside the event counts: DWD's heavy-rain criterion is the amount
    within an hour, so two cells close together add up. Only whole windows
    of the series are considered.
    """
    # The windows starting in [lo, hi] are the whole ones that overlap it.
    lo = max(tl.series_start, first - STEPS_PER_HOUR + 1)
    hi = min(last, tl.last - STEPS_PER_HOUR + 1)
    if hi < lo:
        return None
    return _peak(tl, lo, hi + STEPS_PER_HOUR - 1, STEPS_PER_HOUR)


def _onset_view(
    snapshot: dict[str, Any] | None, state: RainEventsState, base: datetime
) -> dict[str, Any] | None:
    """Return the published forecast_at_onset, with the like-for-like sums.

    Both sums run over the steps measured since the snapshot, and stop where
    its 2-hour forecast does.
    """
    if snapshot is None:
        return None
    snap_base = _parse(snapshot["base"])
    expected = observed = 0.0
    for k, value in enumerate(snapshot["forecast"]):
        t = snap_base + (k + 1) * STEP
        if t > base:
            break
        expected += value or 0.0
        observed += state.measured.get(t) or 0.0
    return {
        "base": snapshot["base"],
        "start": snapshot["start"],
        "end": snapshot["end"],
        "mm": snapshot["mm"],
        "peak_1h": snapshot["peak_1h"],
        "peak_10min": snapshot["peak_10min"],
        "expected_so_far_mm": _mm(expected),
        "observed_so_far_mm": _mm(observed),
    }


def _start_clipped(tl: _Timeline, first: int) -> bool:
    """Whether rain may have started before ``first``.

    The start is certain only after two known dry steps; anything else before
    it (unknown, or older than what is held) might have been rain.
    """
    if first > tl.last_measured:
        return False  # a forecast start
    if first < 2:
        return True
    return any(
        tl.kinds[k] != DRY or tl.final_unknown(k) for k in (first - 1, first - 2)
    )


# ---------------------------------------------------------------------------
# One release
# ---------------------------------------------------------------------------


def _new_event(event_id: str, base: datetime) -> dict[str, Any]:
    return {
        "id": event_id,
        "first_seen": base,
        "status": UPCOMING,
        "start": None,
        "end": None,
        "last_wet": None,
        "absorbed": [],
        "candidate": None,
        "onset": None,
        "onset_frozen": False,
        "view": None,
    }


def _merge_into(survivor: dict[str, Any], others: list[dict[str, Any]]) -> None:
    """Fold merged events into the one first seen earliest."""
    for other in others:
        for absorbed in [other["id"], *other["absorbed"]]:
            if absorbed not in survivor["absorbed"]:
                survivor["absorbed"].append(absorbed)
        # Keep whatever forecast the merged rain was announced with.
        if survivor["candidate"] is None and other["candidate"] is not None:
            survivor["candidate"] = other["candidate"]
        if survivor["onset"] is None and other["onset"] is not None:
            survivor["onset"] = other["onset"]
            survivor["onset_frozen"] = True


def _match(
    events: list[dict[str, Any]], runs: list[tuple[int, int]], tl: _Timeline
) -> dict[int, list[dict[str, Any]]]:
    """Return, per run index, the events that continue as that run."""
    by_run: dict[int, list[dict[str, Any]]] = {i: [] for i in range(len(runs))}
    for event in events:
        candidates = []
        for i, (first, last) in enumerate(runs):
            if event["status"] == ONGOING:
                # It continues as the run holding its last measured rain.
                hit = (
                    event["last_wet"] is not None
                    and tl.end(first) <= event["last_wet"] <= tl.end(last)
                )
            else:
                hit = (
                    event["start"] - MATCH_SLACK < tl.end(last)
                    and tl.start(first) < event["end"] + MATCH_SLACK
                )
            if hit:
                candidates.append(i)
        # A split: the earliest run keeps the id, later ones get new ids.
        if candidates:
            by_run[candidates[0]].append(event)
    return by_run


def _ended_record(
    event: dict[str, Any],
    tl: _Timeline,
    state: RainEventsState,
    base: datetime,
    first: int,
    last_wet: int,
    end_clipped: bool,
) -> dict[str, Any]:
    missing = sum(1 for k in range(first, last_wet + 1) if tl.values[k] is None)
    start_clipped = _start_clipped(tl, first)
    return {
        "id": event["id"],
        "first_seen": _iso(event["first_seen"]),
        "start": _iso(tl.start(first)),
        "start_clipped": start_clipped,
        "end": _iso(tl.end(last_wet)),
        "end_clipped": end_clipped,
        "missing_steps": missing,
        "observed_complete": missing == 0 and not start_clipped and not end_clipped,
        "observed": _block(tl, first, last_wet),
        "forecast_at_onset": _onset_view(event["onset"], state, base),
        "absorbed": list(event["absorbed"]),
    }


def update(
    state: RainEventsState,
    base: datetime,
    analysis: float | None,
    forecast: list[float | None],
    milli: int,
) -> dict[str, Any]:
    """Process release ``base`` and return the ``rain_events`` attribute.

    ``analysis`` is the measured step ending at ``base`` (None for no data),
    ``forecast`` the 24 forecast steps ending at base+5..base+120. Fill the
    missed measured steps (steps_to_fill / record_measured) *before* calling
    this: a lost release must never cause an unseen event, a split or an end.
    """
    if (
        state.base is not None
        and base == state.base
        and state.view is not None
        and state.wet_milli == milli
    ):
        # The same release again: nothing has changed. Not after a threshold
        # change, though: an options change reloads the entry, whose first
        # refresh is this very release.
        return state.view
    if state.base is not None and base < state.base:
        state.events = []  # the clock went backwards; ids could repeat
    if state.wet_milli != milli:
        # A new threshold splits rain differently: start over with new ids,
        # keeping the facts (measured steps, the last ended event).
        state.events = []
        state.wet_milli = milli

    record_measured(state, base, analysis)
    state.base = base

    # Drop what is no longer needed before building the timeline.
    keep = _keep_from(state, base)
    state.measured = {t: v for t, v in state.measured.items() if keep <= t <= base}
    state.nodata = {t for t in state.nodata if t >= window_start(base)}

    tl = _build_timeline(state, base, list(forecast), milli)
    state.ended_spans = [
        (a, b) for a, b in state.ended_spans if b > tl.start(0)
    ]
    runs = [
        (first, last)
        for first, last in _runs(tl)
        if not any(
            tl.start(first) < span_end and span_start < tl.end(last)
            for span_start, span_end in state.ended_spans
        )
    ]

    by_run = _match(state.events, runs, tl)
    matched_ids = {e["id"] for evs in by_run.values() for e in evs}
    counter = 0
    survivors: list[tuple[dict[str, Any], int]] = []
    for i in range(len(runs)):
        events = sorted(
            by_run[i], key=lambda e: (e["first_seen"], e["start"], e["id"])
        )
        if events:
            survivor = events[0]
            _merge_into(survivor, events[1:])
        else:
            survivor = _new_event(f"{base:%Y%m%dt%H%M}-{counter}", base)
            counter += 1
        survivors.append((survivor, i))

    # Events no run continues: upcoming ones get one release of grace.
    remaining: list[dict[str, Any]] = []
    newly_ended: list[dict[str, Any]] = []
    for event in state.events:
        if event["id"] in matched_ids:
            continue
        if event["status"] == ONGOING:
            # Cannot happen while its last rain is held; end it rather than
            # lose it.
            newly_ended.append(
                _orphan_record(event)
            )
        elif event["status"] == UPCOMING:
            event["status"] = UNSEEN
            remaining.append(event)
        # An event unseen twice is dropped.

    m = tl.last_measured
    for event, i in survivors:
        first, last = runs[i]
        measured_hi = min(last, m)
        wet_measured = [k for k in range(first, measured_hi + 1) if tl.kinds[k] == WET]
        forecast_block = _block(tl, max(first, m + 1), last)

        if not wet_measured:
            event["status"] = UPCOMING
            event["candidate"] = {
                "base": _iso(base),
                "start": _iso(tl.start(first)),
                "end": _iso(tl.end(last)),
                "mm": forecast_block["mm"],
                "peak_1h": forecast_block["peak_1h"],
                "peak_10min": forecast_block["peak_10min"],
                "forecast": list(forecast),
            }
        else:
            event["status"] = ONGOING
            if not event["onset_frozen"]:
                # The last pure forecast is what users were warned with.
                event["onset"] = event["candidate"]
                event["onset_frozen"] = True
            event["candidate"] = None
        event["start"] = tl.start(first)
        event["end"] = tl.end(last)

        if wet_measured:
            last_wet = wet_measured[-1]
            event["last_wet"] = tl.end(last_wet)
            after = (last_wet + 1, last_wet + 2)
            # Two dry steps end it. An unknown one postpones that until it is
            # filled or has left the window, and then counts as dry.
            if after[1] <= m and all(
                tl.kinds[k] == DRY or tl.final_unknown(k) for k in after
            ):
                newly_ended.append(
                    _ended_record(
                        event,
                        tl,
                        state,
                        base,
                        first,
                        last_wet,
                        end_clipped=any(tl.final_unknown(k) for k in after),
                    )
                )
                state.ended_spans.append((tl.start(first), tl.end(last_wet)))
                continue
        else:
            event["last_wet"] = None

        event["view"] = _event_view(event, tl, state, base, first, last, forecast_block)
        remaining.append(event)

    if newly_ended:
        state.last_ended = max(newly_ended, key=lambda r: r["end"])

    state.events = remaining
    events_view = []
    for event in sorted(remaining, key=lambda e: e["start"]):
        view = dict(event["view"])
        view["status"] = event["status"]
        events_view.append(view)

    steps = tl.values[tl.series_start:]
    state.view = {
        "schema": SCHEMA,
        "base": _iso(base),
        "wet_step_mm": milli / 1000,
        "steps_start": _iso(tl.start(tl.series_start)),
        "steps": steps,
        "history_complete": all(v is not None for v in steps[:WINDOW_STEPS]),
        "events": events_view,
        "last_ended": state.last_ended,
    }
    return state.view


def _orphan_record(event: dict[str, Any]) -> dict[str, Any]:
    """Return an ended record for an ongoing event no run continues.

    Defensive only: an ongoing event's last rain is always held, so it always
    has a run. If it ever has not, publish what was last known rather than
    let it vanish.
    """
    view = event["view"] or {}
    return {
        "id": event["id"],
        "first_seen": _iso(event["first_seen"]),
        "start": view.get("start"),
        "start_clipped": view.get("start_clipped", True),
        "end": _iso(event["last_wet"]),
        "end_clipped": True,
        "missing_steps": view.get("missing_steps", 0),
        "observed_complete": False,
        "observed": view.get("observed", {"mm": 0.0, "peak_1h": None, "peak_10min": None}),
        "forecast_at_onset": view.get("forecast_at_onset"),
        "absorbed": list(event["absorbed"]),
    }


def _event_view(
    event: dict[str, Any],
    tl: _Timeline,
    state: RainEventsState,
    base: datetime,
    first: int,
    last: int,
    forecast_block: dict[str, Any],
) -> dict[str, Any]:
    m = tl.last_measured
    measured_hi = min(last, m)
    observed = _block(tl, first, measured_hi)
    missing = sum(1 for k in range(first, measured_hi + 1) if tl.values[k] is None)
    start_clipped = _start_clipped(tl, first)
    lo = max(first, tl.series_start)
    return {
        "id": event["id"],
        "status": event["status"],
        "first_seen": _iso(event["first_seen"]),
        "start": _iso(tl.start(first)),
        "start_clipped": start_clipped,
        "end": _iso(tl.end(last)),
        "beyond_horizon": last == tl.last,
        "last_wet_observed": _iso(event["last_wet"]),
        "missing_steps": missing,
        "observed_complete": missing == 0 and not start_clipped,
        "observed": observed,
        "forecast": forecast_block,
        "total": {
            "mm": _mm(observed["mm"] + forecast_block["mm"]),
            "peak_1h": _total_peak_1h(tl, first, last),
            "peak_10min": _peak(tl, lo, last, PAIR_STEPS),
        },
        "forecast_at_onset": (
            _onset_view(event["onset"], state, base)
            if event["status"] == ONGOING
            else None
        ),
        "absorbed": list(event["absorbed"]),
    }


def at_stake(state: RainEventsState) -> bool:
    """Whether losing the state now would lose something.

    False on a dry day with nothing pending: the store can then wait for the
    next shutdown instead of being written every 5 minutes.
    """
    if state.events:
        return True
    if state.base is None:
        return False
    # An unknown step may still be filled. A step whose release had no data
    # for the cell is final, like a dry one: it is not refetched, so it must
    # not keep the store writing every release at a coverage edge.
    if steps_to_fill(state, state.base):
        return True
    return any(
        value is not None and is_wet(value, state.wet_milli or 0)
        for t, value in state.measured.items()
        if t >= window_start(state.base)
    )


def overall_status(view: dict[str, Any]) -> str:
    """Return the sensor state for a published view.

    ``ongoing`` if any event is, else ``upcoming`` if any is, else ``none``.
    An ``unseen`` event is one the latest forecast does not show, so it does
    not make rain upcoming on its own.
    """
    statuses = {event.get("status") for event in view.get("events") or ()}
    for status in (ONGOING, UPCOMING):
        if status in statuses:
            return status

    return NO_EVENT
