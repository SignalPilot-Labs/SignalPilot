"""Clerk JWT verification and JWKS client.

Dependency direction: auth.clerk → errors, config. Does NOT import from routes,
models, or db. This module is a pure auth concern.

JWKS caching:
- One process-wide JwksClient per app (built in lifespan, stored on app.state).
- TTL-based cache: after ttl_seconds, the next request triggers a refetch.
- async lock prevents concurrent refetches (only one fetch per cache miss).

Token verification order:
  1. Decode unverified header to extract kid.
  2. Look up JWKS entry by kid (fetch from Clerk if cache miss/expired).
  3. Assert kty=="RSA" and alg=="RS256" on the JWKS entry (C2).
  4. jwt.decode(token, key, algorithms=["RS256"], issuer=issuer, audience=audience).
  5. Return sub claim.

Failure modes:
  - Network/non-2xx on JWKS fetch → ClerkJWKSUnavailable (503).
  - Bad signature, expired, wrong issuer/aud, unknown kid, kty/alg mismatch →
    AuthInvalidToken (401).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from workspaces_api.errors import AuthInvalidToken, ClerkJWKSUnavailable

logger = logging.getLogger(__name__)


class JwksClient:
    """Async JWKS client with TTL cache and concurrent-miss protection."""

    def __init__(
        self,
        jwks_url: str,
        http_client: httpx.AsyncClient,
        ttl_seconds: int,
    ) -> None:
        self._jwks_url = jwks_url
        self._http_client = http_client
        self._ttl_seconds = ttl_seconds
        self._cached_keys: dict[str, Any] = {}  # kid → jwk dict
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    def _is_expired(self) -> bool:
        return (time.monotonic() - self._fetched_at) >= self._ttl_seconds

    async def _fetch(self) -> None:
        """Fetch JWKS from Clerk and update the cache. Raises ClerkJWKSUnavailable."""
        try:
            resp = await self._http_client.get(self._jwks_url)
        except Exception as exc:
            raise ClerkJWKSUnavailable(
                f"JWKS fetch network error: {type(exc).__name__}"
            ) from exc

        if resp.status_code < 200 or resp.status_code >= 300:
            raise ClerkJWKSUnavailable(
                f"JWKS fetch returned HTTP {resp.status_code}"
            )

        data = resp.json()
        keys: dict[str, Any] = {}
        for jwk in data.get("keys", []):
            kid = jwk.get("kid")
            if kid:
                keys[kid] = jwk
        self._cached_keys = keys
        self._fetched_at = time.monotonic()

    async def get_key(self, kid: str) -> Any:
        """Return the JWK dict for the given kid. Fetches if cache miss or expired.

        Raises ClerkJWKSUnavailable on upstream error.
        Raises AuthInvalidToken if kid is not in the JWKS after fetching.
        """
        async with self._lock:
            if self._is_expired():
                await self._fetch()

        jwk = self._cached_keys.get(kid)
        if jwk is None:
            # Possibly a new key rotated in; try one refetch under lock.
            async with self._lock:
                if kid not in self._cached_keys:
                    await self._fetch()
            jwk = self._cached_keys.get(kid)

        if jwk is None:
            raise AuthInvalidToken(f"unknown_kid: {kid}")
        return jwk


async def verify_clerk_jwt(
    token: str,
    jwks_client: JwksClient,
    *,
    issuer: str,
    audience: str | None,
) -> str:
    """Verify a Clerk JWT and return the `sub` claim.

    Args:
        token: Raw JWT string (must NOT appear in logs).
        jwks_client: Process-wide JWKS client from app.state.
        issuer: Expected issuer claim (required).
        audience: Expected audience claim, or None to skip audience validation.

    Returns:
        The `sub` claim (Clerk user ID).

    Raises:
        ClerkJWKSUnavailable: JWKS upstream unreachable or non-2xx (503).
        AuthInvalidToken: Any token-content failure (401).
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.exceptions.DecodeError as exc:
        raise AuthInvalidToken(f"malformed_header: {type(exc).__name__}") from exc

    kid = unverified_header.get("kid")
    if not kid:
        raise AuthInvalidToken("missing_kid")

    # May raise ClerkJWKSUnavailable or AuthInvalidToken
    jwk = await jwks_client.get_key(kid)

    # C2: Assert kty=="RSA" and alg=="RS256" on the JWKS entry before constructing key.
    if jwk.get("kty") != "RSA":
        raise AuthInvalidToken("jwk_alg_mismatch: kty is not RSA")
    if jwk.get("alg", "RS256") != "RS256":
        raise AuthInvalidToken("jwk_alg_mismatch: alg is not RS256")

    try:
        public_key: Any = RSAAlgorithm.from_jwk(jwk)
    except Exception as exc:
        raise AuthInvalidToken(f"jwk_construction_failed: {type(exc).__name__}") from exc

    decode_kwargs: dict[str, Any] = {
        "algorithms": ["RS256"],
        "issuer": issuer,
        "options": {"require": ["sub", "iss", "exp"]},
    }
    if audience is not None:
        decode_kwargs["audience"] = audience

    try:
        payload = jwt.decode(token, public_key, **decode_kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise AuthInvalidToken("token_expired") from exc
    except jwt.InvalidIssuerError as exc:
        raise AuthInvalidToken("invalid_issuer") from exc
    except jwt.InvalidAudienceError as exc:
        raise AuthInvalidToken("invalid_audience") from exc
    except jwt.InvalidSignatureError as exc:
        raise AuthInvalidToken("invalid_signature") from exc
    except jwt.DecodeError as exc:
        raise AuthInvalidToken(f"decode_error: {type(exc).__name__}") from exc
    except jwt.PyJWTError as exc:
        raise AuthInvalidToken(f"jwt_error: {type(exc).__name__}") from exc

    sub: str = payload["sub"]
    return sub
