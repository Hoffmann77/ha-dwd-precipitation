"""Domain logic for rain warnings: a filter over the rain-events view.

A rain warning ("Laundry, 60 min") is a config subentry of a location. It has
no event logic of its own: every release it reads the view the rain-events
tracker published (rain_events.py, schema 1) and says whether one of its
events concerns the warning:

- ``rain``: an ongoing event passes the warning's filter;
- ``soon``: none does, but an upcoming event that passes it starts within the
  lead time;
- ``dry``: neither.

Two things are remembered, in memory, per warning (RainWarning), so that a
warning does not flicker while the forecast moves:

- an event that passed the filter once passes until it ends (an ongoing
  shower whose forecast shrinks stays ``rain``), and the event that absorbs it
  in a merge inherits that;
- an event that was ``soon`` stays ``soon`` for the one release in which the
  forecast loses it (``unseen``, which rain_events allows once before dropping
  the event).

A warning is judged when a release brings a new view, not in between: the
lead time is measured from when the release arrived, so a warning starts up to
one release (5 minutes) later than the exact moment, which is within what
DWD's publication delay already costs.

Pure and HA-free, like everything in radar/.

"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .isotime import parse_utc
from .rain_events import ONGOING, UNSEEN, UPCOMING

# The states of the warning's enum sensor; the binary sensor is on for the
# last two.
DRY, SOON, RAIN = "dry", "soon", "rain"
STATES = [DRY, SOON, RAIN]

# How a warning with several minimums combines them.
COMBINE_ANY, COMBINE_ALL = "any", "all"
COMBINES = (COMBINE_ANY, COMBINE_ALL)


@dataclass(frozen=True)
class WarningRule:
    """What one warning asks for; fields named like its subentry data keys.

    ``lead_time`` is in minutes. Each minimum is in mm and optional (None: not
    asked for): ``min_mm`` for the event's total, ``min_peak_1h`` and
    ``min_peak_10min`` for its wettest hour and wettest 10 minutes. Without
    any minimum, every event passes.

    """

    lead_time: int
    min_mm: float | None = None
    min_peak_1h: float | None = None
    min_peak_10min: float | None = None
    combine: str = COMBINE_ANY

    def passes(self, event: dict[str, Any]) -> bool:
        """Return whether ``event`` (an EventView) reaches the minimums.

        Compared with the event's ``total`` block: measured plus forecast for
        an ongoing event, the forecast alone for an upcoming one. With
        ``combine`` "any", one minimum reached is enough; with "all", every one
        that is set must be. A peak the event does not have counts as not
        reached.

        """
        total = event.get("total") or {}
        checks = [
            reached is not None and reached >= minimum
            for minimum, reached in (
                (self.min_mm, total.get("mm")),
                (self.min_peak_1h, _peak_mm(total.get("peak_1h"))),
                (self.min_peak_10min, _peak_mm(total.get("peak_10min"))),
            )
            if minimum is not None
        ]
        if not checks:
            return True
        return all(checks) if self.combine == COMBINE_ALL else any(checks)


def _peak_mm(peak: dict[str, Any] | None) -> float | None:
    """Return a peak's amount (mm), None if there is no peak."""
    return None if peak is None else peak.get("mm")


@dataclass(frozen=True)
class Verdict:
    """A warning's state for one view, and the event it is about (None if dry)."""

    state: str
    event: dict[str, Any] | None = None

    @property
    def is_on(self) -> bool:
        """Return whether the warning is on: rain now or soon."""
        return self.state != DRY

    def attributes(self) -> dict[str, Any]:
        """Return the enum sensor's attributes: the event it is about.

        ``event_id``, ``start`` and ``end`` come from the event, with
        ``beyond_horizon`` true while it lasts past the forecast horizon (its
        end is then only the horizon's); ``mm``, ``peak_1h``
        and ``peak_10min`` are its ``total`` block (mm, the peaks as their
        amount). ``type`` is the event's measured precipitation type, the
        HymecNG label of its latest wet measured step: None while it is only
        upcoming (DWD forecasts no type) and when none was measured. All None
        while dry.

        """
        event = self.event or {}
        total = event.get("total") or {}
        return {
            "event_id": event.get("id"),
            "start": event.get("start"),
            "end": event.get("end"),
            "beyond_horizon": event.get("beyond_horizon"),
            "mm": total.get("mm"),
            "peak_1h": _peak_mm(total.get("peak_1h")),
            "peak_10min": _peak_mm(total.get("peak_10min")),
            "type": event.get("type"),
        }


ATTRIBUTES = tuple(Verdict(DRY).attributes())


def judge(
    view: dict[str, Any],
    now: datetime,
    rule: WarningRule,
    passed: frozenset[str] = frozenset(),
    soon_before: frozenset[str] = frozenset(),
) -> tuple[Verdict, frozenset[str], frozenset[str]]:
    """Return the warning's verdict on ``view`` at ``now``, and what to remember.

    ``passed`` holds the ids of events that passed ``rule`` on an earlier
    view, ``soon_before`` the upcoming ones that were soon on the last one.
    Returned with the verdict: the ids that have passed by now and the
    upcoming ones that are soon now, each limited to the events in ``view``
    (an ended event leaves both).
    Of several events concerned, the earliest (the view is sorted by start)
    is the one reported; rain goes before soon.

    """
    events = view.get("events") or []
    passed_now = frozenset(
        event["id"]
        for event in events
        if event["id"] in passed
        or any(absorbed in passed for absorbed in event.get("absorbed") or ())
        or rule.passes(event)
    )
    lead = timedelta(minutes=rule.lead_time)

    def is_soon(event: dict[str, Any]) -> bool:
        if event["status"] == UPCOMING:
            start = parse_utc(event.get("start"))
            return start is not None and start - now <= lead
        return event["status"] == UNSEEN and event["id"] in soon_before

    concerned = [event for event in events if event["id"] in passed_now]
    soon = [event for event in concerned if is_soon(event)]
    # Only an upcoming event can be held on the next view: a held one is not
    # held again.
    soon_ids = frozenset(event["id"] for event in soon if event["status"] == UPCOMING)
    for event in concerned:
        if event["status"] == ONGOING:
            return Verdict(RAIN, event), passed_now, soon_ids
    if soon:
        return Verdict(SOON, soon[0]), passed_now, soon_ids
    return Verdict(DRY), passed_now, soon_ids


class RainWarning:
    """One warning's memory between views, shared by its two entities.

    Both entities ask evaluate() on every RV update; the first to see a new
    view judges it, the other gets the same verdict, so they never disagree
    and the memory moves once per view. In memory only: after a restart, an
    event is judged again on its current values.

    """

    def __init__(self, rule: WarningRule) -> None:
        """Start with nothing judged."""
        self.rule = rule
        self._view: dict[str, Any] | None = None
        self._verdict: Verdict | None = None
        self._passed: frozenset[str] = frozenset()
        self._soon: frozenset[str] = frozenset()

    def evaluate(self, view: dict[str, Any] | None, now: datetime) -> Verdict | None:
        """Return the verdict on ``view``, judging it at ``now`` if it is new.

        None without a view (RV has no data yet, or the tracker failed), which
        the entities show as unknown rather than a guess. A view already judged
        (the same release again, or the second entity asking) keeps its
        verdict, whatever ``now``.

        """
        if view is None:
            return None
        if view is not self._view:
            self._verdict, self._passed, self._soon = judge(
                view, now, self.rule, self._passed, self._soon
            )
            self._view = view
        return self._verdict
