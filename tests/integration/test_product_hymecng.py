"""HymecNG: the precipitation-type class at the cell."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.dwd_precipitation import products
from custom_components.dwd_precipitation.const import PRECIP_TYPE_BY_INDEX
from custom_components.dwd_precipitation.products import HymecNG
from custom_components.dwd_precipitation.utils import AsyncResponse

from tests.factories.odim import DE1200_WHERE, make_hymecng_h5
from tests.factories.real import real_cells, real_member, real_release


def _hymecng_reader(class_value: int, nodata: int = 255, undetect: int = 254):
    """Return a fake read_odim_classification_at yielding ``class_value``."""
    dataset_what = {
        "prodname": "HymecNG_top_view",
        "product": "COMP",
        "startdate": "20260729", "starttime": "173000",
        "enddate": "20260729", "endtime": "173000",
    }
    moment_what = {"quantity": "CLASS", "nodata": float(nodata), "undetect": float(undetect)}
    return lambda _f, _lat, _lon, **_kw: (class_value, dataset_what, moment_what)


@pytest.mark.asyncio
async def test_hymecng_fetch_maps_class_index_to_label(make_coordinator) -> None:
    """HymecNG: end-to-end fetch + real reader maps the cell class to a label."""
    ts = datetime(2026, 7, 29, 17, 30, tzinfo=timezone.utc)
    hd5 = make_hymecng_h5(shape=(DE1200_WHERE["ysize"], DE1200_WHERE["xsize"]), fill=7)  # SNOW everywhere

    coord = make_coordinator(HymecNG)

    get_mock = AsyncMock(return_value=AsyncResponse(content=hd5.getvalue()))
    with patch.object(products, "async_get", new=get_mock):
        data, meta = await coord._fetch_and_parse(ts)

    assert data == {"precipitation_type": "snow"}
    meta = meta["precipitation_type"]
    assert meta.source_product == "HymecNG_top_view"
    assert meta.source_timestamp == ts
    assert meta.data_end == ts
    # The single ODIM_H5 file (no tar) is addressed by the expected URL.
    assert get_mock.call_args.args[0].endswith(
        "/composite/hymecng/composite_HymecNG_20260729_1730_000-hd5"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "class_value, expected",
    [
        (0, "no_precipitation"),
        (3, "rain"),
        (5, "freezing_rain"),
        (9, "hail"),
        (10, "large_hail"),
        (254, "no_precipitation"),  # undetect → scanned, dry
        (255, None),                # nodata → outside coverage → unavailable
        (200, None),                # unexpected index → unavailable
    ],
)
async def test_hymecng_class_and_sentinel_mapping(make_coordinator, class_value, expected) -> None:
    """HymecNG: class indices, undetect, and nodata map to the right sensor state."""
    ts = datetime(2026, 7, 29, 17, 30, tzinfo=timezone.utc)
    coord = make_coordinator(HymecNG)

    with (
        patch.object(
            products,
            "async_get",
            new=AsyncMock(return_value=AsyncResponse(content=b"x")),
        ),
        patch.object(
            products,
            "read_odim_classification_at",
            side_effect=_hymecng_reader(class_value),
        ),
    ):
        data, _meta = await coord._fetch_and_parse(ts)

    assert data == {"precipitation_type": expected}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["wet", "undetect", "nodata"])
async def test_hymecng_real_file(make_coordinator, kind) -> None:
    """A real HymecNG file through the production path, at three kinds of cell."""
    content, _ = real_member("hymecng")
    cell = real_cells("hymecng")[kind]
    coord = make_coordinator(HymecNG)
    coord.coords = (cell["lat"], cell["lon"])

    with patch.object(
        products, "async_get", new=AsyncMock(return_value=AsyncResponse(content=content))
    ):
        data, meta = await coord._fetch_and_parse(real_release("hymecng"))

    if kind == "undetect":
        expected = "no_precipitation"  # scanned, no echo
    elif kind == "nodata":
        expected = None  # outside coverage: unknown
    else:
        expected = PRECIP_TYPE_BY_INDEX[cell["value"]]
    assert data == {"precipitation_type": expected}
    assert meta["precipitation_type"].source_timestamp == real_release("hymecng")


@pytest.mark.asyncio
async def test_hymecng_hands_each_adopted_type_to_the_rain_events_tracker(
    make_coordinator, make_entry
) -> None:
    from custom_components.dwd_precipitation.products import RadvorRV

    entry = make_entry({"rain_events": True})
    rv = make_coordinator(RadvorRV, entry=entry)
    coord = make_coordinator(HymecNG, entry=entry)
    coord.attach_rain_tracker(rv.rain_tracker)
    ts = datetime(2026, 7, 29, 17, 30, tzinfo=timezone.utc)

    await coord._async_on_new_release(ts, {"precipitation_type": "snow"}, {})
    later = ts.replace(minute=35)
    await coord._async_on_new_release(later, {"precipitation_type": None}, {})

    state = rv.rain_tracker.state
    assert state.types == {ts: "snow"}
    assert state.type_nodata == {later}  # no type for the cell: not refetched


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["wet", "undetect", "nodata"])
async def test_hymecng_with_rain_events_reads_the_nearest_type(
    make_coordinator, make_entry, kind
) -> None:
    """With a tracker, a real file also gives the nearest precipitation's type."""
    from custom_components.dwd_precipitation.products import RadvorRV
    from radar.nearby import nearest_class
    from radar.odim import read_odim_classification

    content, _ = real_member("hymecng")
    cell = real_cells("hymecng")[kind]
    entry = make_entry({"rain_events": True})
    rv = make_coordinator(RadvorRV, entry=entry)
    coord = make_coordinator(HymecNG, entry=entry)
    coord.attach_rain_tracker(rv.rain_tracker)
    coord.coords = (cell["lat"], cell["lon"])

    with patch.object(
        products, "async_get", new=AsyncMock(return_value=AsyncResponse(content=content))
    ):
        data, _meta = await coord._fetch_and_parse(real_release("hymecng"))

    whole, _, _ = read_odim_classification(io.BytesIO(content))
    expected = nearest_class(
        whole, (cell["row"], cell["col"]), (1000.0, 1000.0), range(2, 11), 5000
    )
    assert data["precipitation_type_nearby"] == (
        None if expected is None else PRECIP_TYPE_BY_INDEX[expected]
    )
    if kind == "wet":
        # Rain on the own cell is the nearest there is.
        assert data["precipitation_type_nearby"] == PRECIP_TYPE_BY_INDEX[cell["value"]]


