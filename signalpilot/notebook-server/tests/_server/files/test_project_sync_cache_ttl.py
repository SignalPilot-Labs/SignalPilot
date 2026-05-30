"""F-15: Gate tests for TTL-bounded project-sync clone-info and project-name caches.

Each test demonstrates inject → fail → revert → pass:
  - test_clone_info_cache_expires_after_ttl: reverts _cache_get to plain dict get →
    second token stays t1 → assertion `== 2 httpx calls` fails.
  - test_clone_info_cache_hits_within_ttl: removing TTL invalidation means both calls
    always hit the network → assertion `== 1` fails.
  - test_project_name_cache_expires_after_ttl: reverts _cache_get for project names →
    second name stays "old-name" → assertion fails.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from signalpilot._server.files import project_sync

# Convenience alias so test assertions can reference the module constant by name.
_CACHE_TTL = project_sync._CACHE_TTL_SECONDS


def _make_httpx_response(data: dict[str, Any]) -> MagicMock:
    """Return a mock httpx.Response with status 200 and json() returning data."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data
    return resp


def _fake_httpx_url(*_args: object, **_kwargs: object) -> MagicMock:
    """Placeholder — tests override this via side_effect."""
    return MagicMock()


class TestCloneInfoCacheExpiresAfterTtl:
    """clone_info cache evicts entry after TTL and re-fetches on next call."""

    def test_clone_info_cache_expires_after_ttl(self, monkeypatch):
        """Second call after TTL expiry fetches fresh token from gateway.

        Inject demo: revert _cache_get to `lambda cache, key: cache.get(key, (0, None))[1]`
        (plain dict read without TTL check) → second call returns cached t1 → this assertion
        fails because httpx.get is called only once instead of twice.
        """
        # Reset cache to isolate this test
        monkeypatch.setattr(project_sync, "_clone_url_cache", {})

        call_count = 0
        responses = [
            {"clone_url": "https://x/y.git", "auth_token": "t1"},
            {"clone_url": "https://x/y.git", "auth_token": "t2"},
        ]

        def fake_httpx_get(_url: str, **_kwargs: object) -> MagicMock:
            nonlocal call_count
            resp = _make_httpx_response(responses[call_count])
            call_count += 1
            return resp

        # Simulate time advancing past TTL between the two calls.
        # Call sequence:
        #   1. get_clone_info #1 → _cache_get (cache miss, no monotonic call)
        #                        → _cache_put (monotonic #1 → 0.0)
        #   2. get_clone_info #2 → _cache_get (entry found, monotonic #2 → _CACHE_TTL+1 → evict)
        #                        → _cache_put (monotonic #3 → _CACHE_TTL+1)
        monotonic_times = [
            0.0,               # _cache_put call #1: stores ts=0.0
            _CACHE_TTL + 1.0,  # _cache_get call #2: now - 0.0 > TTL → evict
            _CACHE_TTL + 1.0,  # _cache_put call #2: stores ts=_CACHE_TTL+1
        ]
        time_iter = iter(monotonic_times)

        def fake_monotonic() -> float:
            return next(time_iter)

        with (
            patch("signalpilot._server.files.project_sync.httpx.get", side_effect=fake_httpx_get),
            patch("signalpilot._server.files.project_sync.time.monotonic", side_effect=fake_monotonic),
            patch("signalpilot._server.files.project_sync._gateway_url_raw", return_value="http://gw"),
            patch("signalpilot._server.files.project_sync._gateway_headers", return_value={}),
        ):
            result1 = project_sync.get_clone_info("proj-a")
            result2 = project_sync.get_clone_info("proj-a")

        assert result1["auth_token"] == "t1"
        assert result2["auth_token"] == "t2", (
            "After TTL expiry the cache must be evicted so the second call fetches a fresh token. "
            "Inject demo: revert _cache_get to plain dict access → result2 stays 't1' → this fails."
        )
        assert call_count == 2, (
            f"Expected 2 httpx.get calls (one per TTL window), got {call_count}. "
            "Inject demo: remove TTL eviction → only 1 call is made → assertion fails."
        )

    def test_clone_info_cache_hits_within_ttl(self, monkeypatch):
        """Two calls within the TTL window hit the gateway only once.

        Inject demo: lower _CACHE_TTL_SECONDS to 0 in project_sync → every call misses →
        httpx.get is called twice → assertion `== 1` fails.
        """
        monkeypatch.setattr(project_sync, "_clone_url_cache", {})

        call_count = 0

        def fake_httpx_get(_url: str, **_kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return _make_httpx_response({"clone_url": "https://x/y.git", "auth_token": "t1"})

        # Both monotonic() calls return the same time → well within TTL
        with (
            patch("signalpilot._server.files.project_sync.httpx.get", side_effect=fake_httpx_get),
            patch("signalpilot._server.files.project_sync.time.monotonic", return_value=0.0),
            patch("signalpilot._server.files.project_sync._gateway_url_raw", return_value="http://gw"),
            patch("signalpilot._server.files.project_sync._gateway_headers", return_value={}),
        ):
            result1 = project_sync.get_clone_info("proj-b")
            result2 = project_sync.get_clone_info("proj-b")

        assert result1["auth_token"] == "t1"
        assert result2["auth_token"] == "t1"
        assert call_count == 1, (
            f"Expected 1 httpx.get call (cache hit within TTL), got {call_count}. "
            "Inject demo: set _CACHE_TTL_SECONDS=0 → every call misses → 2 calls → fails."
        )


class TestProjectNameCacheExpiresAfterTtl:
    """project_name cache evicts entry after TTL and re-fetches on next call."""

    def test_project_name_cache_expires_after_ttl(self, monkeypatch):
        """Second call after TTL expiry fetches updated project name from gateway.

        Inject demo: revert _cache_get to plain dict access → second call returns
        cached 'old-name' → assertion fails.
        """
        monkeypatch.setattr(project_sync, "_project_name_cache", {})

        call_count = 0
        names = ["old-name", "new-name"]

        def fake_httpx_get(_url: str, **_kwargs: object) -> MagicMock:
            nonlocal call_count
            resp = _make_httpx_response({"name": names[call_count]})
            call_count += 1
            return resp

        # Same call sequence as clone_info test:
        #   1. _get_project_name #1 → _cache_get (miss, no monotonic)
        #                           → _cache_put (monotonic #1 → 0.0)
        #   2. _get_project_name #2 → _cache_get (found, monotonic #2 → _CACHE_TTL+1 → evict)
        #                           → _cache_put (monotonic #3 → _CACHE_TTL+1)
        monotonic_times = [
            0.0,               # _cache_put call #1: stores ts=0.0
            _CACHE_TTL + 1.0,  # _cache_get call #2: now - 0.0 > TTL → evict
            _CACHE_TTL + 1.0,  # _cache_put call #2: stores ts=_CACHE_TTL+1
        ]
        time_iter = iter(monotonic_times)

        def fake_monotonic() -> float:
            return next(time_iter)

        with (
            patch("signalpilot._server.files.project_sync.httpx.get", side_effect=fake_httpx_get),
            patch("signalpilot._server.files.project_sync.time.monotonic", side_effect=fake_monotonic),
            patch("signalpilot._server.files.project_sync._gateway_url", return_value="http://gw"),
            patch("signalpilot._server.files.project_sync._gateway_headers", return_value={}),
        ):
            name1 = project_sync._get_project_name("proj-c")
            name2 = project_sync._get_project_name("proj-c")

        assert name1 == "old-name"
        assert name2 == "new-name", (
            "After TTL expiry the cache must be evicted so the second call fetches a fresh name. "
            "Inject demo: revert _cache_get to plain dict access → name2 stays 'old-name' → this fails."
        )
        assert call_count == 2, (
            f"Expected 2 httpx.get calls (one per TTL window), got {call_count}. "
            "Inject demo: remove TTL eviction → only 1 call is made → assertion fails."
        )
