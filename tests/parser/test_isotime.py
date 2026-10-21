"""Unit tests for radar/isotime.py — no HA."""

from datetime import UTC, datetime

import pytest

from radar.isotime import iso, parse_utc


def test_iso_round_trips_through_parse_utc():
    ts = datetime(2026, 10, 13, 11, 50, tzinfo=UTC)
    assert parse_utc(iso(ts)) == ts
    assert iso(None) is None


def test_parse_utc_reads_naive_as_utc():
    assert parse_utc("2026-10-13T11:50:00") == datetime(2026, 10, 13, 11, 50, tzinfo=UTC)


@pytest.mark.parametrize("raw", [None, "", "not a time", 17, ["2026-10-13"]])
def test_parse_utc_rejects_what_is_not_a_timestamp(raw):
    assert parse_utc(raw) is None
