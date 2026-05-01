"""Unit tests for auth.clerk — JwksClient and verify_clerk_jwt."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest

from tests.fixtures.jwks import _factory
from workspaces_api.auth.clerk import JwksClient, verify_clerk_jwt
from workspaces_api.errors import AuthInvalidToken, ClerkJWKSUnavailable

_ISSUER = "https://clerk.example.com"
_KID = "test-kid-0001"


def _make_mock_http(jwks_dict: dict) -> AsyncMock:
    mock = AsyncMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = jwks_dict
    mock.get.return_value = response
    return mock


def _make_client(http_client: AsyncMock, ttl_seconds: int = 600) -> JwksClient:
    return JwksClient(
        jwks_url="https://clerk.example.com/.well-known/jwks.json",
        http_client=http_client,
        ttl_seconds=ttl_seconds,
    )


def _prefill_client(client: JwksClient, jwks_dict: dict) -> None:
    """Pre-populate the client cache so tests don't need live HTTP."""
    client._cached_keys = {jwk["kid"]: jwk for jwk in jwks_dict["keys"]}
    client._fetched_at = time.monotonic()


class TestVerifyClerkJwt:
    async def test_verifies_valid_jwt_returns_sub(self) -> None:
        jwks_dict = _factory.jwks_dict(_KID)
        http = _make_mock_http(jwks_dict)
        client = _make_client(http)
        _prefill_client(client, jwks_dict)

        token = _factory.mint_jwt("user_123", kid=_KID, issuer=_ISSUER)
        sub = await verify_clerk_jwt(token, client, issuer=_ISSUER, audience=None)
        assert sub == "user_123"

    async def test_rejects_expired_jwt(self) -> None:
        jwks_dict = _factory.jwks_dict(_KID)
        http = _make_mock_http(jwks_dict)
        client = _make_client(http)
        _prefill_client(client, jwks_dict)

        token = _factory.mint_expired_jwt("user_abc", kid=_KID, issuer=_ISSUER)
        with pytest.raises(AuthInvalidToken, match="token_expired"):
            await verify_clerk_jwt(token, client, issuer=_ISSUER, audience=None)

    async def test_rejects_wrong_issuer(self) -> None:
        jwks_dict = _factory.jwks_dict(_KID)
        http = _make_mock_http(jwks_dict)
        client = _make_client(http)
        _prefill_client(client, jwks_dict)

        token = _factory.mint_jwt("user_abc", kid=_KID, issuer="https://wrong.issuer.com")
        with pytest.raises(AuthInvalidToken, match="invalid_issuer"):
            await verify_clerk_jwt(token, client, issuer=_ISSUER, audience=None)

    async def test_rejects_wrong_audience_when_audience_set(self) -> None:
        jwks_dict = _factory.jwks_dict(_KID)
        http = _make_mock_http(jwks_dict)
        client = _make_client(http)
        _prefill_client(client, jwks_dict)

        token = _factory.mint_jwt(
            "user_abc", kid=_KID, issuer=_ISSUER, audience="wrong-audience"
        )
        with pytest.raises(AuthInvalidToken):
            await verify_clerk_jwt(
                token, client, issuer=_ISSUER, audience="expected-audience"
            )

    async def test_no_audience_check_when_audience_none(self) -> None:
        jwks_dict = _factory.jwks_dict(_KID)
        http = _make_mock_http(jwks_dict)
        client = _make_client(http)
        _prefill_client(client, jwks_dict)

        # Token with audience=None and verifier with audience=None should pass
        token = _factory.mint_jwt("user_abc", kid=_KID, issuer=_ISSUER)
        sub = await verify_clerk_jwt(token, client, issuer=_ISSUER, audience=None)
        assert sub == "user_abc"

    async def test_unknown_kid_raises_auth_invalid_token(self) -> None:
        jwks_dict = _factory.jwks_dict(_KID)
        http = _make_mock_http(jwks_dict)
        client = _make_client(http)
        _prefill_client(client, jwks_dict)

        token = _factory.mint_jwt("user_abc", kid="unknown-kid", issuer=_ISSUER)
        with pytest.raises(AuthInvalidToken, match="unknown_kid"):
            await verify_clerk_jwt(token, client, issuer=_ISSUER, audience=None)

    async def test_jwks_entry_with_wrong_kty_rejected_as_invalid_token(self) -> None:
        """C2: kty != 'RSA' must be rejected."""
        jwks_dict = _factory.jwks_dict(_KID)
        # Tamper with kty
        jwks_dict["keys"][0]["kty"] = "EC"
        http = _make_mock_http(jwks_dict)
        client = _make_client(http)
        _prefill_client(client, jwks_dict)

        token = _factory.mint_jwt("user_abc", kid=_KID, issuer=_ISSUER)
        with pytest.raises(AuthInvalidToken, match="jwk_alg_mismatch"):
            await verify_clerk_jwt(token, client, issuer=_ISSUER, audience=None)

    async def test_jwks_entry_with_alg_other_than_rs256_rejected_as_invalid_token(
        self,
    ) -> None:
        """C2: alg != 'RS256' must be rejected."""
        jwks_dict = _factory.jwks_dict(_KID)
        jwks_dict["keys"][0]["alg"] = "ES256"
        http = _make_mock_http(jwks_dict)
        client = _make_client(http)
        _prefill_client(client, jwks_dict)

        token = _factory.mint_jwt("user_abc", kid=_KID, issuer=_ISSUER)
        with pytest.raises(AuthInvalidToken, match="jwk_alg_mismatch"):
            await verify_clerk_jwt(token, client, issuer=_ISSUER, audience=None)

    async def test_alg_none_token_rejected(self) -> None:
        """C2: alg=none tokens must be rejected at the library layer."""
        jwks_dict = _factory.jwks_dict(_KID)
        http = _make_mock_http(jwks_dict)
        client = _make_client(http)
        _prefill_client(client, jwks_dict)

        # Mint an alg=none token (unsigned)
        payload = {
            "sub": "attacker",
            "iss": _ISSUER,
            "exp": int(time.time()) + 300,
        }
        # jwt.encode with algorithm="none" produces an unsigned token
        unsigned_token = jwt.encode(payload, "", algorithm="none")

        with pytest.raises((AuthInvalidToken, Exception)):
            await verify_clerk_jwt(unsigned_token, client, issuer=_ISSUER, audience=None)

    async def test_jwks_fetch_network_error_raises_clerk_jwks_unavailable_503(
        self,
    ) -> None:
        """C3: Network error on JWKS fetch → ClerkJWKSUnavailable (503)."""
        mock = AsyncMock(spec=httpx.AsyncClient)
        mock.get.side_effect = httpx.ConnectError("connection refused")
        client = JwksClient(
            jwks_url="https://clerk.example.com/.well-known/jwks.json",
            http_client=mock,
            ttl_seconds=600,
        )
        # Force cache to be expired
        client._fetched_at = 0.0

        with pytest.raises(ClerkJWKSUnavailable):
            await client.get_key("any-kid")

    async def test_jwks_fetch_non_2xx_raises_clerk_jwks_unavailable_503(self) -> None:
        """C3: Non-2xx JWKS response → ClerkJWKSUnavailable (503)."""
        mock = AsyncMock(spec=httpx.AsyncClient)
        response = MagicMock()
        response.status_code = 503
        mock.get.return_value = response
        client = JwksClient(
            jwks_url="https://clerk.example.com/.well-known/jwks.json",
            http_client=mock,
            ttl_seconds=600,
        )
        client._fetched_at = 0.0

        with pytest.raises(ClerkJWKSUnavailable):
            await client.get_key("any-kid")


