"""Development tool: choose the reference stations and write stations.csv.

Not part of the service, which only reads the committed stations.csv. Run it
again only to change the station list on purpose (it changes what is logged):

    uv run --only-group precip-eval python -m scripts.precip_eval.select_stations

with ``custom_components/dwd_precipitation`` on PYTHONPATH.

A station qualifies when DWD's 1-minute precipitation series has it reporting
now, freely available, since before 2025, at the position it has had since
before 2025, and with its whole 5x5 window inside the RV radar coverage (taken
from the RV fixture's analysis). Qualifying stations are spread over boxes of
1 x 1.5 degrees and, within a box, over altitude bands: every round takes one
station from each box, rotating through the box's bands, until there are
COUNT. The order inside a box and band comes from a hash of the station id
and SEED, so the result is reproducible and does not favour any id range.

"""

from __future__ import annotations

import hashlib
import io
import logging
import math
import zipfile
from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np

from radar.odim import read_odim_composite, read_odim_grid

from .config import STATIONS_CSV
from .radar_job import make_session
from .stations import Station, write_stations
from .windows import RADIUS, station_cell

_LOGGER = logging.getLogger(__name__)

CDC_1MIN = (
    "https://opendata.dwd.de/climate_environment/CDC/observations_germany/"
    "climate/1_minute/precipitation"
)
STATION_LIST = f"{CDC_1MIN}/recent/ein_min_rr_Beschreibung_Stationen.txt"

COUNT = 150
SEED = "precip-eval-2026"
SINCE = date(2025, 1, 1)  # reporting, and at its current position, since then
BOX_LAT, BOX_LON = 1.0, 1.5  # degrees
ALTITUDE_BANDS = (200.0, 500.0, 1000.0)  # band edges (m): <200, ..., >=1000

# A real RV analysis member; its no-data cells are outside the radar coverage.
COVERAGE_FIXTURE = Path(__file__).parents[2] / "tests/fixtures/composite_rv_sample.hd5"

# Positions in the metadata and the station list agree to their 4 decimals.
SAME_POSITION = 0.00051  # degrees


@dataclass(frozen=True)
class Candidate:
    """A station from DWD's list, with the dates its series covers."""

    station: Station
    first: date
    last: date
    free: bool


def _date(text: str) -> date:
    return datetime.strptime(text, "%Y%m%d").date()


def parse_station_list(text: str) -> list[Candidate]:
    """Parse DWD's fixed-width station description (``*_Beschreibung_Stationen``).

    Columns: id, first and last date, altitude, latitude, longitude, then the
    name (which may contain spaces), the state and whether the data is free.

    """
    candidates = []
    for line in text.splitlines()[2:]:
        parts = line.split()
        if len(parts) < 9:
            continue
        sid, first, last, altitude, lat, lon = parts[:6]
        name, state, release = " ".join(parts[6:-2]), parts[-2], parts[-1]
        station = Station(int(sid), name, float(lat), float(lon), float(altitude), state)
        candidates.append(Candidate(station, _date(first), _date(last), release == "Frei"))
    return candidates


def current_position_since(geography: str) -> tuple[float, float, date] | None:
    """Return the latest (lat, lon, from) of a ``Metadaten_Geographie`` file."""
    rows = [line.split(";") for line in geography.splitlines()[1:] if line.count(";") >= 6]
    if not rows:
        return None
    last = rows[-1]
    return float(last[2]), float(last[3]), _date(last[4].strip())


def _rank(key: object) -> str:
    return hashlib.sha256(f"{SEED}:{key}".encode()).hexdigest()


def _band(altitude: float) -> int:
    return sum(altitude >= edge for edge in ALTITUDE_BANDS)


def _box(station: Station) -> tuple[int, int]:
    return math.floor(station.lat / BOX_LAT), math.floor(station.lon / BOX_LON)


def in_coverage(station: Station, grid, values: np.ndarray) -> bool:
    """Return whether the station's whole window has radar data in ``values``."""
    cell = station_cell(grid, station)
    if cell is None:
        return False
    window = values[
        cell.row - RADIUS : cell.row + RADIUS + 1, cell.col - RADIUS : cell.col + RADIUS + 1
    ]
    return not np.isnan(window).any()


def select(candidates: list[Candidate], qualifies, count: int = COUNT) -> list[Station]:
    """Spread ``count`` stations over boxes and altitude bands (see module doc).

    ``qualifies(station)`` is asked only for stations about to be taken, since
    it downloads the station's metadata.

    """
    boxes: dict[tuple[int, int], list[deque[Station]]] = {}
    for c in sorted(candidates, key=lambda c: _rank(c.station.station_id)):
        bands = boxes.setdefault(_box(c.station), [deque() for _ in range(len(ALTITUDE_BANDS) + 1)])
        bands[_band(c.station.altitude)].append(c.station)

    chosen: list[Station] = []
    turn = {box: 0 for box in boxes}
    while len(chosen) < count and any(any(b) for b in boxes.values()):
        # In hashed order, so the last, partial round favours no region.
        for box in sorted(boxes, key=_rank):
            if len(chosen) >= count:
                break
            bands = boxes[box]
            for _ in range(len(bands)):
                band = bands[turn[box] % len(bands)]
                turn[box] += 1
                taken = None
                while band and taken is None:
                    station = band.popleft()
                    if qualifies(station):
                        taken = station
                if taken is not None:
                    chosen.append(taken)
                    break
    return chosen


def main() -> None:
    """Choose the stations and write stations.csv."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    session = make_session()

    response = session.get(STATION_LIST, timeout=60)
    response.raise_for_status()
    candidates = parse_station_list(response.content.decode("latin-1"))
    reporting_since = date.today() - timedelta(days=7)

    grid = read_odim_grid(COVERAGE_FIXTURE)
    values, _ = read_odim_composite(COVERAGE_FIXTURE)
    eligible = [
        c for c in candidates
        if c.free and c.first <= SINCE and c.last >= reporting_since
        and in_coverage(c.station, grid, values)
    ]
    _LOGGER.info("%d of %d stations eligible before the position check", len(eligible), len(candidates))

    def qualifies(station: Station) -> bool:
        url = f"{CDC_1MIN}/meta_data/Meta_Daten_ein_min_rr_{station.station_id:05d}.zip"
        meta = session.get(url, timeout=60)
        if meta.status_code != 200:
            return False
        with zipfile.ZipFile(io.BytesIO(meta.content)) as zf:
            name = f"Metadaten_Geographie_{station.station_id:05d}.txt"
            if name not in zf.namelist():
                return False
            position = current_position_since(zf.read(name).decode("latin-1"))
        if position is None:
            return False
        lat, lon, since = position
        return (
            since <= SINCE
            and abs(lat - station.lat) < SAME_POSITION
            and abs(lon - station.lon) < SAME_POSITION
        )

    chosen = select(eligible, qualifies)
    chosen.sort(key=lambda s: s.station_id)
    write_stations(STATIONS_CSV, chosen)
    _LOGGER.info(
        "Wrote %d stations to %s (%s)", len(chosen), STATIONS_CSV, datetime.now(UTC).date()
    )


if __name__ == "__main__":
    main()
