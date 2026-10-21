"""Coverage logging: one line when the location loses its data, one when it is back.

A cell without data (a radar out of DWD's composite) does not fail the fetch,
so these lines are the only trace of it in the log.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.dwd_precipitation import PRODUCT_CLASSES, products
from custom_components.dwd_precipitation import coordinator as coordinator_mod
from custom_components.dwd_precipitation.coordinator import ProductMetadata
from custom_components.dwd_precipitation.products import HymecNG, RadolanRW, RadvorRS
from custom_components.dwd_precipitation.radar.nowcast import LEADS
from custom_components.dwd_precipitation.utils import AsyncResponse

from tests.factories.real import real_cells, real_member, real_release

UTC = timezone.utc
FIRST = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
ALL = ("deasb", "deboo", "depro", "deros")
WITHOUT_PRO = ("deasb", "deboo", "deros")


async def _feed(coord, releases) -> None:
    """Adopt one hourly RW release per (amount, radars), from FIRST on."""
    for hour, (amount, radars) in enumerate(releases):
        release = FIRST + timedelta(hours=hour)
        meta = ProductMetadata("RW", release, radars=radars)
        coord._fetch_and_parse = AsyncMock(return_value=({"amount": amount}, {"amount": meta}))
        now = release + coord.release_delay
        with patch.object(coordinator_mod.dt_util, "utcnow", return_value=now):
            await coord._async_update_data()
        assert coord.curr_release == release
    coord._cancel_stale_check()


def _records(caplog, level: int) -> list[str]:
    """Return the coordinator's messages at ``level``."""
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == coordinator_mod.__name__ and r.levelno == level
    ]


@pytest.mark.asyncio
async def test_loss_and_recovery_are_logged_once_each(make_coordinator, caplog) -> None:
    """One WARNING when the data goes, naming the radar; one INFO when it is back."""
    caplog.set_level(logging.INFO, logger=coordinator_mod.__name__)
    coord = make_coordinator(RadolanRW)

    await _feed(
        coord,
        [
            (0.4, ALL),
            (0.0, ALL),
            (None, WITHOUT_PRO),  # 11:00: depro drops out
            (None, WITHOUT_PRO),
            (None, WITHOUT_PRO),
            (0.2, ALL),  # 14:00: back
            (0.1, ALL),
        ],
    )

    warnings = _records(caplog, logging.WARNING)
    assert len(warnings) == 1
    assert warnings[0] == (
        "Home RW hourly precipitation: no radar data for your location in the "
        "2026-10-13 11:00 UTC release (radar(s) missing from the DWD composite: "
        "depro). The location is currently outside DWD's radar coverage; this is "
        "a DWD outage, not a configuration problem. The affected sensors show "
        '"unknown" until DWD restores coverage, and recover on their own.'
    )
    assert warnings[0].isascii()

    infos = _records(caplog, logging.INFO)
    assert len(infos) == 1
    assert "radar data for your location again from the 2026-10-13 14:00 UTC release" in infos[0]


@pytest.mark.asyncio
async def test_every_outage_is_logged(make_coordinator, caplog) -> None:
    """The no-repeat rule is per run: a second outage warns again."""
    caplog.set_level(logging.INFO, logger=coordinator_mod.__name__)
    coord = make_coordinator(RadolanRW)

    await _feed(
        coord,
        [(0.0, ALL), (None, WITHOUT_PRO), (0.0, ALL), (None, ("deasb", "deros")), (0.0, ALL)],
    )

    warnings = _records(caplog, logging.WARNING)
    assert len(warnings) == 2
    assert "missing from the DWD composite: depro)" in warnings[0]
    assert "missing from the DWD composite: deboo, depro)" in warnings[1]
    assert len(_records(caplog, logging.INFO)) == 2


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (None, WITHOUT_PRO),  # the last release with data did not say
        (ALL, None),  # this one does not say
        (ALL, ALL),  # every radar is in: the cell is masked for another reason
    ],
)
@pytest.mark.asyncio
async def test_loss_without_known_missing_radars_names_none(
    make_coordinator, caplog, before, after
) -> None:
    coord = make_coordinator(RadolanRW)

    await _feed(coord, [(0.0, before), (None, after)])

    [warning] = _records(caplog, logging.WARNING)
    assert "no radar data for your location in the 2026-10-13 10:00 UTC release." in warning
    assert "missing" not in warning


@pytest.mark.asyncio
async def test_no_data_from_the_start_is_logged_once(make_coordinator, caplog) -> None:
    """A location without data in the first release: one WARNING, not an outage."""
    caplog.set_level(logging.INFO, logger=coordinator_mod.__name__)
    coord = make_coordinator(RadolanRW)

    await _feed(coord, [(None, ALL)] * 4)

    [warning] = _records(caplog, logging.WARNING)
    assert warning == (
        "Home RW hourly precipitation: no radar data for your location in the "
        "2026-10-13 09:00 UTC release, the first one read. Either the location is "
        "outside the area this product covers, or a DWD radar is out. The affected "
        'sensors show "unknown" while this lasts; this is logged again only when '
        "data arrives."
    )
    assert warning.isascii()
    assert not _records(caplog, logging.INFO)