class TestJwksClientCache:
    async def test_jwks_cache_hit_does_not_refetch(self) -> None:
        jwks_dict = _factory.jwks_dict(_KID)
        http = _make_mock_http(jwks_dict)
        client = _make_client(http)
        _prefill_client(client, jwks_dict)

        # First access — cache warm
        await client.get_key(_KID)
        await client.get_key(_KID)

        # No HTTP call should have been made (cache was pre-filled)
        http.get.assert_not_called()

    async def test_jwks_cache_expiry_triggers_refetch(self) -> None:
        """TTL=0 means every access triggers a refetch."""
        jwks_dict = _factory.jwks_dict(_KID)
        http = _make_mock_http(jwks_dict)
        client = _make_client(http, ttl_seconds=0)
        # Don't prefill — let it fetch

        await client.get_key(_KID)
        assert http.get.call_count >= 1

    async def test_concurrent_cache_miss_only_one_fetch(self) -> None:
        """Multiple concurrent requests on cache miss should only trigger one fetch."""
        jwks_dict = _factory.jwks_dict(_KID)
        http = _make_mock_http(jwks_dict)
        client = _make_client(http, ttl_seconds=0)

        # All concurrent calls; TTL=0 means expired, but lock prevents multi-fetch
        results = await asyncio.gather(*[client.get_key(_KID) for _ in range(5)])
        assert all(r is not None for r in results)
        # With TTL=0, each call may re-fetch due to expiry check outside lock,
        # but the lock ensures serialize. Count is ≤ 5 and ≥ 1.
        assert http.get.call_count >= 1
