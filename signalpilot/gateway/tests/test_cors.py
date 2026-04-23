"""Tests for CORS configuration — X-Request-ID header exposure and allow-list.

Uses the FastAPI TestClient against the app from gateway.main.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from gateway.main import app

_ALLOWED_ORIGIN = "http://localhost:3200"


class TestCorsRequestId:
    """CORS tests verifying X-Request-ID is exposed and allowed as a request header."""

    def test_cors_exposes_request_id(self) -> None:
        """A cross-origin response must include X-Request-ID in Access-Control-Expose-Headers.

        Browsers only receive Access-Control-Expose-Headers on actual responses (not OPTIONS
        preflight), so this test uses a GET against the public /health endpoint.
        """
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/health",
            headers={"Origin": _ALLOWED_ORIGIN},
        )
        expose_headers = response.headers.get("access-control-expose-headers", "")
        assert "X-Request-ID" in expose_headers, (
            f"Expected X-Request-ID in Access-Control-Expose-Headers, got: {expose_headers!r}"
        )

    def test_cors_allows_request_id_header(self) -> None:
        """Preflight response must include X-Request-ID in Access-Control-Allow-Headers."""
        client = TestClient(app, raise_server_exceptions=False)
        response = client.options(
            "/health",
            headers={
                "Origin": _ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Request-ID",
            },
        )
        allow_headers = response.headers.get("access-control-allow-headers", "")
        assert "X-Request-ID" in allow_headers, (
            f"Expected X-Request-ID in Access-Control-Allow-Headers, got: {allow_headers!r}"
        )
