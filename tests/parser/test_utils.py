"""Unit tests for utils.py: fetch hardening and timestamps — no HA, no network."""

import asyncio
from datetime import timezone

import pytest

from utils import (
    AsyncResponse,
    DEFAULT_MAX_BYTES,
    DownloadCache,
    FailureLatch,
    async_get,
)

UTC = timezone.utc

_VALID_URL = "https://opendata.dwd.de/weather/radar/composite/rs/composite_rs.tar"


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
    def __init__(
        self, *, status=200, content_length=None, chunks=(b"payload",), headers=None
    ):
        self.status = status
        self.content_length = content_length
        self.content = _FakeContent(chunks)
        self.headers = headers or {}

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


def test_times_out_a_stall_not_a_slow_download():
    session = _FakeSession(_FakeResponse(chunks=(b"ok",)))
    asyncio.run(async_get(_VALID_URL, session))
    timeout = session.calls[0][1]["timeout"]
    assert timeout.total is None  # a big archive on a slow line may finish
    assert timeout.sock_read is not None and timeout.sock_connect is not None


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


def test_sends_headers_and_returns_status_and_headers():
    """A range request passes its headers through and sees the 206 answer."""
    response = _FakeResponse(
        status=206, chunks=(b"abc",), headers={"Content-Range": "bytes 0-2/10"}
    )
    session = _FakeSession(response)
    result = asyncio.run(
        async_get(_VALID_URL, session, headers={"Range": "bytes=0-2"})
    )
    assert session.calls[0][1]["headers"] == {"Range": "bytes=0-2"}
    assert result.status == 206
    assert result.headers["Content-Range"] == "bytes 0-2/10"
    assert result.content == b"abc"


def test_partial_cap_applies_to_206_only():
    """partial_max_bytes bounds a range answer, not a whole-file 200."""
    big = (b"x" * 100,)
    with pytest.raises(ValueError, match="cap"):
        asyncio.run(
            async_get(
                _VALID_URL,
                _FakeSession(_FakeResponse(status=206, chunks=big)),
                partial_max_bytes=50,
            )
        )
    result = asyncio.run(
        async_get(
            _VALID_URL,
            _FakeSession(_FakeResponse(status=200, chunks=big)),
            partial_max_bytes=50,
        )
    )
    assert len(result.content) == 100


# ===========================================================================
# FailureLatch
# ===========================================================================

def test_failure_latch_reports_a_run_once_and_its_end_once():
    latch = FailureLatch()
    assert latch.ok() is False  # nothing to recover from
    assert [latch.fail() for _ in range(3)] == [True, False, False]
    assert latch.failing
    assert [latch.ok() for _ in range(2)] == [True, False]
    assert latch.fail() is True  # a new run


# ===========================================================================
# DownloadCache
# ===========================================================================

def _counting_fetch(calls, content=b"x", delay=0.0, error=None):
    async def fetch():
        calls.append(1)
        await asyncio.sleep(delay)
        if error is not None:
            raise error
        return AsyncResponse(content=content)
    return fetch


def test_download_cache_downloads_a_url_once_for_concurrent_asks():
    async def run():
        cache, calls = DownloadCache(ttl=300), []
        a, b = await asyncio.gather(
            cache.async_get("u", _counting_fetch(calls, delay=0.01)),
            cache.async_get("u", _counting_fetch(calls, delay=0.01)),
        )
        return a, b, calls
    a, b, calls = asyncio.run(run())
    assert calls == [1]
    assert a is b


def test_download_cache_keeps_a_download_for_its_ttl():
    clock = [0.0]

    async def run():
        cache, calls = DownloadCache(ttl=300, clock=lambda: clock[0]), []
        await cache.async_get("u", _counting_fetch(calls))
        clock[0] = 299
        await cache.async_get("u", _counting_fetch(calls))
        assert calls == [1]  # still kept
        clock[0] = 301
        await cache.async_get("u", _counting_fetch(calls))
        assert calls == [1, 1]  # expired: downloaded again
        await cache.async_get("other", _counting_fetch(calls))
        assert calls == [1, 1, 1]
    asyncio.run(run())


def test_download_cache_does_not_keep_a_failure():
    async def run():
        cache, calls = DownloadCache(ttl=300), []
        results = await asyncio.gather(
            cache.async_get("u", _counting_fetch(calls, delay=0.01, error=OSError("404"))),
            cache.async_get("u", _counting_fetch(calls)),
            return_exceptions=True,
        )
        assert [type(r) for r in results] == [OSError, OSError]  # both waited for it
        assert (await cache.async_get("u", _counting_fetch(calls))).content == b"x"
        return calls
    assert asyncio.run(run()) == [1, 1]


def test_download_cache_survives_a_cancelled_waiter():
    async def run():
        cache, calls = DownloadCache(ttl=300), []
        first = asyncio.ensure_future(cache.async_get("u", _counting_fetch(calls, delay=0.02)))
        await asyncio.sleep(0)
        second = asyncio.ensure_future(cache.async_get("u", _counting_fetch(calls)))
        await asyncio.sleep(0)
        first.cancel()
        response = await second
        return response, calls
    response, calls = asyncio.run(run())
    assert response.content == b"x"
    assert calls == [1]
