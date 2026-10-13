"""Scenario tests for the rain_events logic (pure; no HA)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone

import pytest

from rain_events import (
    MAX_UNKNOWN_BRIDGE,
    RainEventsState,
    STEP,
    at_stake,
    record_measured,
    steps_to_fill,
    update,
    wet_step_milli,
)

UTC = timezone.utc
DAY = datetime(2026, 10, 12, tzinfo=UTC)


def at(hhmm: str) -> datetime:
    hours, minutes = (int(x) for x in hhmm.split(":"))
    return DAY + timedelta(hours=hours, minutes=minutes)


def iso(hhmm: str) -> str:
    return at(hhmm).isoformat()


Rain = Callable[[datetime], float]


def steady(mm: float, start: str, end: str) -> Rain:
    """``mm`` per 5-minute step for the steps covering [start, end]."""
    lo, hi = at(start), at(end)
    return lambda t: mm if lo < t <= hi else 0.0


def combine(*rains: Rain) -> Rain:
    return lambda t: sum(r(t) for r in rains)


DRY: Rain = lambda _t: 0.0


class Sim:
    """Feeds releases to the tracker the way RadvorRV does."""

    def __init__(self, threshold_mmh: float = 0.1) -> None:
        self.state = RainEventsState()
        self.milli = wet_step_milli(threshold_mmh)
        self.unfillable: set[datetime] = set()
        self.fills: list[datetime] = []

    def release(self, base: datetime, truth: Rain, forecast: Rain | None = None) -> dict:
        for t in steps_to_fill(self.state, base):
            if t in self.unfillable:
                continue
            self.fills.append(t)
            record_measured(self.state, t, truth(t))
        forecast = forecast or truth
        steps = [forecast(base + (k + 1) * STEP) for k in range(24)]
        return update(self.state, base, truth(base), steps, self.milli)

    def run(
        self, start: str, end: str, truth: Rain, forecast: Rain | None = None,
        skip: Iterable[str] = (),
    ) -> dict[str, dict]:
        """Process every release from start to end; return the views by T."""
        skipped = {at(s) for s in skip}
        out = {}
        t = at(start)
        while t <= at(end):
            if t not in skipped:
                out[t.strftime("%H:%M")] = self.release(t, truth, forecast)
            t += STEP
        return out

    def restart(self) -> None:
        """Round-trip the state through JSON, as the Store does."""
        self.state = RainEventsState.from_dict(json.loads(json.dumps(self.state.as_dict())))


def only(view: dict) -> dict:
    assert len(view["events"]) == 1, view["events"]
    return view["events"][0]


# ---------------------------------------------------------------------------
# Threshold
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("mmh", "milli"), [(0.1, 8), (0.2, 16), (0.0, 0), (1.2, 100), (0.3, 25)])
def test_wet_step_threshold_is_floored_to_thousandths(mmh, milli):
    assert wet_step_milli(mmh) == milli


def test_wet_is_strictly_above_and_matches_option_over_twelve():
    sim = Sim(threshold_mmh=0.2)  # 0.0167 mm per step -> 0.016
    view = sim.release(at("12:00"), lambda t: 0.016 if t == at("12:00") else 0.0)
    assert view["wet_step_mm"] == 0.016
    assert view["events"] == []
    view = sim.release(at("12:05"), lambda t: 0.017 if t == at("12:05") else 0.0)
    assert only(view)["status"] == "ongoing"


def test_threshold_change_drops_events_but_keeps_steps_and_last_ended():
    sim = Sim()
    sim.run("13:00", "14:50", steady(1.0, "14:00", "14:20"))
    ended = sim.state.last_ended
    assert ended is not None
    upcoming = sim.release(at("14:55"), DRY, steady(1.0, "15:30", "15:40"))
    old_id = only(upcoming)["id"]

    sim.milli = wet_step_milli(0.5)
    view = sim.release(at("15:00"), DRY, steady(1.0, "15:30", "15:40"))

    assert only(view)["id"] != old_id
    assert view["last_ended"] == ended
    # The measured steps are facts and stay: 14:05..14:20 were wet.
    assert view["steps"][:5] == [1.0, 1.0, 1.0, 1.0, 0.0]


def test_threshold_change_applies_to_the_same_release():
    # An options change reloads the entry, and its first refresh is the
    # release the old threshold already processed.
    sim = Sim(threshold_mmh=0.1)
    drizzle = steady(0.02, "15:30", "15:40")  # 0.24 mm/h
    assert only(sim.release(at("14:55"), DRY, drizzle))["status"] == "upcoming"

    sim.milli = wet_step_milli(0.5)
    view = sim.release(at("14:55"), DRY, drizzle)

    assert view["wet_step_mm"] == sim.milli / 1000
    assert view["events"] == []


# ---------------------------------------------------------------------------
# Scenario 1: an approaching cell
# ---------------------------------------------------------------------------


def test_approaching_cell_keeps_its_id_until_it_has_ended():
    sim = Sim()
    rain = steady(1.0, "14:00", "14:30")
    views = sim.run("11:50", "14:45", rain)

    assert views["12:00"]["events"] == []  # beyond the 2 h horizon
    ids = {e["id"] for v in views.values() for e in v["events"]}
    assert ids == {"20261012t1205-0"}

    statuses = [v["events"][0]["status"] for v in views.values() if v["events"]]
    assert statuses[0] == "upcoming" and statuses[-1] == "ongoing"
    assert statuses.index("ongoing") == statuses.count("upcoming")

    # Ended once two measured steps after the last rain were dry.
    assert views["14:35"]["events"][0]["status"] == "ongoing"
    assert views["14:40"]["events"] == []
    ended = views["14:40"]["last_ended"]
    assert ended["id"] == "20261012t1205-0"
    assert (ended["start"], ended["end"]) == (iso("14:00"), iso("14:30"))
    assert ended["observed"]["mm"] == 6.0
    assert ended["observed_complete"] is True

    # The last pure forecast: the 14:00 release, just before the first drop.
    onset = ended["forecast_at_onset"]
    assert onset["base"] == iso("14:00")
    assert onset["mm"] == 6.0
    assert onset["expected_so_far_mm"] == onset["observed_so_far_mm"] == 6.0
    # The onset snapshot stays hidden while the event is still a forecast.
    assert views["13:00"]["events"][0]["forecast_at_onset"] is None


# ---------------------------------------------------------------------------
# Scenario 3: merge, split, vanish
# ---------------------------------------------------------------------------


def test_merge_keeps_the_event_first_seen_and_lists_the_absorbed_one():
    sim = Sim()
    a = steady(1.0, "13:00", "13:20")
    b = steady(1.0, "13:40", "14:00")
    first = sim.release(at("12:00"), DRY, a)
    a_id = only(first)["id"]
    second = sim.release(at("12:05"), DRY, combine(a, b))
    b_id = [e["id"] for e in second["events"] if e["id"] != a_id][0]

    merged = sim.release(at("12:10"), DRY, steady(1.0, "13:00", "14:00"))

    event = only(merged)
    assert event["id"] == a_id
    assert event["absorbed"] == [b_id]


def test_split_gives_the_later_part_a_new_id():
    sim = Sim()
    c_id = only(sim.release(at("12:00"), DRY, steady(1.0, "13:00", "13:40")))["id"]
    split = sim.release(
        at("12:05"), DRY, combine(steady(1.0, "13:00", "13:10"), steady(1.0, "13:30", "13:40"))
    )
    ids = [e["id"] for e in split["events"]]
    assert ids[0] == c_id
    assert ids[1] == "20261012t1205-0"


def test_vanished_event_is_unseen_for_one_release_then_dropped():
    sim = Sim()
    cell = steady(1.0, "13:00", "13:10")
    d_id = only(sim.release(at("12:00"), DRY, cell))["id"]

    gone = only(sim.release(at("12:05"), DRY, DRY))
    assert (gone["id"], gone["status"]) == (d_id, "unseen")
    assert sim.release(at("12:10"), DRY, DRY)["events"] == []


def test_event_missing_from_one_release_keeps_its_id():
    sim = Sim()
    cell = steady(1.0, "13:00", "13:10")
    d_id = only(sim.release(at("12:00"), DRY, cell))["id"]
    sim.release(at("12:05"), DRY, DRY)
    back = only(sim.release(at("12:10"), DRY, cell))
    assert (back["id"], back["status"]) == (d_id, "upcoming")


# ---------------------------------------------------------------------------
# Scenario 5: unforecast rain
# ---------------------------------------------------------------------------


def test_unforecast_rain_starts_at_its_first_wet_step():
    sim = Sim()
    views = sim.run("13:30", "14:10", steady(1.0, "14:00", "14:30"), forecast=DRY)
    event = only(views["14:05"])
    assert event["status"] == "ongoing"
    assert event["start"] == iso("14:00")
    assert event["start_clipped"] is False
    assert event["forecast_at_onset"] is None
    assert only(views["14:10"])["observed"]["mm"] == 2.0


# ---------------------------------------------------------------------------
# Scenarios 6 and 10: lost releases
# ---------------------------------------------------------------------------


def test_lost_releases_are_filled_before_matching():
    sim = Sim()
    rain = steady(1.0, "14:00", "14:30")
    views = sim.run("12:00", "14:25", rain, skip=["13:00", "13:05", "14:10", "14:15"])

    assert at("14:10") in sim.fills and at("14:15") in sim.fills
    event = only(views["14:20"])
    assert event["id"] == "20261012t1205-0"
    assert event["observed"]["mm"] == 4.0
    assert views["14:20"]["history_complete"] is True
    assert all(e["status"] != "unseen" for v in views.values() for e in v["events"])


def test_lost_releases_mid_storm_restore_the_observed_amount():
    sim = Sim()
    views = sim.run("13:00", "14:30", steady(1.5, "14:00", "15:00"), skip=["14:10", "14:15", "14:20"])
    event = only(views["14:30"])
    assert event["observed"]["mm"] == 9.0
    assert event["missing_steps"] == 0


def test_failed_fills_mid_storm_neither_split_nor_end_the_event():
    sim = Sim()
    rain = steady(1.0, "14:00", "15:00")
    sim.unfillable = {at("14:20"), at("14:25")}
    views = sim.run("13:30", "14:40", rain, skip=["14:20", "14:25"])

    event = only(views["14:40"])
    assert event["start"] == iso("14:00")
    assert event["missing_steps"] == 2
    assert event["observed_complete"] is False
    assert views["14:40"]["history_complete"] is False
    assert event["observed"]["mm"] == 6.0  # 8 steps measured, 2 unknown count 0


def test_unknown_steps_after_the_last_rain_postpone_the_end():
    sim = Sim()
    rain = steady(1.0, "14:00", "14:30")
    sim.unfillable = {at("14:35")}
    views = sim.run("13:30", "15:40", rain, skip=["14:35"])

    # 14:35 might have been wet: the event stays ongoing...
    assert only(views["15:25"])["status"] == "ongoing"
    assert views["15:25"]["last_ended"] is None
    # ...until that step leaves the window, which ends it as clipped.
    assert views["15:35"]["events"] == []
    ended = views["15:35"]["last_ended"]
    assert ended["end"] == iso("14:30")
    assert ended["end_clipped"] is True
    assert ended["observed_complete"] is False


# ---------------------------------------------------------------------------
# Scenario 9: the wettest hour straddles now
# ---------------------------------------------------------------------------


def test_hour_straddling_now():
    sim = Sim()
    view = sim.release(at("14:30"), steady(1.5, "14:00", "15:00"))  # first release ever

    event = only(view)
    assert event["start"] == iso("14:00")  # not 14:25: the fill saw it start
    assert event["start_clipped"] is False
    assert event["end"] == iso("15:00")
    assert event["last_wet_observed"] == iso("14:30")
    assert event["observed"] == {
        "mm": 9.0,
        "peak_1h": {"mm": 9.0, "start": iso("14:00"), "end": iso("14:30")},
        "peak_10min": {"mm": 3.0, "start": iso("14:00"), "end": iso("14:10")},
    }
    assert event["forecast"] == {
        "mm": 9.0,
        "peak_1h": {"mm": 9.0, "start": iso("14:30"), "end": iso("15:00")},
        "peak_10min": {"mm": 3.0, "start": iso("14:30"), "end": iso("14:40")},
    }
    assert event["total"] == {
        "mm": 18.0,
        "peak_1h": {"mm": 18.0, "start": iso("14:00"), "end": iso("15:00")},
        "peak_10min": {"mm": 3.0, "start": iso("14:00"), "end": iso("14:10")},
    }
    assert view["steps_start"] == iso("13:30")
    assert len(view["steps"]) == 36
    assert view["steps"][11] == 1.5  # the step ending at T


def test_total_peak_counts_rain_outside_the_event():
    """Two cells within an hour add up for the heavy-rain window."""
    sim = Sim()
    rain = combine(steady(3.0, "14:00", "14:10"), steady(3.0, "14:30", "14:40"))
    view = sim.release(at("13:30"), DRY, rain)
    first, second = view["events"]
    assert first["forecast"]["mm"] == 6.0
    assert first["total"]["peak_1h"]["mm"] == 12.0


# ---------------------------------------------------------------------------
# Restarts
# ---------------------------------------------------------------------------


def test_restart_keeps_ids_and_fills_the_downtime():
    sim = Sim()
    rain = steady(1.0, "14:00", "15:00")
    before = sim.run("13:00", "14:15", rain)
    event_id = only(before["14:15"])["id"]

    sim.restart()
    after = sim.release(at("14:45"), rain)  # 30 min down

    event = only(after)
    assert event["id"] == event_id
    assert event["observed"]["mm"] == 9.0
    assert event["observed_complete"] is True


def test_restart_after_a_long_downtime_keeps_the_event_but_flags_the_gap():
    sim = Sim()
    rain = steady(1.0, "12:00", "17:00")
    before = sim.run("11:30", "13:00", rain)
    event_id = only(before["13:00"])["id"]

    sim.restart()
    after = sim.release(at("15:30"), rain)  # 2.5 h down

    event = only(after)
    assert event["id"] == event_id
    assert event["start"] == iso("12:00")
    assert event["missing_steps"] == 18  # 13:05..14:30, out of reach
    assert event["observed_complete"] is False


def test_downtime_beyond_the_bridge_ends_the_event():
    sim = Sim()
    rain = steady(1.0, "12:00", "23:00")
    before = sim.run("11:30", "13:00", rain)
    event_id = only(before["13:00"])["id"]

    sim.restart()
    later = at("13:00") + (MAX_UNKNOWN_BRIDGE + 14) * STEP
    view = sim.release(later, rain)

    assert view["last_ended"]["id"] == event_id
    assert view["last_ended"]["end_clipped"] is True
    assert only(view)["id"] != event_id
    assert only(view)["start_clipped"] is True


# ---------------------------------------------------------------------------
# Long events, finality, like-for-like
# ---------------------------------------------------------------------------


def test_long_event_amounts_never_decrease():
    sim = Sim()
    views = sim.run("11:00", "15:30", steady(1.0, "12:00", "15:00"))
    observed = [only(v)["observed"] for v in views.values() if v["events"]
                and only(v)["status"] == "ongoing"]
    starts = {only(v)["start"] for v in views.values() if v["events"]}
    assert starts == {iso("12:00")}
    mm = [o["mm"] for o in observed]
    peaks = [o["peak_1h"]["mm"] for o in observed]
    assert mm == sorted(mm) and peaks == sorted(peaks)
    assert mm[-1] == 36.0 and peaks[-1] == 12.0


def test_ended_event_is_final():
    sim = Sim()
    first = steady(1.0, "14:00", "14:20")
    second = steady(1.0, "15:00", "15:20")
    views = sim.run("13:30", "15:10", combine(first, second), forecast=first)
    ended = views["14:30"]["last_ended"]
    assert views["15:10"]["last_ended"] == ended
    assert only(views["15:10"])["id"] != ended["id"]


def test_like_for_like_deviation_over_the_same_steps():
    sim = Sim()
    truth = steady(1.5, "14:00", "17:00")
    forecast = steady(0.5, "14:00", "17:00")
    views = sim.run("13:30", "16:30", truth, forecast=forecast)
    # Upcoming until 13:55; frozen at the first measured drop (14:05).
    def onset(hhmm):
        return only(views[hhmm])["forecast_at_onset"]

    assert onset("14:05")["base"] == iso("14:00")
    assert onset("14:30")["expected_so_far_mm"] == 3.0  # 6 steps x 0.5
    assert onset("14:30")["observed_so_far_mm"] == 9.0  # 6 steps x 1.5
    # Both stop where the snapshot's forecast ends (14:00 + 2 h).
    assert onset("16:00") == onset("16:30")
    assert onset("16:30")["observed_so_far_mm"] == 36.0


def test_like_for_like_differs_from_observed_when_a_fill_reveals_earlier_rain():
    sim = Sim()
    # 13:50 wet, 13:55 dry, then rain from 14:00: one event once 13:50 is known.
    truth = combine(steady(1.0, "13:45", "13:50"), steady(1.0, "13:55", "14:30"))
    sim.unfillable = {at("13:50")}
    sim.run("13:00", "13:55", truth, forecast=steady(1.0, "13:55", "14:30"), skip=["13:50"])
    sim.unfillable = set()
    event = only(sim.release(at("14:00"), truth))
    assert event["start"] == iso("13:45")
    assert event["observed"]["mm"] == 2.0
    assert event["forecast_at_onset"]["observed_so_far_mm"] == 1.0


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def test_state_round_trips_through_json():
    sim = Sim()
    sim.run("13:00", "14:15", steady(1.0, "14:00", "15:00"))
    raw = json.loads(json.dumps(sim.state.as_dict()))
    assert RainEventsState.from_dict(raw).as_dict() == raw


def test_nothing_at_stake_on_a_dry_day():
    sim = Sim()
    sim.run("12:00", "13:00", DRY)
    assert at_stake(sim.state) is False
    sim.release(at("13:05"), DRY, steady(1.0, "14:00", "14:10"))
    assert at_stake(sim.state) is True


def test_nodata_steps_are_not_refetched():
    sim = Sim()
    sim.release(at("12:00"), lambda _t: None)  # no data for the cell at all
    assert steps_to_fill(sim.state, at("12:05")) == []


def test_overall_status_prefers_ongoing_and_ignores_unseen():
    from rain_events import NO_EVENT, overall_status

    def view(*statuses):
        return {"events": [{"status": s} for s in statuses]}

    assert overall_status(view()) == NO_EVENT
    assert overall_status({"events": None}) == NO_EVENT
    assert overall_status(view("unseen")) == NO_EVENT
    assert overall_status(view("unseen", "upcoming")) == "upcoming"
    assert overall_status(view("upcoming", "ongoing")) == "ongoing"
