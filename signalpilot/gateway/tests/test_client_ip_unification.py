"""Tests for F-L6: unified client-IP derivation via gateway.common.ip.

Verifies that:
- ``client_ip`` returns the rightmost XFF entry (spoof-rejection).
- Whitespace is stripped; empty/blank entries are skipped.
- ``x-real-ip`` is never consulted (parity with RateLimitMiddleware).
- ``request_meta`` returns ``(client_ip, user_agent)`` verbatim.
- ``RateLimitMiddleware._client_ip`` is exactly ``client_ip(req) or "unknown"``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from gateway.common.ip import client_ip, request_meta
from gateway.http.middleware.rate_limit import RateLimitMiddleware

# ─── Mock helpers ─────────────────────────────────────────────────────────────


def _make_request(
    headers: dict[str, str] | None = None,
    client_host: str | None = "10.0.0.1",
) -> MagicMock:
    """Build a minimal mock Request matching FastAPI's interface."""
    req = MagicMock()
    req.headers = headers or {}
    if client_host is None:
        req.client = None
    else:
        req.client = MagicMock()
        req.client.host = client_host
    return req


# ─── Unit tests for client_ip / request_meta ──────────────────────────────────


class TestClientIp:
    def test_leftmost_xff_is_not_returned(self) -> None:
        req = _make_request(
            headers={"x-forwarded-for": "1.1.1.1, 2.2.2.2"},
            client_host="10.0.0.1",
        )
        result = client_ip(req)
        assert result == "2.2.2.2", "Rightmost XFF must be returned, not leftmost"
        assert result != "1.1.1.1"

    def test_single_xff_value(self) -> None:
        req = _make_request(headers={"x-forwarded-for": "1.1.1.1"})
        assert client_ip(req) == "1.1.1.1"

    def test_xff_whitespace_trimmed(self) -> None:
        req = _make_request(headers={"x-forwarded-for": "1.1.1.1 , 2.2.2.2 "})
        assert client_ip(req) == "2.2.2.2"

    def test_xff_empty_header_falls_through(self) -> None:
        req = _make_request(
            headers={"x-forwarded-for": ""},
            client_host="10.0.0.1",
        )
        assert client_ip(req) == "10.0.0.1"

    def test_xff_only_empty_entries_falls_through(self) -> None:
        req = _make_request(
            headers={"x-forwarded-for": ", , "},
            client_host="10.0.0.1",
        )
        assert client_ip(req) == "10.0.0.1"

    def test_xff_with_leading_empty_entries(self) -> None:
        req = _make_request(headers={"x-forwarded-for": ", , 2.2.2.2"})
        assert client_ip(req) == "2.2.2.2"

    def test_xff_ipv6(self) -> None:
        req = _make_request(
            headers={"x-forwarded-for": "2001:db8::1, 2001:db8::2"}
        )
        assert client_ip(req) == "2001:db8::2"

    def test_x_real_ip_ignored_when_no_xff(self) -> None:
        """Helper must NOT fall back to x-real-ip — parity guard."""
        req = _make_request(
            headers={"x-real-ip": "3.3.3.3"},
            client_host="10.0.0.1",
        )
        # Must return client.host, not x-real-ip
        assert client_ip(req) == "10.0.0.1"

    def test_x_real_ip_ignored_when_xff_present(self) -> None:
        req = _make_request(
            headers={
                "x-forwarded-for": "1.1.1.1, 2.2.2.2",
                "x-real-ip": "9.9.9.9",
            },
            client_host="10.0.0.1",
        )
        # XFF rightmost wins; x-real-ip is ignored entirely
        assert client_ip(req) == "2.2.2.2"

    def test_remote_addr_fallback(self) -> None:
        req = _make_request(headers={}, client_host="10.0.0.1")
        assert client_ip(req) == "10.0.0.1"

    def test_returns_none_when_nothing_available(self) -> None:
        req = _make_request(headers={}, client_host=None)
        assert client_ip(req) is None

    def test_request_meta_returns_user_agent(self) -> None:
        req = _make_request(
            headers={
                "x-forwarded-for": "1.1.1.1, 2.2.2.2",
                "user-agent": "test-agent/1.0",
            },
            client_host="10.0.0.1",
        )
        ip, ua = request_meta(req)
        assert ip == "2.2.2.2"
        assert ua == "test-agent/1.0"

    def test_request_meta_user_agent_none_when_absent(self) -> None:
        req = _make_request(headers={}, client_host="10.0.0.1")
        _ip, ua = request_meta(req)
        assert ua is None


# ─── Parity test: middleware._client_ip == (client_ip(req) or "unknown") ──────

_PARITY_MATRIX: list[tuple[str, dict[str, Any], str | None, str]] = [
    # (case_id, headers, client_host, expected_both)
    (
        "spoof",
        {"x-forwarded-for": "evil, 2.2.2.2"},
        "10.0.0.1",
        "2.2.2.2",
    ),
    (
        "single-xff",
        {"x-forwarded-for": "1.1.1.1"},
        "10.0.0.1",
        "1.1.1.1",
    ),
    (
        "whitespace-xff",
        {"x-forwarded-for": "1.1.1.1 , 2.2.2.2 "},
        "10.0.0.1",
        "2.2.2.2",
    ),
    (
        "empty-xff",
        {"x-forwarded-for": ""},
        "10.0.0.1",
        "10.0.0.1",
    ),
    (
        "only-empty-entries",
        {"x-forwarded-for": ", , "},
        "10.0.0.1",
        "10.0.0.1",
    ),
    (
        "ipv6-xff",
        {"x-forwarded-for": "2001:db8::1, 2001:db8::2"},
        "10.0.0.1",
        "2001:db8::2",
    ),
    (
        "x-real-ip-only",
        {"x-real-ip": "3.3.3.3"},
        "10.0.0.1",
        "10.0.0.1",  # x-real-ip must be ignored; client.host wins
    ),
    (
        "no-headers-with-host",
        {},
        "10.0.0.1",
        "10.0.0.1",
    ),
    (
        "no-headers-no-host",
        {},
        None,
        "unknown",  # helper returns None; middleware returns "unknown"
    ),
]

_NOOP_APP: Any = None  # sentinel; BaseHTTPMiddleware accepts an ASGI callable


@pytest.mark.parametrize(
    "case_id,headers,client_host,expected",
    _PARITY_MATRIX,
    ids=[row[0] for row in _PARITY_MATRIX],
)
def test_parity_with_rate_limit_middleware(
    case_id: str,
    headers: dict[str, Any],
    client_host: str | None,
    expected: str,
) -> None:
    """``middleware._client_ip(req)`` must equal ``client_ip(req) or "unknown"``."""
    # Instantiate with a no-op ASGI app — dispatch is never called in this test.
    middleware = RateLimitMiddleware(app=MagicMock())  # type: ignore[arg-type]
    req = _make_request(headers=headers, client_host=client_host)

    helper_result = client_ip(req) or "unknown"
    middleware_result = middleware._client_ip(req)

    assert middleware_result == expected, (
        f"[{case_id}] middleware returned {middleware_result!r}, expected {expected!r}"
    )
    assert helper_result == expected, (
        f"[{case_id}] helper returned {helper_result!r}, expected {expected!r}"
    )
    assert middleware_result == helper_result, (
        f"[{case_id}] middleware={middleware_result!r} != helper={helper_result!r}"
    )