@pytest.mark.asyncio
async def test_data_after_a_start_without_is_said(make_coordinator, caplog) -> None:
    caplog.set_level(logging.INFO, logger=coordinator_mod.__name__)
    coord = make_coordinator(RadolanRW)

    await _feed(coord, [(None, WITHOUT_PRO), (0.0, ALL)])

    assert len(_records(caplog, logging.WARNING)) == 1
    [info] = _records(caplog, logging.INFO)
    assert "radar data for your location again from the 2026-10-13 10:00 UTC release" in info


@pytest.mark.asyncio
async def test_data_throughout_logs_nothing(make_coordinator, caplog) -> None:
    caplog.set_level(logging.INFO, logger=coordinator_mod.__name__)
    coord = make_coordinator(RadolanRW)

    await _feed(coord, [(0.0, ALL), (1.2, WITHOUT_PRO), (0.0, ALL)])

    assert not _records(caplog, logging.WARNING)
    assert not _records(caplog, logging.INFO)


@pytest.mark.asyncio
async def test_a_release_held_already_is_not_counted_again(make_coordinator, caplog) -> None:
    """Refreshes between releases return the held data and log nothing."""
    coord = make_coordinator(RadolanRW)
    await _feed(coord, [(0.0, ALL), (None, WITHOUT_PRO)])
    caplog.clear()

    now = FIRST + timedelta(hours=1) + coord.release_delay + timedelta(minutes=10)
    with patch.object(coordinator_mod.dt_util, "utcnow", return_value=now):
        await coord._async_update_data()

    assert coord._fetch_and_parse.await_count == 1
    assert not _records(caplog, logging.WARNING)


@pytest.mark.parametrize("key", ["last_60", "next_60", "next_60_120"])
def test_rs_any_hour_without_data_counts(make_coordinator, caplog, key) -> None:
    """RS: an hour without data turns its sensor "unknown", so it counts."""
    coord = make_coordinator(RadvorRS)
    hours = {"last_60": 0.1, "next_60": 0.2, "next_60_120": 0.3, "next_120": 0.5}
    meta = {k: ProductMetadata("RS", FIRST, radars=ALL) for k in hours}

    coord._track_coverage(FIRST, hours, meta)
    coord._track_coverage(FIRST + timedelta(minutes=5), {**hours, key: None}, {
        k: ProductMetadata("RS", FIRST, radars=WITHOUT_PRO) for k in hours
    })

    [warning] = _records(caplog, logging.WARNING)
    assert warning.startswith("Home RS precipitation nowcast: no radar data")
    assert "missing from the DWD composite: depro)" in warning


def test_hymecng_counts_its_type(make_coordinator, caplog) -> None:
    """HymecNG: no class for the cell is no data; "no_precipitation" is data."""
    coord = make_coordinator(HymecNG)
    meta = {"precipitation_type": ProductMetadata("HymecNG", FIRST)}

    coord._track_coverage(FIRST, {"precipitation_type": "no_precipitation"}, meta)
    assert not _records(caplog, logging.WARNING)
    coord._track_coverage(FIRST, {"precipitation_type": None}, meta)
    assert len(_records(caplog, logging.WARNING)) == 1


def test_every_product_is_watched() -> None:
    """Each product names the sub-keys whose None means no data."""
    for cls in PRODUCT_CLASSES:
        assert cls.COVERAGE_KEYS, cls.__name__


@pytest.mark.asyncio
async def test_real_files_carry_their_radars(make_coordinator) -> None:
    """The production path puts each file's radars into the metadata."""
    content, _ = real_member("hymecng")
    cell = real_cells("hymecng")["wet"]
    coord = make_coordinator(HymecNG)
    coord.coords = (cell["lat"], cell["lon"])
    with patch.object(
        products, "async_get", new=AsyncMock(return_value=AsyncResponse(content=content))
    ):
        _, meta = await coord._fetch_and_parse(real_release("hymecng"))
    assert "depro" in meta["precipitation_type"].radars

    rw = (Path(__file__).parents[1] / "fixtures" / "radolan_rw_sample.hdf5").read_bytes()
    coord = make_coordinator(RadolanRW)
    with patch.object(
        products, "async_get", new=AsyncMock(return_value=AsyncResponse(content=rw))
    ):
        _, meta = await coord._fetch_and_parse(datetime(2026, 10, 12, 12, 50, tzinfo=UTC))
    assert len(meta["amount"].radars) == 17


def test_rv_names_the_analysis_radars() -> None:
    """RV's values carry the radars of its analysis, the member it is watched by."""
    cells = {lead: (0.0, {"nodes": ALL} if lead == 0 else {}) for lead in LEADS}
    parts = products._rv_intensities(products._RvSeries.from_cells(cells))
    assert products.RadvorRV.COVERAGE_KEYS == ("amount_000",)
    assert parts["amount_000"][1].radars == ALL
