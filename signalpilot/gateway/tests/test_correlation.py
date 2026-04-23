"""Tests for RequestCorrelationMiddleware.

Uses httpx.AsyncClient with ASGITransport against the FastAPI app from gateway.main.
The /health endpoint is public (no auth required) so all tests target it.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from gateway.main import app


def _is_valid_uuid4(value: str) -> bool:
    """Return True if value is a well-formed UUID4 string."""
    try:
        parsed = uuid.UUID(value, version=4)
        return str(parsed) == value
    except (ValueError, AttributeError):
        return False


class TestRequestCorrelationMiddleware:
    """Tests for the X-Request-ID correlation middleware."""

    @pytest.mark.asyncio
    async def test_response_has_request_id_header(self):
        """Every response must include an X-Request-ID header."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/health")

        assert response.status_code == 200
        assert "x-request-id" in response.headers
        assert _is_valid_uuid4(response.headers["x-request-id"])

    @pytest.mark.asyncio
    async def test_client_provided_request_id_is_echoed(self):
        """A valid client-provided X-Request-ID must be echoed back unchanged."""
        known_id = str(uuid.uuid4())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/health", headers={"X-Request-ID": known_id})

        assert response.status_code == 200
        assert response.headers["x-request-id"] == known_id

    @pytest.mark.asyncio
    async def test_invalid_request_id_is_replaced(self):
        """A header injection attempt must be replaced with a new valid UUID4."""
        malicious_id = '"><script>alert(1)</script>'
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/health", headers={"X-Request-ID": malicious_id})

        assert response.status_code == 200
        returned_id = response.headers["x-request-id"]
        assert returned_id != malicious_id
        assert _is_valid_uuid4(returned_id)

    @pytest.mark.asyncio
    async def test_oversized_request_id_is_replaced(self):
        """An X-Request-ID value exceeding 64 chars must be replaced with a new UUID4."""
        oversized_id = "a" * 200
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/health", headers={"X-Request-ID": oversized_id})

        assert response.status_code == 200
        returned_id = response.headers["x-request-id"]
        assert returned_id != oversized_id
        assert _is_valid_uuid4(returned_id)

    @pytest.mark.asyncio
    async def test_empty_request_id_generates_new(self):
        """An empty X-Request-ID must be replaced with a new valid UUID4."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/health", headers={"X-Request-ID": ""})

        assert response.status_code == 200
        returned_id = response.headers["x-request-id"]
        assert _is_valid_uuid4(returned_id)

    @pytest.mark.asyncio
    async def test_request_id_is_consistent_in_response(self):
        """The returned X-Request-ID is always exactly one header value."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/health")

        assert response.status_code == 200
        # httpx merges duplicate headers with comma; a single UUID has no comma
        returned_id = response.headers["x-request-id"]
        assert "," not in returned_id
        assert _is_valid_uuid4(returned_id)

    @pytest.mark.asyncio
    async def test_alphanumeric_hyphen_request_id_accepted(self):
        """A valid alphanumeric-with-hyphens request ID (non-UUID) is echoed back."""
        custom_id = "my-service-abc123"
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/health", headers={"X-Request-ID": custom_id})

        assert response.status_code == 200
        assert response.headers["x-request-id"] == custom_id

    @pytest.mark.asyncio
    async def test_request_id_with_special_chars_is_replaced(self):
        """An X-Request-ID containing underscores or spaces must be replaced."""
        for bad_id in ("my_id_with_underscores", "has space here", "pipe|char"):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get("/health", headers={"X-Request-ID": bad_id})

            assert response.status_code == 200
            returned_id = response.headers["x-request-id"]
            assert returned_id != bad_id
            assert _is_valid_uuid4(returned_id)
