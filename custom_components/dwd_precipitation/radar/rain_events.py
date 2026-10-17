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

Pure and HA-free, like everything in radar/: the coordinator owns fetching,
filling and persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, TypedDict

from .isotime import iso, parse_utc
from .nowcast import LEAD_STEP, LEADS, STEPS_PER_HOUR, round_mm

SCHEMA = 1

STEP = timedelta(minutes=LEAD_STEP)
WINDOW_STEPS = STEPS_PER_HOUR  # measured steps published: the hour ending at T
FORECAST_STEPS = len(LEADS) - 1  # leads 5..120
PAIR_STEPS = 2

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

# The published view, schema 1: a contract with blueprints (README, "Rain
# events"). Timestamps are ISO strings, amounts mm.


class Peak(TypedDict):
    """The wettest window of a given width: its amount and when."""

    mm: float
    start: str
    end: str


class Block(TypedDict):
    """An amount with its wettest hour and wettest 10 minutes."""

    mm: float
    peak_1h: Peak | None
    peak_10min: Peak | None


class OnsetView(TypedDict):
    """The forecast users were warned with, and how it compares so far."""

    base: str
    start: str
    end: str
    mm: float
    peak_1h: Peak | None
    peak_10min: Peak | None
    expected_so_far_mm: float
    observed_so_far_mm: float


class EventView(TypedDict):
    """An upcoming, ongoing or unseen event."""

    id: str
    status: str
    first_seen: str
    start: str
    start_clipped: bool
    end: str
    beyond_horizon: bool
    last_wet_observed: str | None
    missing_steps: int
    observed_complete: bool
    observed: Block
    forecast: Block
    total: Block
    forecast_at_onset: OnsetView | None
    absorbed: list[str]


class EndedRecord(TypedDict):
    """An event that has ended: final."""

    id: str
    first_seen: str
    start: str | None
    start_clipped: bool
    end: str | None
    end_clipped: bool
    missing_steps: int
    observed_complete: bool
    observed: Block
    forecast_at_onset: OnsetView | None
    absorbed: list[str]


class RainEventsView(TypedDict):
    """The attributes of the Rain events sensor."""

    schema: int
    base: str
    wet_step_mm: float
    steps_start: str
    steps: list[float | None]
    history_complete: bool
    events: list[EventView]
    last_ended: EndedRecord | None


# Each a state attribute of the "Rain events" sensor.
VIEW_KEYS = tuple(RainEventsView.__annotations__)

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


def is_wet(value: float | None, wet_milli: int) -> bool:
    """Return whether a 5-minute amount counts as rain (strictly above)."""
    return value is not None and round(value * 1000) > wet_milli


def _parse(raw: str | None) -> datetime | None:
    """Parse a stored timestamp (UTC); raise on one that cannot be read.

    Raising, unlike parse_utc, is what makes an unreadable store be discarded
    as a whole rather than half restored.
    """
    if not raw:
        return None
    if (ts := parse_utc(raw)) is None:
        raise ValueError(f"unreadable timestamp {raw!r}")
    return ts


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
    last_ended: EndedRecord | None = None
    # (start, end) of ended events still in view, so their rain is not
    # picked up again as a new event.
    ended_spans: list[tuple[datetime, datetime]] = field(default_factory=list)
    # The attribute as last published.
    view: RainEventsView | None = None

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
            "base": iso(self.base),
            "wet_milli": self.wet_milli,
            "measured_start": iso(start),
            "measured": steps,
            "nodata": sorted(iso(t) for t in self.nodata),
            "events": [_event_to_json(e) for e in self.events],
            "last_ended": self.last_ended,
            "ended_spans": [[iso(a), iso(b)] for a, b in self.ended_spans],
            "view": self.view,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RainEventsState:
        """Rebuild the state saved by :meth:`as_dict`.

        Raises ValueError (or TypeError) for anything update() could not work
        with, so a damaged or foreign store is discarded as a whole when it is
        loaded, rather than failing every release after it.
        """
        measured: dict[datetime, float | None] = {}
        if (start := _parse(raw.get("measured_start"))) is not None:
            for i, value in enumerate(raw.get("measured") or []):
                measured[start + i * STEP] = _amount(value)
        return cls(
            base=_parse(raw.get("base")),
            wet_milli=_optional(raw.get("wet_milli"), int, "wet_milli"),
            measured=measured,
            nodata={_required_time(t) for t in raw.get("nodata") or []},
            events=[_event_from_json(e) for e in raw.get("events") or []],
            last_ended=_optional(raw.get("last_ended"), dict, "last_ended"),
            ended_spans=[
                (_required_time(a), _required_time(b))
                for a, b in raw.get("ended_spans") or []
            ],
            view=_optional(raw.get("view"), dict, "view"),
        )


