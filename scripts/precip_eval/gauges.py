"""The gauge job: DWD's 1-minute precipitation, summed to the RV step windows.

Each station's ``now/`` file holds yesterday and today, refreshed hourly; it
is read on every turn, and its windows replace the stored ones while it still
covers them, since DWD revises its newest minutes and raises their quality
level once checked. A day the database lacks for longer (downtime of more
than a day, or the days before the service started) is read from the
station's ``recent/`` file instead, which reaches back years but is ~5 MB, so
at most once a day per station.

Windows are stored as DWD stamps the minutes, whatever the instrument; the
instrument history is stored alongside (``instruments``), because what a
timestamp means depends on it (the 1-minute dataset description: rain[e]H3
stamps the end of the minute, OTT Pluvio lags about 5 minutes). The
evaluation applies that when it pairs windows with radar steps.

"""

from __future__ import annotations

import io
import logging
import sqlite3
import threading
import zipfile
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import requests

from . import db
from .stations import Station

_LOGGER = logging.getLogger(__name__)

CDC_1MIN = (
    "https://opendata.dwd.de/climate_environment/CDC/observations_germany/"
    "climate/1_minute/precipitation"
)

WINDOW = 300  # seconds: the RV step
MINUTE = 60
DAY = timedelta(days=1)

# A station's recent/ file and instrument history are fetched at most this often.
RECENT_EVERY = timedelta(hours=24)
INSTRUMENTS_EVERY = timedelta(hours=24)

TIMEOUT = (15, 120)


def now_url(station_id: int) -> str:
    return f"{CDC_1MIN}/now/1minutenwerte_nieder_{station_id:05d}_now.zip"


def recent_url(station_id: int) -> str:
    return f"{CDC_1MIN}/recent/1minutenwerte_nieder_{station_id:05d}_akt.zip"


def meta_url(station_id: int) -> str:
    return f"{CDC_1MIN}/meta_data/Meta_Daten_ein_min_rr_{station_id:05d}.zip"


@dataclass(frozen=True)
class Minute:
    """One row of a 1-minute file."""

    label: int  # MESS_DATUM as Unix seconds UTC
    qn: int
    amount: int | None  # hundredths of a mm; None for DWD's -999


def product_text(archive: bytes) -> str:
    """Return the data file (``produkt_*.txt``) of a station zip, decoded."""
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        names = [n for n in zf.namelist() if n.startswith("produkt_") and n.endswith(".txt")]
        if len(names) != 1:
            raise ValueError(f"expected one produkt_*.txt, found {names}")
        return zf.read(names[0]).decode("latin-1")


def parse_minutes(text: str, days: set[str] | None = None) -> Iterator[Minute]:
    """Yield the rows of a 1-minute file, optionally only those of ``days``.

    ``days`` are YYYYMMDD prefixes of MESS_DATUM; filtering on them first keeps
    a years-long recent/ file cheap to read. Rows that do not parse are
    skipped.

    """
    for line in text.splitlines()[1:]:
        parts = line.split(";")
        if len(parts) < 4:
            continue
        stamp = parts[1].strip()
        if days is not None and stamp[:8] not in days:
            continue
        try:
            label = datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=UTC)
            qn = int(parts[2])
            value = float(parts[3])
        except ValueError:
            continue
        amount = None if value < 0 else round(value * 100)
        yield Minute(int(label.timestamp()), qn, amount)


