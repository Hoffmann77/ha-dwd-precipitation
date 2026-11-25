"""RV's neighbourhood evaluation: nearby start, nearest rain, where it heads."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from custom_components.dwd_precipitation import products
from custom_components.dwd_precipitation.const import CONF_NEIGHBOURHOOD
from custom_components.dwd_precipitation.products import RadvorRV
from custom_components.dwd_precipitation.utils import AsyncResponse

from tests.factories.radvor import LEADS, make_radvor_tar
from tests.integration.product_helpers import rv_fetch, rv_what

TS = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
SIZE = 21  # a 10 km reach around the location, 1 km cells
CENTER = (SIZE // 2, SIZE // 2)


def shower(rows: range, col_at_lead_0: int) -> Callable[[int], np.ndarray]:
    """A 1 mm shower over ``rows``, one cell wide, moving 1 km east per step."""

    def window(lead: int) -> np.ndarray:
        w = np.zeros((SIZE, SIZE), dtype=np.float32)
        col = col_at_lead_0 + lead // 5
        if 0 <= col < SIZE:
            w[rows, col] = 1.0
        return w

    return window


async def fetch(make_coordinator, window: Callable[[int], np.ndarray], options=None):
    """Run RV's fetch with every lead's window drawn by ``window``."""

    def _near(fileobj, _lat, _lon, _radius_m, **_kw):
        lead = int(fileobj.getvalue())  # make_radvor_tar's payload is the lead
        w = window(lead)
        return w[CENTER], w, CENTER, (1000.0, 1000.0), rv_what(TS, lead)

    coord = make_coordinator(RadvorRV, options)
    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=make_radvor_tar("rv", TS))),
        ),
        patch.object(products, "read_odim_composite_near", side_effect=_near),
    ):
        return await coord._fetch_and_parse(TS)


def series(meta, key: str) -> list:
    return [s[key] for s in meta["rain_within_2h"].samples]


@pytest.mark.asyncio
async def test_rain_heading_for_the_location(make_coordinator) -> None:
    """A shower 5 km west moving east: the cells west of the location count."""
    data, meta = await fetch(make_coordinator, shower(range(10, 11), 5))

    # Over the own cell at lead 25, in the cell west of it at lead 20.
    assert data["start_in"] == 20
    assert data["area_start_in"] == 15
    assert data["area_start_at"] == TS + timedelta(minutes=15)
    assert data["nearest_km"] == 5.0
    assert data["nearest_bearing"] == 270
    assert data["nearest_direction"] == "W"
    assert data["approaching"] is True
    assert data["closest_approach_km"] == 0.0
    assert data["closest_approach_in"] == 25
    assert data["approach_from_bearing"] == 270
    assert data["approach_from"] == "W"

    # Once it has passed (lead 30, the cell east of the location) it no
    # longer counts: only the cells on the side it comes from do.
    area = series(meta, "area_value")
    assert [lead for lead, v in zip(LEADS, area) if v] == [20, 25]
    assert series(meta, "event_value") == area


@pytest.mark.asyncio
async def test_rain_passing_by_counts_only_on_the_own_cell(make_coordinator) -> None:
    """A shower 2-3 km north moving east grazes the 1.5 km disk but goes by."""
    data, meta = await fetch(make_coordinator, shower(range(7, 10), 5))

    assert data["approaching"] is False
    assert data["closest_approach_km"] == 2.0
    # Its southern edge is 1 km north, within the disk, but it does not come
    # towards the own cell: neither the nearby start nor the events see it.
    assert not any(series(meta, "area_value"))
    assert data["area_start_in"] is None
    assert series(meta, "event_value") == series(meta, "value")
    assert not any(series(meta, "event_value"))


@pytest.mark.asyncio
async def test_rain_beside_the_track_does_not_count(make_coordinator) -> None:
    """A wide shower coming from the west: only cells west of the location count."""

    def window(lead: int) -> np.ndarray:
        # A band 3 cells high coming from the west, plus a speck 1 km east of
        # the location that stays put (a cell error behind it).
        w = shower(range(9, 12), 3)(lead)
        w[CENTER[0], CENTER[1] + 1] = 2.0
        return w

    data, meta = await fetch(make_coordinator, window)

    assert data["approaching"] is True
    assert data["approach_from"] == "W"
    # The speck east of the location (2 mm) never counts, the band does (1 mm).
    assert max(v for v in series(meta, "area_value") if v is not None) == 1.0


@pytest.mark.asyncio
async def test_rain_moving_away(make_coordinator) -> None:
    """A shower over the location moving east: it is leaving."""
    data, meta = await fetch(make_coordinator, shower(range(10, 11), 10))

    assert data["approaching"] is False
    assert data["nearest_km"] == 0.0
    assert data["nearest_bearing"] is None
    assert data["nearest_direction"] is None
    assert series(meta, "event_value") == series(meta, "value")


@pytest.mark.asyncio
async def test_dry_neighbourhood(make_coordinator) -> None:
    """No rain within reach: no track, no nearest rain, no nearby start."""
    data, _ = await fetch(make_coordinator, lambda _lead: np.zeros((SIZE, SIZE), np.float32))

    assert data["approaching"] is False
    assert data["closest_approach_km"] is None
    assert data["nearest_km"] is None
    assert data["area_start_in"] is None


@pytest.mark.asyncio
async def test_off_reads_the_own_cell_only(make_coordinator) -> None:
    """With the option off, RV reads one cell and has no neighbourhood values."""
    with patch.object(products, "read_odim_composite_near") as near:
        data, meta = await rv_fetch(
            make_coordinator,
            TS,
            {lead: 0.0 for lead in LEADS},
            coord=make_coordinator(RadvorRV, {CONF_NEIGHBOURHOOD: False}),
        )
    near.assert_not_called()
    assert "nearest_km" not in data
    assert "area_start_in" not in data
    assert "area_value" not in meta["rain_within_2h"].samples[0]