_EVENT_TIMES = ("first_seen", "start", "end", "last_wet")

# Every field of an event record (see _new_event). A stored record must have
# them all: update() reads each one on every release.
_EVENT_FIELDS = (
    "id",
    "first_seen",
    "status",
    "start",
    "end",
    "last_wet",
    "absorbed",
    "candidate",
    "onset",
    "onset_frozen",
    "view",
)

# What a forecast snapshot (an event's candidate or onset) holds.
_SNAPSHOT_FIELDS = ("base", "start", "end", "mm", "peak_1h", "peak_10min", "forecast")


def _optional(value: Any, kind: type, name: str) -> Any:
    """Return ``value`` if it is None or a ``kind``; raise otherwise."""
    if value is not None and not isinstance(value, kind):
        raise ValueError(f"{name} is {type(value).__name__}, not {kind.__name__}")
    return value


def _amount(value: Any) -> float | None:
    """Return a stored step amount, which must be a number or None."""
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, (int, float))
    ):
        raise ValueError(f"step amount {value!r}")
    return value


def _required_time(raw: Any) -> datetime:
    """Parse a stored timestamp that must be there."""
    if (ts := _parse(raw)) is None:
        raise ValueError("missing timestamp")
    return ts


def _snapshot(raw: Any) -> dict[str, Any] | None:
    """Check a stored forecast snapshot (candidate / onset)."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or not set(_SNAPSHOT_FIELDS) <= raw.keys():
        raise ValueError("incomplete forecast snapshot")
    _required_time(raw["base"])
    if not isinstance(raw["forecast"], list):
        raise ValueError("snapshot forecast is not a list")
    return raw


def _event_to_json(event: dict[str, Any]) -> dict[str, Any]:
    return {k: iso(event[k]) if k in _EVENT_TIMES else event[k] for k in _EVENT_FIELDS}


def _event_from_json(raw: Any) -> dict[str, Any]:
    """Rebuild a stored event record, checking everything update() relies on.

    Fields of an older format that update() no longer reads are dropped.
    """
    if not isinstance(raw, dict) or not set(_EVENT_FIELDS) <= raw.keys():
        raise ValueError("incomplete event record")
    if raw["status"] not in (UPCOMING, ONGOING, UNSEEN):
        raise ValueError(f"event status {raw['status']!r}")
    if not isinstance(raw["id"], str) or not isinstance(raw["absorbed"], list):
        raise ValueError("event id or absorbed ids")
    if not isinstance(raw["view"], dict):
        raise ValueError("event without a view")
    event = {
        k: _parse(raw[k]) if k in _EVENT_TIMES else raw[k] for k in _EVENT_FIELDS
    }
    for k in ("first_seen", "start", "end"):
        if event[k] is None:
            raise ValueError(f"event without {k}")
    event["onset_frozen"] = bool(event["onset_frozen"])
    event["candidate"] = _snapshot(event["candidate"])
    event["onset"] = _snapshot(event["onset"])
    return event


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
        state.measured[step_end] = round_mm(value)
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
            keep = min(keep, _required_time(onset["base"]) + STEP)
    return keep


def _build_timeline(
    state: RainEventsState,
    base: datetime,
    forecast: list[float | None],
    wet_milli: int,
) -> _Timeline:
    first = _keep_from(state, base)
    values: list[float | None] = []
    kinds: list[str] = []

    t = first
    while t <= base:
        value = state.measured.get(t)
        values.append(value)
        kinds.append(
            UNKNOWN if value is None else WET if is_wet(value, wet_milli) else DRY
        )
        t += STEP
    last_measured = len(values) - 1

    for value in forecast:
        values.append(value)
        # A forecast step without data (coverage edge) counts as dry.
        kinds.append(WET if is_wet(value, wet_milli) else DRY)

    return _Timeline(first, values, kinds, last_measured)


def _runs(timeline: _Timeline) -> list[tuple[int, int]]:
    """Return the (first wet, last wet) index of every run of rain.

    Two consecutive dry steps end a run; a single one does not. An unknown
    step never ends one: it might have been wet. More than
    MAX_UNKNOWN_BRIDGE of them in a row count as dry.
    """
    runs: list[tuple[int, int]] = []
    first: int | None = None
    last = 0  # set together with first
    dry = unknown = 0
    for i, kind in enumerate(timeline.kinds):
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
                first = None
                dry = 0
    if first is not None:
        runs.append((first, last))
    return runs


# ---------------------------------------------------------------------------
# Amounts and peaks
# ---------------------------------------------------------------------------


def _sum_mm(timeline: _Timeline, first: int, last: int) -> float:
    """Return the rain in the steps [first, last]; an unknown step counts as 0."""
    return round_mm(sum(timeline.values[step] or 0.0 for step in range(first, last + 1)))


def _peak(timeline: _Timeline, first: int, last: int, width: int) -> Peak | None:
    """Return the wettest ``width`` consecutive steps within [first, last].

    A part shorter than ``width`` is its own only window. Ties go to the
    earlier window. Unknown steps count as 0.
    """
    if last < first:
        return None
    width = min(width, last - first + 1)
    # max() keeps the first of equal totals: the earlier window.
    mm, start = max(
        (
            (_sum_mm(timeline, start, start + width - 1), start)
            for start in range(first, last - width + 2)
        ),
        key=lambda total_at: total_at[0],
    )
    return {
        "mm": mm,
        "start": iso(timeline.start(start)),
        "end": iso(timeline.end(start + width - 1)),
    }


def _block(timeline: _Timeline, first: int, last: int) -> Block:
    """Return {mm, peak_1h, peak_10min} for the steps [first, last] (may be empty)."""
    if last < first:
        return {"mm": 0.0, "peak_1h": None, "peak_10min": None}
    return {
        "mm": _sum_mm(timeline, first, last),
        "peak_1h": _peak(timeline, first, last, STEPS_PER_HOUR),
        "peak_10min": _peak(timeline, first, last, PAIR_STEPS),
    }


def _total_peak_1h(timeline: _Timeline, first: int, last: int) -> Peak | None:
    """Return the wettest hour of the published series that overlaps the event.

    Rain outside the event counts: DWD's heavy-rain criterion is the amount
    within an hour, so two cells close together add up. Only whole windows
    of the series are considered.
    """
    # The whole windows that overlap the event start in [first_start, last_start].
    first_start = max(timeline.series_start, first - STEPS_PER_HOUR + 1)
    last_start = min(last, timeline.last - STEPS_PER_HOUR + 1)
    if last_start < first_start:
        return None
    return _peak(timeline, first_start, last_start + STEPS_PER_HOUR - 1, STEPS_PER_HOUR)


def _onset_view(
    snapshot: dict[str, Any] | None, state: RainEventsState, base: datetime
) -> OnsetView | None:
    """Return the published forecast_at_onset, with the like-for-like sums.

    Both sums run over the steps measured since the snapshot, and stop where
    its 2-hour forecast does.
    """
    if snapshot is None:
        return None
    snap_base = _required_time(snapshot["base"])
    expected = observed = 0.0
    for steps_ahead, value in enumerate(snapshot["forecast"], start=1):
        t = snap_base + steps_ahead * STEP
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
        "expected_so_far_mm": round_mm(expected),
        "observed_so_far_mm": round_mm(observed),
    }


def _start_clipped(timeline: _Timeline, first: int) -> bool:
    """Whether rain may have started before ``first``.

    The start is certain only after two known dry steps; anything else before
    it (unknown, or older than what is held) might have been rain.
    """
    if first > timeline.last_measured:
        return False  # a forecast start
    if first < 2:
        return True
    return any(
        timeline.kinds[step] != DRY or timeline.final_unknown(step)
        for step in (first - 1, first - 2)
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
    events: list[dict[str, Any]], runs: list[tuple[int, int]], timeline: _Timeline
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
                    and timeline.end(first) <= event["last_wet"] <= timeline.end(last)
                )
            else:
                hit = (
                    event["start"] - MATCH_SLACK < timeline.end(last)
                    and timeline.start(first) < event["end"] + MATCH_SLACK
                )
            if hit:
                candidates.append(i)
        # A split: the earliest run keeps the id, later ones get new ids.
        if candidates:
            by_run[candidates[0]].append(event)
    return by_run


def _missing(timeline: _Timeline, first: int, last: int) -> int:
    """Return how many of the steps [first, last] are unknown."""
    return sum(1 for step in range(first, last + 1) if timeline.values[step] is None)


def _rain_ended_after(timeline: _Timeline, last_wet: int) -> bool:
    """Whether the two measured steps after ``last_wet`` end the rain.

    Two dry steps end it. An unknown one postpones that until it is filled or
    has left the window, and then counts as dry.
    """
    after = (last_wet + 1, last_wet + 2)
    return after[1] <= timeline.last_measured and all(
        timeline.kinds[step] == DRY or timeline.final_unknown(step) for step in after
    )


def _ended_record(
    event: dict[str, Any],
    timeline: _Timeline,
    state: RainEventsState,
    base: datetime,
    first: int,
    last_wet: int,
) -> EndedRecord:
    """Return the final record of an event whose rain ended at ``last_wet``."""
    missing = _missing(timeline, first, last_wet)
    start_clipped = _start_clipped(timeline, first)
    # An unknown step that counted as dry to end it might have been rain.
    end_clipped = any(timeline.final_unknown(step) for step in (last_wet + 1, last_wet + 2))
    return {
        "id": event["id"],
        "first_seen": iso(event["first_seen"]),
        "start": iso(timeline.start(first)),
        "start_clipped": start_clipped,
        "end": iso(timeline.end(last_wet)),
        "end_clipped": end_clipped,
        "missing_steps": missing,
        "observed_complete": missing == 0 and not start_clipped and not end_clipped,
        "observed": _block(timeline, first, last_wet),
        "forecast_at_onset": _onset_view(event["onset"], state, base),
        "absorbed": list(event["absorbed"]),
    }


def update(
    state: RainEventsState,
    base: datetime,
    analysis: float | None,
    forecast: list[float | None],
    wet_milli: int,
) -> RainEventsView:
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
        and state.view.get("schema") == SCHEMA
        and state.wet_milli == wet_milli
    ):
        # The same release again (a refresh, or a restart within one release):
        # nothing has changed, and processing it twice is not harmless (an
        # unmatched upcoming event would go unseen, then be dropped). Not
        # after a threshold change, though: an options change reloads the
        # entry, whose first refresh is this very release. The stored view is
        # also why a restart can answer here at all.
        return state.view

    _reset_events_if_needed(state, base, wet_milli)
    record_measured(state, base, analysis)
    state.base = base
    _prune(state, base)

    timeline = _build_timeline(state, base, list(forecast), wet_milli)
    runs = _live_runs(state, timeline)
    survivors, matched_ids = _continue_events(state, runs, timeline, base)
    remaining, newly_ended = _set_aside_unmatched(state, matched_ids)
    for event, (first, last) in survivors:
        ended = _classify(state, event, timeline, base, first, last, forecast)
        if ended is not None:
            newly_ended.append(ended)
        else:
            remaining.append(event)

    if newly_ended:
        state.last_ended = max(newly_ended, key=lambda r: r["end"] or "")
    state.events = remaining
    state.view = _publish(state, timeline, base, wet_milli)
    return state.view


def _reset_events_if_needed(state: RainEventsState, base: datetime, wet_milli: int) -> None:
    """Start the events over when their ids or their split would be wrong."""
    if state.base is not None and base < state.base:
        state.events = []  # the clock went backwards; ids could repeat
    if state.wet_milli != wet_milli:
        # A new threshold splits rain differently: start over with new ids,
        # keeping the facts (measured steps, the last ended event).
        state.events = []
        state.wet_milli = wet_milli


def _prune(state: RainEventsState, base: datetime) -> None:
    """Drop the measured steps no event and no published window needs."""
    keep = _keep_from(state, base)
    state.measured = {t: v for t, v in state.measured.items() if keep <= t <= base}
    state.nodata = {t for t in state.nodata if t >= window_start(base)}


def _live_runs(state: RainEventsState, timeline: _Timeline) -> list[tuple[int, int]]:
    """Return the runs of rain that are not an ended event's, seen again."""
    state.ended_spans = [(a, b) for a, b in state.ended_spans if b > timeline.start(0)]
    return [
        (first, last)
        for first, last in _runs(timeline)
        if not any(
            timeline.start(first) < span_end and span_start < timeline.end(last)
            for span_start, span_end in state.ended_spans
        )
    ]


