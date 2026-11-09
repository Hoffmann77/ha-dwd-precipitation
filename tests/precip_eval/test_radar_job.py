"""The radar job: listing, gaps, and a release logged from a real RV member."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from radar.nowcast import LEADS
from radar.tar_range import member_names
from radar.urls import radvor_prefix
from tests.factories.radvor import radvor_archive

from scripts.precip_eval import db, radar_job
from scripts.precip_eval.scheduler import Job
from scripts.precip_eval.windows import CELL_COLUMNS, cut_windows, station_cells

TS = datetime(2026, 10, 13, 18, 45, tzinfo=UTC)

LISTING = """
<a href="composite_rv_20261013_1840.tar">composite_rv_20261013_1840.tar</a> 13-Oct-2026 18:44  2252480
<a href="composite_rv_20261013_1845.tar">composite_rv_20261013_1845.tar</a> 13-Oct-2026 18:49  2252480
<a href="composite_rv_LATEST.tar">composite_rv_LATEST.tar</a>             13-Oct-2026 18:49  2252480
"""


def test_listing_gives_the_releases_not_latest():
    assert radar_job.parse_listing(LISTING) == [TS - timedelta(minutes=5), TS]


def test_missing_releases_are_the_unlogged_ones_oldest_first():
    listed = [TS, TS - timedelta(minutes=5), TS - timedelta(minutes=10)]
    logged = {int((TS - timedelta(minutes=5)).timestamp())}

    assert radar_job.missing_releases(listed, logged) == [TS - timedelta(minutes=10), TS]


def _release_tar(tmp_path, member: bytes, skip: set[int] = frozenset()):
    names = member_names(radvor_prefix("rv", TS), LEADS)
    archive = radvor_archive(
        {name: member for name, lead in zip(names, LEADS) if lead not in skip}
    )
    path = tmp_path / "release.tar"
    path.write_bytes(archive)
    return path


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.sqlite")
    yield connection
    connection.close()


def test_a_release_is_logged_with_every_wet_window(
    tmp_path, conn, rv_member, wet_station, city_stations
):
    grid, values, member = rv_member
    stations = [wet_station, *city_stations]
    db.sync_stations(conn, stations)
    tar = _release_tar(tmp_path, member, skip={60})

    n_rows = radar_job.log_release(conn, stations, TS, tar, TS + timedelta(minutes=5))

    # Every member is the same analysis here, so each present lead stores the
    # same windows: those of the stations that are not dry.
    cells = station_cells(grid, stations)
    windows = cut_windows(values, cells)
    wet = [c.station_id for c, w in zip(cells, windows) if not np.all(w == 0)]
    assert wet and wet_station.station_id in wet
    assert n_rows == len(wet) * (len(LEADS) - 1)

    release, gid, leads_present = conn.execute(
        "SELECT release, grid_id, leads_present FROM releases"
    ).fetchone()
    assert release == int(TS.timestamp())
    assert leads_present == (1 << len(LEADS)) - 1 - (1 << LEADS.index(60))
    assert conn.execute("SELECT count(*) FROM radar WHERE lead = 60").fetchone()[0] == 0

    centre = conn.execute(
        "SELECT c22 FROM radar WHERE station_id = ? AND lead = 0", (wet_station.station_id,)
    ).fetchone()[0]
    assert centre == 1544
    stored = conn.execute(
        "SELECT row, col FROM station_cells WHERE grid_id = ? AND station_id = ?",
        (gid, wet_station.station_id),
    ).fetchone()
    assert stored == (584, 247)


def test_a_release_without_a_readable_member_is_not_logged(tmp_path, conn, wet_station):
    tar = _release_tar(tmp_path, b"not hdf5")

    with pytest.raises(ValueError, match="no member"):
        radar_job.log_release(conn, [wet_station], TS, tar, TS)

    assert db.logged_releases(conn, 0) == set()


def test_cell_columns_match_the_table(conn):
    columns = [r[1] for r in conn.execute("PRAGMA table_info(radar)")]
    assert columns == ["release", "lead", "station_id", *CELL_COLUMNS]


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC), datetime(2026, 11, 9, 12, 0, 30, tzinfo=UTC)),
        (datetime(2026, 11, 9, 12, 0, 30, tzinfo=UTC), datetime(2026, 11, 9, 12, 5, 30, tzinfo=UTC)),
        (datetime(2026, 11, 9, 12, 3, 0, tzinfo=UTC), datetime(2026, 11, 9, 12, 5, 30, tzinfo=UTC)),
    ],
)
def test_job_grid(now, expected):
    job = Job("radar", lambda: None, timedelta(minutes=5), timedelta(seconds=30))

    assert job.next_after(now) == expected
