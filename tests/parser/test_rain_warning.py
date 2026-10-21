"""The rain-warning filter over the rain-events view (pure; no HA)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from radar.rain_events import RainEventsState, update, wet_step_milli
from radar.rain_warning import (
    ATTRIBUTES,
    COMBINE_ALL,
    DRY,
    RAIN,
    SOON,
    RainWarning,
    Verdict,
    WarningRule,
    judge,
)

UTC = timezone.utc
DAY = datetime(2026, 10, 12, tzinfo=UTC)
# The release the views are about, and when it arrived.
BASE = DAY + timedelta(hours=14)
NOW = BASE + timedelta(minutes=7)


def at(minutes: float) -> str:
    """Return the ISO time ``minutes`` after NOW."""
    return (NOW + timedelta(minutes=minutes)).isoformat()


def peak(mm: float) -> dict:
    return {"mm": mm, "start": at(0), "end": at(60)}


def event(
    event_id: str,
    status: str = "upcoming",
    start: float = 30,
    mm: float = 2.0,
    peak_1h: float | None = 1.5,
    peak_10min: float | None = 0.8,
    absorbed: list[str] | None = None,
) -> dict:
    """Return an EventView with what the warning reads; ``start`` minutes from NOW."""
    return {
        "id": event_id,
        "status": status,
        "start": at(start),
        "total": {
            "mm": mm,
            "peak_1h": None if peak_1h is None else peak(peak_1h),
            "peak_10min": None if peak_10min is None else peak(peak_10min),
        },
        "absorbed": absorbed or [],
    }


def view(*events: dict) -> dict:
    return {"schema": 1, "base": BASE.isoformat(), "events": sorted(events, key=lambda e: e["start"])}


def verdict(rule: WarningRule, *events: dict) -> Verdict:
    return judge(view(*events), NOW, rule)[0]


# ---------------------------------------------------------------------------
# Lead time
# ---------------------------------------------------------------------------


def test_an_upcoming_event_within_the_lead_time_is_soon() -> None:
    result = verdict(WarningRule(lead_time=60), event("a", start=40))

    assert result.state == SOON
    assert result.is_on
    assert result.event["id"] == "a"


def test_the_lead_time_is_measured_from_now_and_includes_its_end() -> None:
    """Exactly lead_time away is soon; a second more is not yet."""
    rule = WarningRule(lead_time=30)

    assert verdict(rule, event("a", start=30)).state == SOON
    assert verdict(rule, event("a", start=30 + 1 / 60)).state == DRY


def test_an_event_beyond_the_lead_time_is_dry() -> None:
    result = verdict(WarningRule(lead_time=15), event("a", start=45))

    assert result.state == DRY
    assert not result.is_on
    assert result.event is None


def test_an_upcoming_event_whose_start_has_passed_is_soon() -> None:
    """The view is minutes old when it arrives: a start before now is still soon."""
    assert verdict(WarningRule(lead_time=5), event("a", start=-2)).state == SOON


def test_an_ongoing_event_is_rain_whatever_the_lead_time() -> None:
    result = verdict(WarningRule(lead_time=5), event("a", "ongoing", start=-20))

    assert result.state == RAIN
    assert result.is_on


def test_no_events_is_dry() -> None:
    assert verdict(WarningRule(lead_time=120)).state == DRY


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------


def test_without_a_minimum_every_event_passes() -> None:
    assert WarningRule(lead_time=30).passes(event("a", mm=0.01, peak_1h=None, peak_10min=None))


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        (WarningRule(30, min_mm=2.0), True),  # reached exactly
        (WarningRule(30, min_mm=2.1), False),
        (WarningRule(30, min_peak_1h=1.5), True),
        (WarningRule(30, min_peak_1h=1.6), False),
        (WarningRule(30, min_peak_10min=0.8), True),
        (WarningRule(30, min_peak_10min=0.9), False),
        # Any: one reached is enough.
        (WarningRule(30, min_mm=5.0, min_peak_10min=0.5), True),
        (WarningRule(30, min_mm=5.0, min_peak_10min=1.0), False),
        # All: every one set must be reached.
        (WarningRule(30, min_mm=1.0, min_peak_10min=0.5, combine=COMBINE_ALL), True),
        (WarningRule(30, min_mm=5.0, min_peak_10min=0.5, combine=COMBINE_ALL), False),
    ],
)
def test_the_minimums_are_compared_with_the_events_total(rule, expected) -> None:
    """Event a: 2.0 mm in total, 1.5 mm in its wettest hour, 0.8 mm in 10 min."""
    assert rule.passes(event("a")) is expected


def test_a_missing_peak_does_not_reach_its_minimum() -> None:
    assert not WarningRule(30, min_peak_1h=0.0).passes(event("a", peak_1h=None))


def test_an_event_below_the_minimum_does_not_warn() -> None:
    rule = WarningRule(lead_time=60, min_mm=5.0)

    assert verdict(rule, event("a", "ongoing", start=-10, mm=1.0)).state == DRY
    assert verdict(rule, event("a", start=10, mm=1.0)).state == DRY


def test_a_later_event_that_passes_is_reported() -> None:
    """A small shower first, the heavy one after it: the warning is about the heavy one."""
    rule = WarningRule(lead_time=60, min_mm=5.0)

    result = verdict(rule, event("small", start=10, mm=0.5), event("heavy", start=40, mm=8.0))

    assert result.state == SOON
    assert result.event["id"] == "heavy"


# ---------------------------------------------------------------------------
# Which event
# ---------------------------------------------------------------------------


def test_rain_goes_before_soon() -> None:
    result = verdict(
        WarningRule(lead_time=60),
        event("now", "ongoing", start=-10),
        event("next", start=20),
    )

    assert result.state == RAIN
    assert result.event["id"] == "now"


def test_the_earliest_soon_event_is_reported() -> None:
    result = verdict(WarningRule(lead_time=60), event("b", start=50), event("a", start=20))

    assert result.event["id"] == "a"


def test_the_attributes_describe_the_event() -> None:
    result = verdict(WarningRule(lead_time=60), event("a", start=20, mm=2.5))

    assert result.attributes() == {
        "event_id": "a",
        "start": at(20),
        "mm": 2.5,
        "peak_1h": 1.5,
        "peak_10min": 0.8,
        "type": None,
    }
    assert tuple(result.attributes()) == ATTRIBUTES


def test_the_attributes_are_none_while_dry() -> None:
    assert Verdict(DRY).attributes() == dict.fromkeys(ATTRIBUTES)


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def test_an_event_that_passed_once_passes_until_it_ends() -> None:
    """The forecast of an ongoing shower shrinks below the minimum: still rain."""
    warning = RainWarning(WarningRule(lead_time=60, min_mm=5.0))

    assert warning.evaluate(view(event("a", start=20, mm=6.0)), NOW).state == SOON
    assert warning.evaluate(view(event("a", "ongoing", start=-5, mm=3.0)), NOW).state == RAIN
    assert warning.evaluate(view(event("a", "ongoing", start=-10, mm=2.0)), NOW).state == RAIN


def test_a_pass_outside_the_lead_time_counts_too() -> None:
    """Passed while still beyond the lead time, then shrank: soon once it is near."""
    warning = RainWarning(WarningRule(lead_time=30, min_mm=5.0))

    assert warning.evaluate(view(event("a", start=90, mm=6.0)), NOW).state == DRY
    assert warning.evaluate(view(event("a", start=20, mm=4.0)), NOW).state == SOON


def test_an_ended_event_is_forgotten() -> None:
    warning = RainWarning(WarningRule(lead_time=60, min_mm=5.0))
    warning.evaluate(view(event("a", "ongoing", start=-5, mm=6.0)), NOW)
    warning.evaluate(view(), NOW)  # a ended

    # Should an id ever come back, it is judged again.
    assert warning.evaluate(view(event("a", start=10, mm=1.0)), NOW).state == DRY


def test_the_event_that_absorbs_a_passed_one_inherits_its_pass() -> None:
    warning = RainWarning(WarningRule(lead_time=60, min_mm=5.0))
    warning.evaluate(view(event("b", start=40, mm=6.0), event("a", start=10, mm=1.0)), NOW)

    merged = event("a", start=10, mm=4.0, absorbed=["b"])
    assert warning.evaluate(view(merged), NOW).state == SOON


def test_an_unseen_event_that_was_soon_stays_soon_for_that_release() -> None:
    warning = RainWarning(WarningRule(lead_time=60))
    warning.evaluate(view(event("a", start=20)), NOW)

    held = warning.evaluate(view(event("a", "unseen", start=20)), NOW)
    assert held.state == SOON
    assert held.event["id"] == "a"


def test_an_unseen_event_that_was_not_soon_does_not_warn() -> None:
    """Only a warning already given is held; the forecast no longer shows this one."""
    warning = RainWarning(WarningRule(lead_time=30))
    warning.evaluate(view(event("a", start=60)), NOW)

    later = NOW + timedelta(minutes=35)  # now within the lead time, but unseen
    assert warning.evaluate(view(event("a", "unseen", start=60)), later).state == DRY


def test_an_unseen_event_is_held_once() -> None:
    """Unseen in two releases running is not soon (rain_events drops it anyway)."""
    warning = RainWarning(WarningRule(lead_time=60))
    warning.evaluate(view(event("a", start=20)), NOW)
    warning.evaluate(view(event("a", "unseen", start=20)), NOW)

    assert warning.evaluate(view(event("a", "unseen", start=20)), NOW).state == DRY


def test_a_view_is_judged_once() -> None:
    """The second entity asking, later, gets the same verdict and moves no memory."""
    warning = RainWarning(WarningRule(lead_time=30))
    same = view(event("a", start=40))

    assert warning.evaluate(same, NOW).state == DRY
    assert warning.evaluate(same, NOW + timedelta(minutes=15)).state == DRY


def test_without_a_view_there_is_no_verdict() -> None:
    assert RainWarning(WarningRule(lead_time=30)).evaluate(None, NOW) is None


# ---------------------------------------------------------------------------
# On the real view
# ---------------------------------------------------------------------------


def test_the_warning_reads_the_view_rain_events_publishes() -> None:
    """A shower forecast 20-40 min after the release, then falling."""
    milli = wet_step_milli(0.1)
    state = RainEventsState()
    warning = RainWarning(WarningRule(lead_time=30, min_mm=1.0))

    def forecast(base: datetime, lo: int, hi: int) -> list[float]:
        """0.5 mm per step for the steps ending lo..hi minutes after the release."""
        return [0.5 if lo <= lead <= hi else 0.0 for lead in range(5, 125, 5)]

    upcoming = update(state, BASE, 0.0, forecast(BASE, 25, 40), milli)
    result = warning.evaluate(upcoming, BASE + timedelta(minutes=7))
    assert result.state == SOON
    assert result.attributes()["mm"] == pytest.approx(2.0)
    assert result.attributes()["start"] == (BASE + timedelta(minutes=20)).isoformat()

    later = BASE + timedelta(minutes=25)
    ongoing = update(state, later, 0.5, forecast(later, 5, 15), milli)
    result = warning.evaluate(ongoing, later + timedelta(minutes=7))
    assert result.state == RAIN
    assert result.attributes()["event_id"] == upcoming["events"][0]["id"]
