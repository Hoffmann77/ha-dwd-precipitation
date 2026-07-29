"""Unit tests for utils.py timing math and fetch hardening — no HA, no network."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from utils import (
    AsyncResponse,
    DEFAULT_MAX_BYTES,
    async_get,
    get_previous_multiple,
    mydatetime,
)

UTC = timezone.utc

_VALID_URL = "https://opendata.dwd.de/weather/radar/composite/rs/composite_rs.tar"


# ===========================================================================
# get_previous_multiple
# ===========================================================================

def test_hourly_with_offset():
    """RADOLAN-style grid at HH:50 — previous release before 12:32 is 11:50."""
    ts = datetime(2025, 6, 1, 12, 32, tzinfo=UTC)
    result = get_previous_multiple(ts, timedelta(hours=1), timedelta(minutes=50))
    assert result == datetime(2025, 6, 1, 11, 50, tzinfo=UTC)


def test_on_boundary_included():
    """A timestamp exactly on a release boundary returns itself when include=True."""
    ts = datetime(2025, 6, 1, 11, 50, tzinfo=UTC)
    result = get_previous_multiple(ts, timedelta(hours=1), timedelta(minutes=50))
    assert result == ts


def test_on_boundary_excluded():
    """include=False steps back one interval when exactly on a boundary."""
    ts = datetime(2025, 6, 1, 11, 50, tzinfo=UTC)
    result = get_previous_multiple(
        ts, timedelta(hours=1), timedelta(minutes=50), include=False
    )
    assert result == datetime(2025, 6, 1, 10, 50, tzinfo=UTC)


def test_five_minute_zero_offset():
    """RS-style 5-minute grid — 12:37:30 floors to 12:35."""
    ts = datetime(2025, 6, 1, 12, 37, 30, tzinfo=UTC)
    result = get_previous_multiple(ts, timedelta(minutes=5), timedelta())
    assert result == datetime(2025, 6, 1, 12, 35, tzinfo=UTC)


# ===========================================================================
# mydatetime operators
# ===========================================================================

def test_divmod_invariant():
    """divmod(dt, delta) → (quotient, remainder) with quotient + remainder == dt."""
    dt = mydatetime(2025, 6, 1, 12, 32, tzinfo=UTC)
    delta = timedelta(hours=1)
    quotient, remainder = divmod(dt, delta)
    assert timedelta() <= remainder < delta
    assert quotient + remainder == dt


def test_floordiv_and_mod_match_divmod():
    dt = mydatetime(2025, 6, 1, 12, 32, tzinfo=UTC)
    delta = timedelta(minutes=15)
    quotient, remainder = divmod(dt, delta)
    assert dt // delta == quotient
    assert dt % delta == remainder


# ===========================================================================
# async_get — transport hardening
# ===========================================================================

class _FakeContent:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def iter_chunked(self, _n):
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    def __init__(self, *, status=200, content_length=None, chunks=(b"payload",)):
        self.status = status
        self.content_length = content_length
        self.content = _FakeContent(chunks)

    def raise_for_status(self):
        # aiohttp only raises for >= 400; our tests exercise the < 400 paths.
        assert self.status < 400

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Records get() kwargs and returns a canned response (or raises if unused)."""

    def __init__(self, response=None):
        self._response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self._response is None:
            raise AssertionError("session.get must not be called for a rejected URL")
        return self._response


def test_rejects_non_https():
    session = _FakeSession()  # must not be touched
    with pytest.raises(ValueError, match="non-HTTPS"):
        asyncio.run(async_get("http://opendata.dwd.de/x.tar", session))
    assert session.calls == []


def test_rejects_untrusted_host():
    session = _FakeSession()
    with pytest.raises(ValueError, match="untrusted host"):
        asyncio.run(async_get("https://evil.example/x.tar", session))
    assert session.calls == []


def test_disables_cross_host_redirects():
    session = _FakeSession(_FakeResponse(chunks=(b"ok",)))
    result = asyncio.run(async_get(_VALID_URL, session))
    assert result == AsyncResponse(content=b"ok")
    # The one call must have opted out of redirect following.
    assert session.calls[0][1].get("allow_redirects") is False


def test_redirect_status_rejected():
    session = _FakeSession(_FakeResponse(status=302))
    with pytest.raises(ValueError, match="redirect"):
        asyncio.run(async_get(_VALID_URL, session))


def test_rejects_declared_oversize_body():
    session = _FakeSession(_FakeResponse(content_length=DEFAULT_MAX_BYTES + 1))
    with pytest.raises(ValueError, match="too large"):
        asyncio.run(async_get(_VALID_URL, session))


def test_rejects_streamed_oversize_body():
    # No Content-Length, but the streamed bytes exceed a small cap.
    session = _FakeSession(_FakeResponse(chunks=(b"a" * 40, b"b" * 40)))
    with pytest.raises(ValueError, match="exceeded"):
        asyncio.run(async_get(_VALID_URL, session, max_bytes=50))


def test_returns_joined_body_within_cap():
    session = _FakeSession(_FakeResponse(chunks=(b"ab", b"cd", b"ef")))
    result = asyncio.run(async_get(_VALID_URL, session, max_bytes=1000))
    assert result.content == b"abcdef"
