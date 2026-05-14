"""Unit tests for auth.dependency — current_user_id behavior."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import httpx
import pytest

from tests.fixtures.jwks import _factory
from workspaces_api.auth.clerk import JwksClient
from workspaces_api.auth.dependency import current_user_id
from workspaces_api.config import Settings
from workspaces_api.errors import AuthInvalidToken, AuthMissingToken, ClerkJWKSUnavailable

_ISSUER = "https://clerk.example.com"
_KID = "test-kid-0001"
_SQLITE_URL = "sqlite+aiosqlite:///:memory:"


def _make_local_settings() -> Settings:
    return Settings.model_validate({
        "SP_DEPLOYMENT_MODE": "local",
        "CLAUDE_CODE_OAUTH_TOKEN": "tok",
        "WORKSPACES_DATABASE_URL": _SQLITE_URL,
    })


def _make_cloud_settings() -> Settings:
    return Settings.model_validate({
        "SP_DEPLOYMENT_MODE": "cloud",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "WORKSPACES_DATABASE_URL": _SQLITE_URL,
        "SP_CLERK_JWKS_URL": "https://clerk.example.com/.well-known/jwks.json",
        "SP_CLERK_ISSUER": _ISSUER,
    })


def _make_jwks_client(jwks_dict: dict) -> JwksClient:
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    client = JwksClient(
        jwks_url="https://clerk.example.com/.well-known/jwks.json",
        http_client=mock_http,
        ttl_seconds=600,
    )
    client._cached_keys = {jwk["kid"]: jwk for jwk in jwks_dict["keys"]}
    client._fetched_at = time.monotonic()
    return client


async def _call_dep(
    settings: Settings,
    jwks_client: JwksClient,
    auth_header: str | None = None,
) -> str | None:
    """Helper to invoke the dependency directly."""
    scope = {"type": "http", "method": "GET", "headers": []}
    if auth_header is not None:
        scope["headers"] = [(b"authorization", auth_header.encode())]

    from starlette.requests import Request as StarletteRequest

    request = StarletteRequest(scope)
    request.state  # initialize state

    async def _get_settings() -> Settings:
        return settings

    async def _get_client() -> JwksClient:
        return jwks_client

    return await current_user_id(request, settings=settings, jwks_client=jwks_client)


class TestCurrentUserIdLocalMode:
    async def test_local_mode_returns_none_no_header_required(self) -> None:
        """C4: local mode always returns None regardless of header."""
        jwks = _make_jwks_client(_factory.jwks_dict(_KID))
        result = await _call_dep(_make_local_settings(), jwks)
        assert result is None

    async def test_local_mode_ignores_authorization_header(self) -> None:
        """C4: Authorization header in local mode is silently ignored."""
        jwks = _make_jwks_client(_factory.jwks_dict(_KID))
        result = await _call_dep(
            _make_local_settings(), jwks, auth_header="Bearer garbage-token"
        )
        assert result is None

    async def test_local_mode_sets_request_state_user_id_none(self) -> None:
        from starlette.requests import Request as StarletteRequest

        settings = _make_local_settings()
        jwks = _make_jwks_client(_factory.jwks_dict(_KID))
        scope = {"type": "http", "method": "GET", "headers": []}
        request = StarletteRequest(scope)
        request.state  # init

        await current_user_id(request, settings=settings, jwks_client=jwks)
        assert request.state.user_id is None


class TestCurrentUserIdCloudMode:
    async def test_cloud_mode_missing_header_raises_auth_missing_token(self) -> None:
        jwks = _make_jwks_client(_factory.jwks_dict(_KID))
        with pytest.raises(AuthMissingToken):
            await _call_dep(_make_cloud_settings(), jwks)

    async def test_cloud_mode_malformed_header_bearer_no_token_raises(self) -> None:
        jwks = _make_jwks_client(_factory.jwks_dict(_KID))
        with pytest.raises(AuthMissingToken):
            await _call_dep(_make_cloud_settings(), jwks, auth_header="Bearer")

    async def test_cloud_mode_malformed_header_wrong_scheme_raises(self) -> None:
        jwks = _make_jwks_client(_factory.jwks_dict(_KID))
        with pytest.raises(AuthMissingToken):
            await _call_dep(
                _make_cloud_settings(), jwks, auth_header="Token some-token"
            )

    async def test_cloud_mode_empty_header_raises(self) -> None:
        jwks = _make_jwks_client(_factory.jwks_dict(_KID))
        with pytest.raises(AuthMissingToken):
            await _call_dep(_make_cloud_settings(), jwks, auth_header="")

    async def test_cloud_mode_valid_jwt_sets_request_state_user_id(self) -> None:
        from starlette.requests import Request as StarletteRequest

        settings = _make_cloud_settings()
        jwks_dict = _factory.jwks_dict(_KID)
        jwks = _make_jwks_client(jwks_dict)
        token = _factory.mint_jwt("user_abc", kid=_KID, issuer=_ISSUER)

        auth_header = f"Bearer {token}"
        scope = {
            "type": "http",
            "method": "GET",
            "headers": [(b"authorization", auth_header.encode())],
        }
        request = StarletteRequest(scope)
        request.state  # init

        result = await current_user_id(request, settings=settings, jwks_client=jwks)
        assert result == "user_abc"
        assert request.state.user_id == "user_abc"

    async def test_cloud_mode_invalid_jwt_raises_auth_invalid_token(self) -> None:
        jwks = _make_jwks_client(_factory.jwks_dict(_KID))
        with pytest.raises(AuthInvalidToken):
            await _call_dep(
                _make_cloud_settings(), jwks, auth_header="Bearer invalid.jwt.token"
            )

    async def test_cloud_mode_jwks_unavailable_returns_503(self) -> None:
        """C3: JWKS unavailable raises ClerkJWKSUnavailable."""
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.get.side_effect = httpx.ConnectError("refused")
        broken_jwks = JwksClient(
            jwks_url="https://clerk.example.com/.well-known/jwks.json",
            http_client=mock_http,
            ttl_seconds=0,  # Always expired → triggers fetch
        )

        token = _factory.mint_jwt("user_abc", kid=_KID, issuer=_ISSUER)
        with pytest.raises(ClerkJWKSUnavailable):
            await _call_dep(
                _make_cloud_settings(), broken_jwks, auth_header=f"Bearer {token}"
            )
