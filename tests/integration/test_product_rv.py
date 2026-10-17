"""RV (RADVOR 5-minute nowcast): derived values, options, and the peak hour."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from custom_components.dwd_precipitation import products
from custom_components.dwd_precipitation.products import RadvorRV
from custom_components.dwd_precipitation.utils import AsyncResponse

from tests.factories.radvor import LEADS, RangeServer, make_radvor_tar
from tests.factories.real import real_cells, real_member, real_release
from tests.integration.product_helpers import rv_fetch, rv_what


@pytest.mark.asyncio
async def test_rv_fetch_derives_buckets_and_timing(make_coordinator) -> None:
    """RV: peak intensity, start/end detection, and the raw 5-min series."""
    ts = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    # Scenario: dry now, rain at leads 30..60 (1.0 mm each), dry afterwards.
    leads = LEADS
    values = {lead: (1.0 if 30 <= lead <= 60 else 0.0) for lead in leads}
    reads = iter([
        (np.float32(values[lead]), rv_what(ts, lead))
        for lead in leads
    ])

    coord = make_coordinator(RadvorRV)

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rv", ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=lambda _f, _r, _c, **_kw: next(reads)),
    ):
        data, meta = await coord._fetch_and_parse(ts)

    # Peak intensity: 1.0 mm/5min → 12 mm/h in hour 1; hour 2 is dry.
    assert data["max_060"] == pytest.approx(12.0)
    assert data["max_120"] == pytest.approx(0.0)
    assert data["max_000_120"] == pytest.approx(12.0)
    # The two-hour sum sensors were removed; only max intensity remains.
    assert "rv_060" not in data
    assert "rv_120" not in data
    # Dry now → rain starts at lead 30 (25 min out); ends at lead 65 boundary (60 min out).
    assert data["start_in"] == 25
    assert data["start_at"] == datetime(2026, 7, 16, 20, 55, tzinfo=timezone.utc)
    assert data["end_in"] == 60
    assert data["end_at"] == datetime(2026, 7, 16, 21, 30, tzinfo=timezone.utc)
    # Rain occurs within the horizon → the "rain expected" flag is set.
    assert data["rain_within_2h"] is True

    # Base run time and per-hour bucket metadata (no samples on these anymore).
    assert meta["max_060"].source_timestamp == ts
    assert meta["max_060"].lead_time_minutes == 60
    assert meta["max_060"].data_start == datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    assert meta["max_060"].data_end == datetime(2026, 7, 16, 21, 30, tzinfo=timezone.utc)
    assert meta["max_060"].samples is None
    assert meta["max_120"].samples is None
    assert meta["max_000_120"].lead_time_minutes == 120
    assert meta["max_000_120"].data_start == datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    assert meta["max_000_120"].data_end == datetime(2026, 7, 16, 22, 30, tzinfo=timezone.utc)

    # The raw 5-min series (25 points, leads 0..120) rides on the rain flag.
    samples = meta["rain_within_2h"].samples
    assert len(samples) == 25
    assert samples[0]["lead"] == 0
    assert samples[-1]["lead"] == 120
    # Lead 60 is the last raining member: 1.0 mm/5min → 12 mm/h.
    lead_60 = next(s for s in samples if s["lead"] == 60)
    assert lead_60["value"] == pytest.approx(1.0)
    assert lead_60["intensity"] == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_rv_threshold_from_options_suppresses_light_rain(make_coordinator) -> None:
    """RV: light rain below the configured mm/h threshold does not trigger start/end."""
    ts = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    leads = LEADS
    values = {lead: (0.2 if lead >= 30 else 0.0) for lead in leads}  # 0.2 mm/5min = 2.4 mm/h
    reads = iter([
        (np.float32(values[lead]), rv_what(ts, lead))
        for lead in leads
    ])

    # Threshold is now an intensity (mm/h); 2.4 mm/h < 3.0 mm/h → suppressed.
    coord = make_coordinator(RadvorRV, {"precipitation_threshold": 3.0})

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rv", ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=lambda _f, _r, _c, **_kw: next(reads)),
    ):
        data, _meta = await coord._fetch_and_parse(ts)

    # 0.2 mm/5min (2.4 mm/h) never exceeds the 3.0 mm/h threshold → no rain.
    assert data["start_in"] is None
    assert data["start_at"] is None
    assert data["end_in"] is None
    assert data["rain_within_2h"] is False


@pytest.mark.asyncio
async def test_rv_threshold_is_interpreted_as_mm_per_hour(make_coordinator) -> None:
    """RV: the mm/h threshold is divided by 12 before comparison to 5-min values."""
    ts = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    leads = LEADS
    # Dry now; 0.4 mm/5min (=4.8 mm/h) at lead 30, 0.6 mm/5min (=7.2 mm/h) at lead 60.
    values = {lead: 0.0 for lead in leads}
    values[30] = 0.4
    values[60] = 0.6
    reads = iter([
        (np.float32(values[lead]), rv_what(ts, lead))
        for lead in leads
    ])

    # 6 mm/h → 0.5 mm/5min gate: 4.8 mm/h is dry, 7.2 mm/h counts.
    coord = make_coordinator(RadvorRV, {"precipitation_threshold": 6.0})

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rv", ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=lambda _f, _r, _c, **_kw: next(reads)),
    ):
        data, _meta = await coord._fetch_and_parse(ts)

    # Only the 7.2 mm/h step at lead 60 crosses the gate → start 55 min out.
    assert data["start_in"] == 55
    assert data["rain_within_2h"] is True


@pytest.mark.asyncio
async def test_rv_end_algorithm_option_selects_clearing(make_coordinator) -> None:
    """RV: the clearing algorithm looks past a lull to the last forecast wave."""
    ts = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
    leads = LEADS
    # Dry now; a wave at lead 10, a lull, then a second wave at lead 60.
    values = {lead: (1.0 if lead in (10, 60) else 0.0) for lead in leads}

    def _make_reads():
        return iter([
            (np.float32(values[lead]), rv_what(ts, lead))
            for lead in leads
        ])

    # Default (episode): ends at the first lull after the lead-10 wave.
    coord = make_coordinator(RadvorRV)
    episode_reads = _make_reads()
    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rv", ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=lambda _f, _r, _c, **_kw: next(episode_reads)),
    ):
        episode, _ = await coord._fetch_and_parse(ts)
    assert episode["start_in"] == 5
    assert episode["end_in"] == 10

    # Clearing: waits out the lull to the boundary after the lead-60 wave. A
    # new coordinator, as an options change reloads the entry.
    coord = make_coordinator(RadvorRV, {"precipitation_end_algorithm": "clearing"})
    clearing_reads = _make_reads()
    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rv", ts))),
        ),
        patch.object(products, "read_odim_composite_cell", side_effect=lambda _f, _r, _c, **_kw: next(clearing_reads)),
    ):
        clearing, _ = await coord._fetch_and_parse(ts)
    assert clearing["start_in"] == 5
    assert clearing["end_in"] == 60
    assert clearing["end_at"] == datetime(2026, 7, 16, 21, 30, tzinfo=timezone.utc)


T = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
STEP = timedelta(minutes=5)
FUTURE_LEADS = list(range(60, 121, 5))


def _release(analysis: float, forecast: dict[int, float] | None = None) -> dict[int, float | None]:
    """One RV release's steps: ``analysis`` at lead 0, dry unless ``forecast`` says."""
    values: dict[int, float | None] = {lead: 0.0 for lead in LEADS}
    values.update(forecast or {})
    values[0] = analysis
    return values


