"""The gauge job: DWD 1-minute files summed to the RV step windows."""

from __future__ import annotations

import io
import threading
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from scripts.precip_eval import db, gauges
from scripts.precip_eval.stations import Station

HEADER = "STATIONS_ID;MESS_DATUM;QN;RS_01;RS_IND_01;eor"
STATION = Station(20, "Abtsgmuend", 48.9219, 9.9129, 432.0, "Baden-Wuerttemberg")


def ts(text: str) -> int:
    return int(datetime.strptime(text, "%Y%m%d%H%M").replace(tzinfo=UTC).timestamp())


def row(stamp: str, mm: str = "0.00", qn: int = 3) -> str:
    # DWD's padding, as in the real files.
    return f"        20;{stamp};    {qn};{mm:>7};-999;eor"


def text(rows: list[str]) -> str:
    return "\r\n".join([HEADER, *rows]) + "\r\n"


def minutes(start: str, end: str, mm: str = "0.00", qn: int = 3) -> list[str]:
    """Rows for every minute stamped start..end (inclusive)."""
    t, stop, out = datetime.strptime(start, "%Y%m%d%H%M"), datetime.strptime(end, "%Y%m%d%H%M"), []
    while t <= stop:
        out.append(row(t.strftime("%Y%m%d%H%M"), mm, qn))
        t += timedelta(minutes=1)
    return out


def test_a_minute_on_the_mark_closes_its_window():
    assert gauges.window_end(ts("202611091205")) == ts("202611091205")
    assert gauges.window_end(ts("202611091201")) == ts("202611091205")
    assert gauges.window_end(ts("202611091206")) == ts("202611091210")


def test_windows_sum_values_and_keep_the_lowest_quality():
    rows = [
        row("202611091201", "0.10"),
        row("202611091202", "0.05", qn=2),
        row("202611091203", "-999   "),
        row("202611091204", "0.00"),
        row("202611091205", "0.20"),
        row("202611091206", "-999   ", qn=1),
    ]

    result = gauges.windows(gauges.parse_minutes(text(rows)))

    assert result == [
        (ts("202611091205"), 35, 2, 4),  # 0.10 + 0.05 + 0.20 mm, one missing
        (ts("202611091210"), 0, 1, 0),  # no value at all
    ]


def test_the_window_ending_at_midnight_belongs_to_the_day_before():
    assert gauges.window_day(ts("202611100000")) == "2026-11-09"
    assert gauges.window_day(ts("202611100005")) == "2026-11-10"


def test_a_day_is_covered_from_its_first_minute_to_the_next_midnight():
    # now/ as DWD serves it late on the 10th: from the 9th 00:00 to 22:56.
    file = list(gauges.parse_minutes(text(minutes("202611090000", "202611102256"))))

    assert gauges.covered_days(file) == {"2026-11-09"}


def test_a_file_starting_after_midnight_does_not_cover_that_day():
    file = list(gauges.parse_minutes(text(minutes("202611090002", "202611100000"))))

    assert gauges.covered_days(file) == set()


def test_parse_filters_by_day_prefix():
    rows = [row("202611081200"), row("202611091200")]

    assert [m.label for m in gauges.parse_minutes(text(rows), {"20261109"})] == [ts("202611091200")]


def test_instrument_history_is_parsed():
    meta = (
        "Stations_ID;Stationsname;Geo. Laenge [Grad];Geo. Breite [Grad];Stationshoehe [m];"
        "Geberhoehe ueber Grund [m];Von_Datum;Bis_Datum;Geraetetyp Name;Messverfahren;eor;\n"
        "20;A;9.91;48.92;432;1;20040813;20190721;PLUVIO;Niederschlagsmenge, elektr.;eor;\n"
        "20;A;9.91;48.92;432;1;20190722;20261108;rain[e]H3, Wägetechnologie;Niederschlagsmenge, elektr.;eor;\n"
        "generiert: 09.11.2026 --  Deutscher Wetterdienst  --\n"
    )

    assert gauges.parse_instruments(meta) == [
        ("20040813", "20190721", "PLUVIO"),
        ("20190722", "20261108", "rain[e]H3, Wägetechnologie"),
    ]