@pytest.mark.asyncio
async def test_hymecng_without_rain_events_hands_nothing_on(make_coordinator) -> None:
    coord = make_coordinator(HymecNG)
    ts = datetime(2026, 7, 29, 17, 30, tzinfo=timezone.utc)
    await coord._async_on_new_release(ts, {"precipitation_type": "snow"}, {})
    assert coord._rain_tracker is None


@pytest.mark.asyncio
async def test_hymecng_fetches_a_past_type_and_checks_its_moment(make_coordinator) -> None:
    coord = make_coordinator(HymecNG)
    ts = datetime(2026, 7, 29, 17, 30, tzinfo=timezone.utc)  # the reader's moment
    hd5 = make_hymecng_h5(shape=(DE1200_WHERE["ysize"], DE1200_WHERE["xsize"]), fill=8)
    with (
        patch.object(products, "async_get", new=AsyncMock(return_value=AsyncResponse(content=hd5.getvalue()))),
        patch.object(products, "read_odim_classification_at", side_effect=_hymecng_reader(8)),
    ):
        assert await coord._async_fetch_type(ts) == PRECIP_TYPE_BY_INDEX[8]
        # A file for another moment is never recorded as this step's type.
        with pytest.raises(ValueError, match="is for"):
            await coord._async_fetch_type(ts.replace(minute=35))
    assert coord.curr_release is None  # a past release is not adopted
