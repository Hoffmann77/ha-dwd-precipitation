"""The reference stations: DWD rain gauges the radar windows are logged around."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

FIELDS = ("station_id", "name", "lat", "lon", "altitude", "state")


@dataclass(frozen=True)
class Station:
    """A DWD precipitation station, at its current position."""

    station_id: int
    name: str
    lat: float
    lon: float
    altitude: float
    state: str


def load_stations(path: Path) -> list[Station]:
    """Return the stations listed in ``path`` (stations.csv), in file order."""
    with path.open(encoding="utf-8", newline="") as f:
        return [
            Station(
                station_id=int(row["station_id"]),
                name=row["name"],
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                altitude=float(row["altitude"]),
                state=row["state"],
            )
            for row in csv.DictReader(f)
        ]


def write_stations(path: Path, stations: list[Station]) -> None:
    """Write ``stations`` to ``path`` in the stations.csv format."""
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(FIELDS)
        for s in stations:
            writer.writerow(
                (s.station_id, s.name, f"{s.lat:.4f}", f"{s.lon:.4f}", f"{s.altitude:g}", s.state)
            )