def _continue_events(
    state: RainEventsState,
    runs: list[tuple[int, int]],
    timeline: _Timeline,
    base: datetime,
) -> tuple[list[tuple[dict[str, Any], tuple[int, int]]], set[str]]:
    """Return each run's event (continued, merged or new), and the ids continued.

    Events that continue as the same run merge into the one first seen
    earliest; a run no event continues is a new event.
    """
    by_run = _match(state.events, runs, timeline)
    matched_ids = {e["id"] for evs in by_run.values() for e in evs}
    counter = 0
    survivors: list[tuple[dict[str, Any], tuple[int, int]]] = []
    for i, run in enumerate(runs):
        events = sorted(
            by_run[i], key=lambda e: (e["first_seen"], e["start"], e["id"])
        )
        if events:
            survivor = events[0]
            _merge_into(survivor, events[1:])
        else:
            survivor = _new_event(f"{base:%Y%m%dt%H%M}-{counter}", base)
            counter += 1
        survivors.append((survivor, run))
    return survivors, matched_ids


def _set_aside_unmatched(
    state: RainEventsState, matched_ids: set[str]
) -> tuple[list[dict[str, Any]], list[EndedRecord]]:
    """Return (events kept although no run continues them, events that ended).

    An upcoming event gets one release of grace as unseen; an event unseen
    twice is dropped.
    """
    remaining: list[dict[str, Any]] = []
    newly_ended: list[EndedRecord] = []
    for event in state.events:
        if event["id"] in matched_ids:
            continue
        if event["status"] == ONGOING:
            # Cannot happen while its last rain is held; end it rather than
            # lose it.
            newly_ended.append(_orphan_record(event))
        elif event["status"] == UPCOMING:
            event["status"] = UNSEEN
            remaining.append(event)
    return remaining, newly_ended


