"""The service's SQLite database: schema, migrations and the writes.

Plain SQL on the standard library's sqlite3. The schema's version lives in
``PRAGMA user_version``; ``connect`` brings any older database up to date, so
the service never needs setting up by hand.

"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from .stations import Station
from .windows import CELL_COLUMNS, StationCell

# Each entry takes the schema from the version before it to its own number
# (its index + 1). Append, never edit: a database is at a version because it
# ran exactly these statements.
MIGRATIONS: tuple[str, ...] = (
    f"""
    CREATE TABLE stations (
        station_id INTEGER PRIMARY KEY,
        name       TEXT NOT NULL,
        lat        REAL NOT NULL,
        lon        REAL NOT NULL,
        altitude   REAL NOT NULL,
        state      TEXT NOT NULL
    ) STRICT;

    -- Every distinct grid a release was read on (the file's /where), so a
    -- grid DWD moves or resizes keeps old and new releases correct.
    CREATE TABLE grids (
        grid_id     INTEGER PRIMARY KEY,
        description TEXT NOT NULL UNIQUE
    ) STRICT;

    CREATE TABLE station_cells (
        grid_id    INTEGER NOT NULL REFERENCES grids,
        station_id INTEGER NOT NULL REFERENCES stations,
        row        INTEGER NOT NULL,
        col        INTEGER NOT NULL,
        frac_x     REAL NOT NULL,   -- 0 = the cell's west edge, 1 = east
        frac_y     REAL NOT NULL,   -- 0 = the cell's south edge, 1 = north
        PRIMARY KEY (grid_id, station_id)
    ) STRICT;

    -- One row per logged release. leads_present has bit k set when the
    -- member of lead 5*k was read: a radar row missing for a present lead
    -- means an all-dry window, for an absent lead "not read".
    CREATE TABLE releases (
        release       INTEGER PRIMARY KEY,   -- nominal time, Unix seconds UTC
        grid_id       INTEGER NOT NULL REFERENCES grids,
        logged_at     INTEGER NOT NULL,
        leads_present INTEGER NOT NULL
    ) STRICT;

    -- Sparse: a window whose 25 cells are all 0 is not stored. Cells are in
    -- thousandths of a mm, NULL for no data; c00 is the north-west corner,
    -- c22 the station's own cell.
    CREATE TABLE radar (
        release    INTEGER NOT NULL,
        lead       INTEGER NOT NULL,
        station_id INTEGER NOT NULL,
        {", ".join(f"{c} INTEGER" for c in CELL_COLUMNS)},
        PRIMARY KEY (release, lead, station_id)
    ) STRICT, WITHOUT ROWID;
    """,
)

SCHEMA_VERSION = len(MIGRATIONS)


def connect(path: Path) -> sqlite3.Connection:
    """Open the database, creating or migrating its schema as needed."""
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Run every migration the database has not had yet, each in a transaction."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema {version} is newer than this code's {SCHEMA_VERSION}"
        )
    for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
        # executescript commits first and runs outside the module's own
        # transaction handling, so the transaction is spelled out.
        conn.executescript(f"BEGIN; {script}; PRAGMA user_version = {number}; COMMIT;")


def sync_stations(conn: sqlite3.Connection, stations: Iterable[Station]) -> None:
    """Store the stations of stations.csv, updating any that changed."""
    with transaction(conn):
        conn.executemany(
            """
            INSERT INTO stations (station_id, name, lat, lon, altitude, state)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (station_id) DO UPDATE SET
                name = excluded.name, lat = excluded.lat, lon = excluded.lon,
                altitude = excluded.altitude, state = excluded.state
            """,
            [(s.station_id, s.name, s.lat, s.lon, s.altitude, s.state) for s in stations],
        )


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run the ``with`` block in one transaction: committed, or rolled back on error."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def grid_id(conn: sqlite3.Connection, description: str) -> int:
    """Return the id of the grid with this description, storing it if new."""
    conn.execute(
        "INSERT INTO grids (description) VALUES (?) ON CONFLICT DO NOTHING", (description,)
    )
    return conn.execute(
        "SELECT grid_id FROM grids WHERE description = ?", (description,)
    ).fetchone()[0]


def store_station_cells(
    conn: sqlite3.Connection, grid: int, cells: Iterable[StationCell]
) -> None:
    """Store the stations' cells on a grid (those already stored stay as they are)."""
    conn.executemany(
        """
        INSERT INTO station_cells (grid_id, station_id, row, col, frac_x, frac_y)
        VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING
        """,
        [(grid, c.station_id, c.row, c.col, c.frac_x, c.frac_y) for c in cells],
    )


def logged_releases(conn: sqlite3.Connection, since: int) -> set[int]:
    """Return the releases logged from ``since`` (Unix seconds) on."""
    return {r for (r,) in conn.execute("SELECT release FROM releases WHERE release >= ?", (since,))}


_RADAR_INSERT = (
    f"INSERT INTO radar (release, lead, station_id, {', '.join(CELL_COLUMNS)}) "
    f"VALUES ({', '.join('?' * (3 + len(CELL_COLUMNS)))})"
)


def radar_rows(
    release: int, lead: int, station_ids: Sequence[int], windows
) -> list[tuple]:
    """Return the radar rows to store for one member: all but the all-dry windows.

    ``windows`` is cut_windows' array (thousandths of a mm, NaN for no data),
    one row per station in ``station_ids`` order.

    """
    rows = []
    for station_id, window in zip(station_ids, windows.tolist()):
        if all(v == 0 for v in window):
            continue
        cells = [None if math.isnan(v) else int(v) for v in window]
        rows.append((release, lead, station_id, *cells))
    return rows


def store_release(
    conn: sqlite3.Connection,
    release: int,
    grid: int,
    logged_at: int,
    leads_present: int,
    rows: Iterable[tuple],
) -> None:
    """Store one release's radar rows and its releases entry, in one transaction."""
    with transaction(conn):
        conn.executemany(_RADAR_INSERT, rows)
        conn.execute(
            "INSERT INTO releases (release, grid_id, logged_at, leads_present) VALUES (?, ?, ?, ?)",
            (release, grid, logged_at, leads_present),
        )