async def _adopt(make_coordinator, coord, ts: datetime, values):
    """Fetch release ``ts`` on ``coord`` and adopt it, as _async_update_data does."""
    data, meta = await rv_fetch(make_coordinator, ts, values, coord=coord)
    await coord._async_on_new_release(ts, data, meta)
    return data, meta


@pytest.mark.asyncio
async def test_rv_peak_hour_window_and_series(make_coordinator) -> None:
    """RV: the wettest rolling hour wholly ahead, its window, and the 13 hours ahead."""
    # 5-minute rain: a shower around +40 min and a heavier cell around +95 min.
    data, meta = await rv_fetch(
        make_coordinator, T, _release(0.0, {35: 0.4, 40: 0.9, 45: 0.3, 85: 0.6, 90: 1.7, 95: 2.2, 100: 0.8})
    )

    # Wettest hour ends at +95: steps +40..+95 catch the tail of the first
    # shower too (0.9 + 0.3), beating the window ending at +100 (5.6 mm).
    assert data["peak_1h"] == pytest.approx(0.9 + 0.3 + 0.6 + 1.7 + 2.2)
    peak = meta["peak_1h"]
    assert peak.lead_time_minutes == 95
    assert peak.data_start == datetime(2026, 5, 18, 16, 35, tzinfo=timezone.utc)
    assert peak.data_end == datetime(2026, 5, 18, 17, 35, tzinfo=timezone.utc)
    assert peak.source_timestamp == T
    assert [p["lead"] for p in peak.rolling_1h] == FUTURE_LEADS
    assert peak.rolling_1h[(95 - 60) // 5]["value"] == pytest.approx(data["peak_1h"])


@pytest.mark.asyncio
async def test_rv_dry_forecast_has_no_peak_window(make_coordinator) -> None:
    """RV: a dry forecast peaks at 0 mm, but has no wettest hour to point at."""
    data, meta = await rv_fetch(make_coordinator, T, _release(0.0))

    assert data["peak_1h"] == 0.0
    peak = meta["peak_1h"]
    assert (peak.data_start, peak.data_end, peak.lead_time_minutes) == (None, None, None)
    assert len(peak.rolling_1h) == len(FUTURE_LEADS)


@pytest.mark.asyncio
async def test_rv_full_series_adds_the_past_hour(make_coordinator) -> None:
    """With the option, the series starts an hour earlier, from the analyses adopted.

    The hour ending at T is the analyses of T and of the 11 releases before it
    (what RS's _000 holds); the hours ahead, and so the peak, are untouched.
    """
    coord = make_coordinator(RadvorRV, {"full_rolling_series": True})
    # The past hour: 0.5 mm in the 5 minutes ending at T-55, 1.0 mm at T-5.
    for k in range(11, 0, -1):
        await _adopt(make_coordinator, coord, T - k * STEP, _release({11: 0.5, 1: 1.0}.get(k, 0.0)))
    current = _release(2.0, {5: 0.25, 90: 3.0})
    data, meta = await _adopt(make_coordinator, coord, T, current)

    series = meta["peak_1h"].rolling_1h
    assert [p["lead"] for p in series] == LEADS
    assert series[0] == {
        "lead": 0,
        "start": "2026-05-18T15:00:00+00:00",
        "end": "2026-05-18T16:00:00+00:00",
        "value": pytest.approx(0.5 + 1.0 + 2.0),
    }
    # Ending at T+5: the step ending at T-55 has left the hour, step +5 joined it.
    assert series[1]["value"] == pytest.approx(1.0 + 2.0 + 0.25)
    assert (series[6]["start"], series[6]["end"]) == (
        "2026-05-18T15:30:00+00:00",
        "2026-05-18T16:30:00+00:00",
    )

    plain_data, plain_meta = await rv_fetch(make_coordinator, T, current)
    assert series[len(LEADS) - len(FUTURE_LEADS):] == plain_meta["peak_1h"].rolling_1h
    assert data["peak_1h"] == plain_data["peak_1h"] == pytest.approx(3.0)
    for attr in ("lead_time_minutes", "data_start", "data_end"):
        assert getattr(meta["peak_1h"], attr) == getattr(plain_meta["peak_1h"], attr), attr


@pytest.mark.asyncio
async def test_rv_full_series_waits_for_a_whole_past_hour(make_coordinator) -> None:
    """Right after a restart, or a release never adopted, the past hour is missing.

    The series then has the 13 hours ahead, as without the option, until all
    11 analyses before the release are in again.
    """
    coord = make_coordinator(RadvorRV, {"full_rolling_series": True})
    for k in range(10, 0, -1):  # started at T-50, so T-55 was never adopted
        await _adopt(make_coordinator, coord, T - k * STEP, _release(1.0))
    _, meta = await _adopt(make_coordinator, coord, T, _release(1.0))
    assert [p["lead"] for p in meta["peak_1h"].rolling_1h] == FUTURE_LEADS

    # One release later the past hour (T-50..T) is complete.
    _, meta = await _adopt(make_coordinator, coord, T + STEP, _release(1.0))
    series = meta["peak_1h"].rolling_1h
    assert [p["lead"] for p in series] == LEADS
    assert series[0]["value"] == pytest.approx(12 * 1.0)


@pytest.mark.asyncio
async def test_rv_without_the_option_the_series_stays_ahead(make_coordinator) -> None:
    """Without the option, a whole hour of releases still gives the 13 hours ahead."""
    coord = make_coordinator(RadvorRV)
    for k in range(12, -1, -1):
        _, meta = await _adopt(make_coordinator, coord, T - k * STEP, _release(1.0))
    assert [p["lead"] for p in meta["peak_1h"].rolling_1h] == FUTURE_LEADS


@pytest.mark.asyncio
async def test_rv_intensity_now_is_the_analysis_step_as_a_rate(make_coordinator) -> None:
    """RV: lead 0 (the 5 minutes ending at T) becomes mm/h, with its window."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    rv: dict[int, float | None] = {lead: 0.0 for lead in LEADS}
    # The float32 reading carries noise below the ODIM 0.001 mm resolution.
    rv.update({0: 0.123, 5: 2.0})
    data, meta = await rv_fetch(make_coordinator, ts, rv)

    assert data["amount_000"] == 0.123
    assert data["intensity_000"] == 1.476  # exact at 0.001 mm resolution, not 1.47600001
    assert meta["intensity_000"].lead_time_minutes == 0
    assert meta["intensity_000"].source_timestamp == ts
    assert meta["intensity_000"].data_start == datetime(2026, 5, 18, 15, 55, tzinfo=timezone.utc)
    assert meta["intensity_000"].data_end == ts


@pytest.mark.asyncio
async def test_rv_intensity_now_is_unknown_without_the_analysis(make_coordinator) -> None:
    """RV: a missing lead-0 member leaves both values None rather than 0."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    rv: dict[int, float | None] = {lead: 0.0 for lead in LEADS}
    rv[0] = None
    data, _ = await rv_fetch(make_coordinator, ts, rv)

    assert data["intensity_000"] is None
    assert data["amount_000"] is None


@pytest.mark.asyncio
async def test_rv_peak_hour_treats_missing_step_as_dry(make_coordinator) -> None:
    """RV: a missing 5-minute member counts as 0, as RS does at the coverage edge."""
    ts = datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    rv: dict[int, float | None] = {lead: 0.0 for lead in LEADS}
    rv.update({5: None, 60: 1.0, 65: 2.0})
    data, meta = await rv_fetch(make_coordinator, ts, rv)

    assert data["peak_1h"] == pytest.approx(3.0)
    # Lead 5 opens the T+0..T+60 window; its start falls back to end - 60 min.
    first = meta["peak_1h"].rolling_1h[0]
    assert first == {
        "lead": 60,
        "start": "2026-05-18T16:00:00+00:00",
        "end": "2026-05-18T17:00:00+00:00",
        "value": pytest.approx(1.0),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["wet", "nodata"])
async def test_rv_real_analysis_through_the_fill_path(make_coordinator, kind) -> None:
    """A real RV analysis, read by range as a missed step is filled."""
    content, _ = real_member("rv")
    cell = real_cells("rv")[kind]
    release = real_release("rv")
    coord = make_coordinator(RadvorRV)
    coord.coords = (cell["lat"], cell["lon"])
    # The real analysis first, as DWD orders them; the forecast members are
    # placeholders, and the range read must not need them.
    archive = make_radvor_tar("rv", release, lambda lead: content if lead == 0 else b"x")
    server = RangeServer(archive)

    with patch.object(products, "async_get", side_effect=server.async_get):
        value = await coord._async_fetch_analysis(release)

    if cell["value"] is None:
        assert value is None
    else:
        assert value == pytest.approx(cell["value"], abs=5e-4)
    assert server.whole_downloads == 0