def _classify(
    state: RainEventsState,
    event: dict[str, Any],
    timeline: _Timeline,
    base: datetime,
    first: int,
    last: int,
    forecast: list[float | None],
) -> EndedRecord | None:
    """Bring a continued event up to this release; its record if it ended."""
    last_measured = timeline.last_measured
    wet_measured = [
        step
        for step in range(first, min(last, last_measured) + 1)
        if timeline.kinds[step] == WET
    ]
    forecast_block = _block(timeline, max(first, last_measured + 1), last)
    event["start"] = timeline.start(first)
    event["end"] = timeline.end(last)

    if not wet_measured:
        event["status"] = UPCOMING
        event["candidate"] = _candidate(timeline, base, first, last, forecast, forecast_block)
        event["last_wet"] = None
    else:
        event["status"] = ONGOING
        if not event["onset_frozen"]:
            # The last pure forecast is what users were warned with.
            event["onset"] = event["candidate"]
            event["onset_frozen"] = True
        event["candidate"] = None
        last_wet = wet_measured[-1]
        event["last_wet"] = timeline.end(last_wet)
        if _rain_ended_after(timeline, last_wet):
            state.ended_spans.append((timeline.start(first), timeline.end(last_wet)))
            return _ended_record(event, timeline, state, base, first, last_wet)

    event["view"] = _event_view(event, timeline, state, base, first, last, forecast_block)
    return None


