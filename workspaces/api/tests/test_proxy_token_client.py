"""Tests for ProxyTokenClient — mint, revoke, repr masking."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from workspaces_api.agent.proxy_token_client import ProxyTokenClient, ProxyTokenLease
from workspaces_api.errors import ProxyTokenMintFailed

_RUN_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_TOKEN = "secrethextoken1234"
_EXPIRES = "2026-05-01T12:00:00+00:00"
_HOST_PORT = 15432
_GATEWAY_URL = "http://gateway.test"


def _mint_response_200() -> dict:
    return {"token": _TOKEN, "host_port": _HOST_PORT, "expires_at": _EXPIRES}


def _make_client(transport: httpx.MockTransport, api_key: str | None = None) -> ProxyTokenClient:
    http = httpx.AsyncClient(transport=transport)
    return ProxyTokenClient(
        gateway_url=_GATEWAY_URL,
        http_client=http,
        api_key=api_key,
    )


class TestProxyTokenClientMint:
    @pytest.mark.asyncio
    async def test_mint_success_returns_lease(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json=_mint_response_200())

        client = _make_client(httpx.MockTransport(handler))
        lease = await client.mint(_RUN_ID, "my_connector", 3600)

        assert lease.host_port == _HOST_PORT
        assert lease.token == _TOKEN
        assert isinstance(lease.expires_at, datetime)

    @pytest.mark.asyncio
    async def test_mint_401_raises_auth(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "unauthorized"})

        client = _make_client(httpx.MockTransport(handler))
        with pytest.raises(ProxyTokenMintFailed) as exc_info:
            await client.mint(_RUN_ID, "my_connector", 3600)
        assert "auth" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_mint_409_retries_and_succeeds(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            # First call is mint (409), second is revoke DELETE (204), third is mint retry (201)
            if request.method == "DELETE":
                return httpx.Response(204)
            if call_count == 1:
                return httpx.Response(409, json={"detail": "conflict"})
            return httpx.Response(201, json=_mint_response_200())

        client = _make_client(httpx.MockTransport(handler))
        lease = await client.mint(_RUN_ID, "my_connector", 3600)
        assert lease.token == _TOKEN

    @pytest.mark.asyncio
    async def test_mint_409_twice_raises_conflict(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "DELETE":
                return httpx.Response(204)
            return httpx.Response(409, json={"detail": "conflict"})

        client = _make_client(httpx.MockTransport(handler))
        with pytest.raises(ProxyTokenMintFailed) as exc_info:
            await client.mint(_RUN_ID, "my_connector", 3600)
        assert "conflict" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_mint_network_error_raises_mint_failed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client = _make_client(httpx.MockTransport(handler))
        with pytest.raises(ProxyTokenMintFailed) as exc_info:
            await client.mint(_RUN_ID, "my_connector", 3600)
        assert "network error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_mint_sends_bearer_header_when_api_key_set(self) -> None:
        captured_headers: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            return httpx.Response(201, json=_mint_response_200())

        client = _make_client(httpx.MockTransport(handler), api_key="sp_mykey")
        await client.mint(_RUN_ID, "my_connector", 3600)

        assert captured_headers
        assert captured_headers[0].get("authorization") == "Bearer sp_mykey"

    @pytest.mark.asyncio
    async def test_mint_omits_bearer_header_when_no_api_key(self) -> None:
        captured_headers: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            return httpx.Response(201, json=_mint_response_200())

        client = _make_client(httpx.MockTransport(handler), api_key=None)
        await client.mint(_RUN_ID, "my_connector", 3600)

        assert "authorization" not in captured_headers[0]


class TestProxyTokenClientRevoke:
    @pytest.mark.asyncio
    async def test_revoke_204_succeeds(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        client = _make_client(httpx.MockTransport(handler))
        await client.revoke(_RUN_ID)  # Should not raise

    @pytest.mark.asyncio
    async def test_revoke_404_succeeds(self) -> None:
        """Gateway returns 204 always (idempotent) but test that non-204 doesn't raise either."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        client = _make_client(httpx.MockTransport(handler))
        await client.revoke(_RUN_ID)  # Should not raise

    @pytest.mark.asyncio
    async def test_revoke_network_error_does_not_raise(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("gone")

        client = _make_client(httpx.MockTransport(handler))
        await client.revoke(_RUN_ID)  # Should log warning but not raise


class TestProxyTokenLeaseRepr:
    def test_lease_repr_masks_token(self) -> None:
        lease = ProxyTokenLease(
            token="supersecrettoken",
            host_port=15432,
            expires_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        r = repr(lease)
        assert "supersecrettoken" not in r
        assert "***" in r

    def test_client_repr_does_not_expose_api_key(self) -> None:
        http = httpx.AsyncClient()
        client = ProxyTokenClient(
            gateway_url="http://gw",
            http_client=http,
            api_key="sp_secret_key",
        )
        r = repr(client)
        assert "sp_secret_key" not in r
