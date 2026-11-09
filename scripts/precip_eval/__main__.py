"""The container's entry point: ``python -m scripts.precip_eval``.

Opens (or creates) the database, loads the station list and runs the jobs
until the container is stopped. There are no options: settings come from the
environment (config.py).

"""

from __future__ import annotations

import logging
import shutil
import signal
import threading
from datetime import timedelta

from . import db, gauges, radar_job
from .config import Config
from .scheduler import Job, run_forever, touch
from .stations import load_stations

_LOGGER = logging.getLogger("precip_eval")


def main() -> None:
    """Run the service until SIGTERM or SIGINT."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = Config.from_env()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    # Left over from a run that was stopped mid-download.
    shutil.rmtree(config.tmp_dir, ignore_errors=True)

    stations = load_stations(config.stations_csv)
    conn = db.connect(config.database)
    db.sync_stations(conn, stations)
    _LOGGER.info(
        "Started: %d stations, database %s (schema %d), code %s",
        len(stations), config.database, db.SCHEMA_VERSION, config.code_commit,
    )

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    session = radar_job.make_session()
    jobs = [
        Job(
            "radar",
            lambda: radar_job.run(
                conn, session, stations, config.tmp_dir, stop,
                on_progress=lambda: touch(config.heartbeat),
            ),
            # RV is on OpenData ~4 min after its nominal time: half a minute
            # past each 5-minute mark finds the release of the mark before.
            interval=timedelta(minutes=5),
            offset=timedelta(seconds=30),
        ),
        Job(
            "gauges",
            lambda: gauges.run(conn, session, stations, stop),
            # now/ is refreshed hourly and holds yesterday and today, so every
            # 3 hours keeps each day's final revision with a day to spare.
            interval=timedelta(hours=3),
            offset=timedelta(minutes=20),
        ),
    ]
    run_forever(jobs, stop, config.heartbeat)
    conn.close()
    _LOGGER.info("Stopped")


if __name__ == "__main__":
    main()