def _candidate(
    timeline: _Timeline,
    base: datetime,
    first: int,
    last: int,
    forecast: list[float | None],
    forecast_block: Block,
) -> dict[str, Any]:
    """Return an upcoming event's forecast as of this release (its snapshot)."""
    return {
        "base": iso(base),
        "start": iso(timeline.start(first)),
        "end": iso(timeline.end(last)),
        "mm": forecast_block["mm"],
        "peak_1h": forecast_block["peak_1h"],
        "peak_10min": forecast_block["peak_10min"],
        "forecast": list(forecast),
    }


def _publish(
    state: RainEventsState, timeline: _Timeline, base: datetime, wet_milli: int
) -> RainEventsView:
    """Return the view of the events as they now stand."""
    events_view: list[EventView] = []
    for event in sorted(state.events, key=lambda e: e["start"]):
        view = EventView(**event["view"])
        view["status"] = event["status"]
        events_view.append(view)

    steps = timeline.values[timeline.series_start:]
    return {
        "schema": SCHEMA,
        "base": iso(base),
        "wet_step_mm": wet_milli / 1000,
        "steps_start": iso(timeline.start(timeline.series_start)),
        "steps": steps,
        "history_complete": all(v is not None for v in steps[:WINDOW_STEPS]),
        "events": events_view,
        "last_ended": state.last_ended,
    }