def window_end(label: int) -> int:
    """Return the end of the 5-minute window a minute stamped ``label`` is in.

    The window ending at E holds the minutes stamped E-4 min .. E, so a minute
    stamped on a 5-minute mark closes the window ending there.

    """
    return -(-label // WINDOW) * WINDOW


def windows(minutes: Iterable[Minute]) -> list[tuple[int, int, int, int]]:
    """Sum minutes to windows: (window_end, amount, qn, n_minutes), sorted.

    ``amount`` sums the minutes that have a value; ``qn`` is the lowest
    quality level among them (of all its minutes if none has one).

    """
    acc: dict[int, list[int]] = {}
    for m in minutes:
        end = window_end(m.label)
        w = acc.setdefault(end, [0, 99, 99, 0])  # amount, qn valid, qn all, n
        w[2] = min(w[2], m.qn)
        if m.amount is not None:
            w[0] += m.amount
            w[1] = min(w[1], m.qn)
            w[3] += 1
    return [
        (end, amount, qn_valid if n else qn_all, n)
        for end, (amount, qn_valid, qn_all, n) in sorted(acc.items())
    ]


def window_day(end: int) -> str:
    """Return the UTC day (YYYY-MM-DD) a window belongs to.

    A day's windows end after its midnight and at the next one, so the window
    ending at midnight is the last of the day before.

    """
    return datetime.fromtimestamp(end - 1, UTC).date().isoformat()


def covered_days(minutes: Sequence[Minute]) -> set[str]:
    """Return the days whose every window the file could hold.

    Day D needs the minutes stamped D 00:01 .. D+1 00:00. A day is covered when
    the file reaches from its first to its last minute; minutes missing in
    between are DWD's gaps, which the windows' n_minutes show.

    """
    if not minutes:
        return set()
    first = min(m.label for m in minutes)
    last = max(m.label for m in minutes)
    day = datetime.fromtimestamp(first - MINUTE, UTC).date()
    covered = set()
    while True:
        start = int(datetime.combine(day, datetime.min.time(), UTC).timestamp())
        end = start + 86400
        if end > last:
            break
        if start + MINUTE >= first:
            covered.add(day.isoformat())
        day += DAY
    return covered


def parse_instruments(text: str) -> list[tuple[str, str, str]]:
    """Parse ``Metadaten_Geraete_Niederschlagshoehe_*.txt``: (from, to, name)."""
    periods = []
    for line in text.splitlines()[1:]:
        parts = [p.strip() for p in line.split(";")]
        if len(parts) >= 10 and parts[6].isdigit():
            periods.append((parts[6], parts[7], parts[8]))
    return periods


def _get(session: requests.Session, url: str) -> bytes | None:
    """Return a file's bytes, or None when DWD has no such file (404)."""
    response = session.get(url, timeout=TIMEOUT)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content


def _days(first: date, last: date) -> list[str]:
    return [(first + timedelta(days=k)).isoformat() for k in range((last - first).days + 1)]


def _refresh_instruments(conn, session, station: Station, now: datetime) -> None:
    key = f"instruments:{station.station_id}"
    done = db.job_state(conn, key)
    if done is not None and now.timestamp() - done < INSTRUMENTS_EVERY.total_seconds():
        return
    archive = _get(session, meta_url(station.station_id))
    if archive is None:
        return
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        name = f"Metadaten_Geraete_Niederschlagshoehe_{station.station_id:05d}.txt"
        if name not in zf.namelist():
            return
        periods = parse_instruments(zf.read(name).decode("latin-1"))
    db.store_instruments(conn, station.station_id, periods)
    db.set_job_state(conn, key, int(now.timestamp()))


def _store(conn, station, minutes, wanted: set[str], source: str, now: datetime) -> int:
    """Store the windows of ``wanted`` days and mark the covered ones; return the count."""
    rows = [w for w in windows(minutes) if window_day(w[0]) in wanted]
    days = covered_days(minutes) & wanted
    db.store_gauge(conn, station.station_id, rows, days, source, int(now.timestamp()))
    return len(rows)


def update_station(
    conn: sqlite3.Connection,
    session: requests.Session,
    station: Station,
    first_day: date,
    now: datetime,
) -> None:
    """Bring one station's gauge windows up to date (see module doc)."""
    _refresh_instruments(conn, session, station, now)
    today = now.date()
    wanted = set(_days(first_day, today))

    archive = _get(session, now_url(station.station_id))
    if archive is not None:
        minutes = list(parse_minutes(product_text(archive)))
        _store(conn, station, minutes, wanted, "now", now)

    # Complete days older than yesterday that now/ no longer holds.
    missing = set(_days(first_day, today - 2 * DAY)) - db.complete_days(conn, station.station_id)
    if not missing:
        return
    key = f"recent:{station.station_id}"
    done = db.job_state(conn, key)
    if done is not None and now.timestamp() - done < RECENT_EVERY.total_seconds():
        return
    archive = _get(session, recent_url(station.station_id))
    db.set_job_state(conn, key, int(now.timestamp()))
    if archive is None:
        return
    # A day's last window needs the minute stamped at the next midnight.
    stamps = {d.replace("-", "") for d in missing}
    stamps |= {(date.fromisoformat(d) + DAY).strftime("%Y%m%d") for d in missing}
    minutes = list(parse_minutes(product_text(archive), stamps))
    n = _store(conn, station, minutes, missing, "recent", now)
    _LOGGER.info("Gauge %d: %d day(s) from recent/, %d window(s)", station.station_id, len(missing), n)


def run(
    conn: sqlite3.Connection,
    session: requests.Session,
    stations: Sequence[Station],
    stop: threading.Event,
    now: datetime | None = None,
) -> int:
    """Update every station; return how many were updated without error.

    Gauge windows are kept from the day of the first logged release on, so
    nothing is fetched before the radar job has logged one. A station that
    fails is logged as a warning and tried again on the next turn.

    """
    first = db.first_release(conn)
    if first is None:
        return 0
    now = now or datetime.now(UTC)
    first_day = datetime.fromtimestamp(first, UTC).date()
    done = 0
    for station in stations:
        if stop.is_set():
            break
        try:
            update_station(conn, session, station, first_day, now)
        except Exception as err:  # one station must not hold up the rest
            _LOGGER.warning("Gauge %d: not updated, retried next turn (%s)", station.station_id, err)
            continue
        done += 1
    return done
