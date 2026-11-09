"""The radar job: log every RV release still on OpenData that is not logged yet.

DWD keeps RV releases for about 48 hours, so the job is a catch-up, not a
fetch of "the latest": it lists what OpenData has, and logs every release the
database lacks, oldest first (those expire first). A restart or a few hours
of downtime therefore lose nothing.

"""

from __future__ import annotations

import io
import logging
import re
import sqlite3
import tarfile
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from radar.nowcast import LEADS
from radar.odim import read_odim_composite, read_odim_grid
from radar.tar_range import member_names
from radar.urls import COMPOSITE, radvor_prefix, radvor_url

from . import db
from .stations import Station
from .windows import cut_windows, grid_description, station_cells

_LOGGER = logging.getLogger(__name__)

LISTING_URL = f"{COMPOSITE}/rv/"

# A release name in the directory listing (composite_rv_LATEST.tar is not one).
_RELEASE_NAME = re.compile(r'href="composite_rv_(\d{8})_(\d{4})\.tar"')

# How far back the database is checked for gaps: OpenData's retention, with
# a margin. Releases older than this are no longer listed anyway.
LOOKBACK = timedelta(hours=50)

TIMEOUT = (15, 120)  # connect, read (s)
USER_AGENT = "ha-dwd-precipitation precip-eval (+https://github.com/Hoffmann77/ha-dwd-precipitation)"


def parse_listing(html: str) -> list[datetime]:
    """Return the RV releases a directory listing of OpenData shows, sorted."""
    return sorted(
        datetime.strptime(day + hhmm, "%Y%m%d%H%M").replace(tzinfo=UTC)
        for day, hhmm in _RELEASE_NAME.findall(html)
    )


def missing_releases(listed: Sequence[datetime], logged: set[int]) -> list[datetime]:
    """Return the listed releases not logged yet, oldest first."""
    return [ts for ts in sorted(listed) if int(ts.timestamp()) not in logged]


def make_session() -> requests.Session:
    """Return the HTTP session the job downloads with."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def list_releases(session: requests.Session) -> list[datetime]:
    """Return the RV releases currently on OpenData."""
    response = session.get(LISTING_URL, timeout=TIMEOUT)
    response.raise_for_status()
    return parse_listing(response.text)


def download(session: requests.Session, url: str, dest: Path) -> None:
    """Download ``url`` to ``dest``, complete or not at all.

    Written to a ``.part`` file first and renamed once its length matches the
    server's Content-Length, so a broken transfer never looks like a file.

    """
    part = dest.with_name(dest.name + ".part")
    with session.get(url, timeout=TIMEOUT, stream=True) as response:
        response.raise_for_status()
        expected = response.headers.get("Content-Length")
        with part.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1 << 16):
                f.write(chunk)
    size = part.stat().st_size
    if expected is not None and size != int(expected):
        part.unlink()
        raise OSError(f"{url}: got {size} of {expected} bytes")
    part.replace(dest)


def log_release(
    conn: sqlite3.Connection,
    stations: Sequence[Station],
    ts: datetime,
    tar_path: Path,
    now: datetime,
) -> int:
    """Log one downloaded release; return the number of radar rows stored.

    Every member is read whole once and every station's window cut out of it
    on the grid the member describes. A member that is missing or cannot be
    read, or that describes another grid than the first one read, is left out
    of ``leads_present``; the rest of the release is still logged.

    """
    release = int(ts.timestamp())
    names = member_names(radvor_prefix("rv", ts), LEADS)
    rows: list[tuple] = []
    leads_present = 0
    grid = grid_key = cells = None

    with tarfile.open(tar_path) as tar:
        for k, (lead, name) in enumerate(zip(LEADS, names)):
            try:
                member = tar.extractfile(name)
                if member is None:
                    raise KeyError(name)
                payload = member.read()
                member_grid = read_odim_grid(io.BytesIO(payload))
                values, _ = read_odim_composite(io.BytesIO(payload))
            except Exception as err:  # a damaged member must not cost the release
                _LOGGER.warning("RV %s: lead %d not read (%s)", ts, lead, err)
                continue
            if grid is None:
                grid = member_grid
                grid_key = grid_description(grid)
                cells = station_cells(grid, stations)
            elif member_grid != grid:
                _LOGGER.warning("RV %s: lead %d is on another grid, not read", ts, lead)
                continue
            if cells:
                windows = cut_windows(values, cells)
                rows += db.radar_rows(release, lead, [c.station_id for c in cells], windows)
            leads_present |= 1 << k

    if grid is None:
        raise ValueError(f"RV {ts:%Y-%m-%d %H:%M}: no member could be read")

    gid = db.grid_id(conn, grid_key)
    db.store_station_cells(conn, gid, cells)
    db.store_release(conn, release, gid, int(now.timestamp()), leads_present, rows)
    return len(rows)


def run(
    conn: sqlite3.Connection,
    session: requests.Session,
    stations: Sequence[Station],
    tmp_dir: Path,
    stop: threading.Event,
    on_progress=lambda: None,
) -> int:
    """Log every RV release on OpenData that is not logged yet; return how many.

    Stops early, between releases, once ``stop`` is set. A release that fails
    is logged as a warning and left for the next turn.

    """
    try:
        listed = list_releases(session)
    except requests.RequestException as err:
        _LOGGER.warning("RV: OpenData not reachable, retried next turn (%s)", err)
        return 0
    since = int((datetime.now(UTC) - LOOKBACK).timestamp())
    todo = missing_releases(listed, db.logged_releases(conn, since))
    if not todo:
        return 0
    _LOGGER.info("RV: %d release(s) to log, %s .. %s", len(todo), todo[0], todo[-1])

    tmp_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    for ts in todo:
        if stop.is_set():
            break
        tar_path = tmp_dir / f"{radvor_prefix('rv', ts)}.tar"
        started = time.monotonic()
        try:
            download(session, radvor_url("rv", ts), tar_path)
            n_rows = log_release(conn, stations, ts, tar_path, datetime.now(UTC))
        except Exception as err:  # one bad release must not hold up the rest
            _LOGGER.warning("RV %s: not logged, retried next turn (%s)", ts, err)
            continue
        finally:
            tar_path.unlink(missing_ok=True)
        done += 1
        _LOGGER.info(
            "RV %s: logged, %d wet window(s), %.1f s", ts, n_rows, time.monotonic() - started
        )
        on_progress()
    return done