def _orphan_record(event: dict[str, Any]) -> EndedRecord:
    """Return an ended record for an ongoing event no run continues.

    Defensive only: an ongoing event's last rain is always held, so it always
    has a run. If it ever has not, publish what was last known rather than
    let it vanish.
    """
    view = event["view"] or {}
    return {
        "id": event["id"],
        "first_seen": iso(event["first_seen"]),
        "start": view.get("start"),
        "start_clipped": view.get("start_clipped", True),
        "end": iso(event["last_wet"]),
        "end_clipped": True,
        "missing_steps": view.get("missing_steps", 0),
        "observed_complete": False,
        "observed": view.get("observed", {"mm": 0.0, "peak_1h": None, "peak_10min": None}),
        "forecast_at_onset": view.get("forecast_at_onset"),
        "absorbed": list(event["absorbed"]),
    }


def _event_view(
    event: dict[str, Any],
    timeline: _Timeline,
    state: RainEventsState,
    base: datetime,
    first: int,
    last: int,
    forecast_block: Block,
) -> EventView:
    """Return the published view of an event that goes on."""
    last_observed = min(last, timeline.last_measured)
    observed = _block(timeline, first, last_observed)
    missing = _missing(timeline, first, last_observed)
    start_clipped = _start_clipped(timeline, first)
    first_published = max(first, timeline.series_start)
    return {
        "id": event["id"],
        "status": event["status"],
        "first_seen": iso(event["first_seen"]),
        "start": iso(timeline.start(first)),
        "start_clipped": start_clipped,
        "end": iso(timeline.end(last)),
        "beyond_horizon": last == timeline.last,
        "last_wet_observed": iso(event["last_wet"]),
        "missing_steps": missing,
        "observed_complete": missing == 0 and not start_clipped,
        "observed": observed,
        "forecast": forecast_block,
        "total": {
            "mm": round_mm(observed["mm"] + forecast_block["mm"]),
            "peak_1h": _total_peak_1h(timeline, first, last),
            "peak_10min": _peak(timeline, first_published, last, PAIR_STEPS),
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
