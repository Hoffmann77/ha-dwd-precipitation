"""The database: schema, migrations, the sparse rule and atomic releases."""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from scripts.precip_eval import db
from scripts.precip_eval.stations import Station
from scripts.precip_eval.windows import CELL_COLUMNS, StationCell


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.sqlite")
    yield connection
    connection.close()


def test_connect_creates_the_schema_once(tmp_path):
    path = tmp_path / "test.sqlite"
    db.connect(path).close()

    conn = db.connect(path)  # a second start migrates nothing

    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    tables = {r for (r,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"stations", "grids", "station_cells", "releases", "radar"} <= tables


def test_a_newer_schema_is_refused(tmp_path):
    path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    conn.close()

    with pytest.raises(RuntimeError, match="newer"):
        db.connect(path)


def test_tables_are_strict(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO grids (grid_id, description) VALUES ('one', 'x')")


def test_sync_stations_updates_a_moved_station(conn):
    db.sync_stations(conn, [Station(1, "A", 50.0, 8.0, 100.0, "Hessen")])
    db.sync_stations(conn, [Station(1, "A", 50.1, 8.0, 100.0, "Hessen")])

    assert conn.execute("SELECT lat FROM stations").fetchall() == [(50.1,)]


def test_radar_rows_skip_dry_windows_and_keep_no_data():
    dry = np.zeros(len(CELL_COLUMNS))
    wet = np.zeros(len(CELL_COLUMNS))
    wet[12] = 1544.0
    wet[0] = np.nan

    rows = db.radar_rows(1000, 5, [1, 2], np.vstack([dry, wet]))

    assert len(rows) == 1
    release, lead, station_id, *cells = rows[0]
    assert (release, lead, station_id) == (1000, 5, 2)
    assert cells[0] is None
    assert cells[12] == 1544
    assert all(type(c) is int for c in cells[1:])


def test_a_release_is_stored_completely_or_not_at_all(conn):
    db.sync_stations(conn, [Station(1, "A", 50.0, 8.0, 100.0, "Hessen")])
    gid = db.grid_id(conn, '{"grid": 1}')
    db.store_station_cells(conn, gid, [StationCell(1, 10, 10, 0.5, 0.5)])
    row = (1000, 5, 1, *([1] * len(CELL_COLUMNS)))
    db.store_release(conn, 1000, gid, 1001, 1, [row])

    # The same release again: its rows clash, so nothing of it is written.
    other = (1000, 10, 1, *([2] * len(CELL_COLUMNS)))
    with pytest.raises(sqlite3.IntegrityError):
        db.store_release(conn, 1000, gid, 1002, 1, [other, row])

    assert conn.execute("SELECT lead FROM radar").fetchall() == [(5,)]
    assert db.logged_releases(conn, 0) == {1000}


def test_grid_id_is_stable(conn):
    assert db.grid_id(conn, "a") == db.grid_id(conn, "a") != db.grid_id(conn, "b")