# --- the job, against files served from memory -------------------------------


def zipped(name: str, content: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, content.encode("latin-1"))
    return buf.getvalue()


class Response:
    def __init__(self, content: bytes | None):
        self.content = content or b""
        self.status_code = 404 if content is None else 200

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class Session:
    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.requested: list[str] = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        return Response(self.files.get(url))


META = zipped(
    "Metadaten_Geraete_Niederschlagshoehe_00020.txt",
    "header\n20;A;9.91;48.92;432;1;20190722;20261108;rain[e]H3, Wägetechnologie;x;eor;\n",
)
NOW = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.sqlite")
    db.sync_stations(connection, [STATION])
    gid = db.grid_id(connection, "grid")
    yield connection, gid
    connection.close()


def _log_release(conn, gid, when: str):
    db.store_release(conn, ts(when), gid, ts(when), 1, [])


def test_nothing_is_fetched_before_the_first_release(conn):
    connection, _ = conn
    session = Session({})

    assert gauges.run(connection, session, [STATION], threading.Event(), NOW) == 0
    assert session.requested == []


def test_now_file_fills_yesterday_and_today(conn):
    connection, gid = conn
    _log_release(connection, gid, "202611091200")
    now_file = zipped(
        "produkt_ein_now_rr_20261109_20261111_00020.txt",
        text(minutes("202611090000", "202611102256", "0.01")),
    )
    session = Session({gauges.now_url(20): now_file, gauges.meta_url(20): META})

    assert gauges.run(connection, session, [STATION], threading.Event(), NOW) == 1

    assert db.complete_days(connection, 20) == {"2026-11-09"}
    n_windows, total = connection.execute(
        "SELECT count(*), sum(amount) FROM gauge WHERE window_end <= ?", (ts("202611100000"),)
    ).fetchone()
    assert (n_windows, total) == (288, 288 * 5)  # a whole day of 0.05 mm windows
    assert connection.execute("SELECT name FROM instruments").fetchall() == [
        ("rain[e]H3, Wägetechnologie",)
    ]
    # Nothing older is missing, so recent/ is not touched.
    assert gauges.recent_url(20) not in session.requested


def test_older_days_come_from_recent_once_a_day(conn):
    connection, gid = conn
    _log_release(connection, gid, "202611071200")
    recent_file = zipped(
        "produkt_ein_min_rr_20230101_20261109_00020.txt",
        text(minutes("202611060000", "202611092359", "0.02")),
    )
    files = {gauges.recent_url(20): recent_file, gauges.meta_url(20): META}
    session = Session(files)

    gauges.run(connection, session, [STATION], threading.Event(), NOW)

    # now/ is missing (404); recent/ covers the 7th and 8th (the 9th lacks
    # the minute stamped at the next midnight).
    assert db.complete_days(connection, 20) == {"2026-11-07", "2026-11-08"}
    assert connection.execute(
        "SELECT min(window_end) FROM gauge"
    ).fetchone()[0] == ts("202611070005")

    session.requested.clear()
    gauges.run(connection, session, [STATION], threading.Event(), NOW + timedelta(hours=3))
    assert gauges.recent_url(20) not in session.requested  # not again within a day


def test_a_revised_window_replaces_the_stored_one(conn):
    connection, gid = conn
    _log_release(connection, gid, "202611101200")
    first = zipped("produkt_ein_now_rr_x_00020.txt", text([row("202611101205", "0.10", qn=2)]))
    later = zipped("produkt_ein_now_rr_x_00020.txt", text([row("202611101205", "0.30", qn=3)]))

    gauges.run(connection, Session({gauges.now_url(20): first}), [STATION], threading.Event(), NOW)
    gauges.run(connection, Session({gauges.now_url(20): later}), [STATION], threading.Event(), NOW)

    assert connection.execute("SELECT amount, qn FROM gauge").fetchall() == [(30, 3)]
