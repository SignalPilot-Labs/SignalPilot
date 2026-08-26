"""Run-token mint/verify/revoke — HMAC-SHA256 over run_id|org_id|user_id|connector_name|expires_at.

Token format: hex(hmac_sha256(secret, f"{run_id}:{org_id}:{user_id}:{connector_name}:{expires_at_iso}"))

Tokens are kept in-memory; a gateway restart invalidates all live runs.
Concurrent mints for the same run_id raise RunTokenAlreadyExists (409).
Concurrent open sessions for the same run_id are allowed within R3.
Verification is constant-time via hmac.compare_digest.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from .errors import AuthFailed, RunTokenAlreadyExists, RunTokenExpired

_USER_PREFIX = "run-"


@dataclass(frozen=True, slots=True)
class RunTokenClaims:
    """Immutable claims attached to a verified run-token session.

    Fields run_id, org_id, user_id, connector_name, and expires_at are
    included in the HMAC payload and uniquely bind this token to a tenant
    and connector. The token value itself is NEVER stored in this dataclass.
    """

    run_id: uuid.UUID
    org_id: str
    user_id: str
    connector_name: str
    expires_at: float  # Unix timestamp

    def __repr__(self) -> str:
        """Mask token-binding fields in repr to prevent accidental log leakage."""
        return (
            f"RunTokenClaims("
            f"run_id={self.run_id!r}, "
            f"org_id=<masked>, "
            f"user_id=<masked>, "
            f"connector_name={self.connector_name!r}, "
            f"expires_at={self.expires_at!r}"
            f")"
        )


def _compute_hmac(secret: str, run_id: uuid.UUID, org_id: str, user_id: str, connector_name: str, expires_at_iso: str) -> str:
    """Compute hex-encoded HMAC-SHA256 over the canonical claim string."""
    message = f"{run_id}:{org_id}:{user_id}:{connector_name}:{expires_at_iso}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


class RunTokenStore:
    """In-memory store for minted run-tokens.

    Thread-safe via asyncio.Lock. All mutations (mint/revoke) acquire the lock.
    Verify is read-only after the initial dict lookup (safe without lock since
    CPython dicts are read-safe under GIL, but we lock anyway for correctness).
    """

    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("sp_gateway_run_token_secret must not be empty")
        self._secret = secret
        self._tokens: dict[uuid.UUID, tuple[str, RunTokenClaims]] = {}  # run_id -> (token_hex, claims)
        self._lock = asyncio.Lock()

    async def mint(
        self,
        run_id: uuid.UUID,
        org_id: str,
        user_id: str,
        connector_name: str,
        ttl_seconds: int,
    ) -> tuple[str, RunTokenClaims]:
        """Mint a new run-token. Raises RunTokenAlreadyExists if run_id is taken."""
        expires_at_dt = datetime.fromtimestamp(time.time() + ttl_seconds, tz=UTC)
        expires_at_iso = expires_at_dt.isoformat()
        expires_at_unix = expires_at_dt.timestamp()

        token_hex = _compute_hmac(self._secret, run_id, org_id, user_id, connector_name, expires_at_iso)
        claims = RunTokenClaims(
            run_id=run_id,
            org_id=org_id,
            user_id=user_id,
            connector_name=connector_name,
            expires_at=expires_at_unix,
        )

        async with self._lock:
            if run_id in self._tokens:
                raise RunTokenAlreadyExists(f"Token for run_id={run_id} already exists")
            self._tokens[run_id] = (token_hex, claims)

        return token_hex, claims

    async def verify(self, user: str, password: str) -> RunTokenClaims:
        """Verify a startup message's user/password against stored tokens.

        user format: "run-<run_id>" (UUID string).
        password: the hex token returned by mint.
        Raises AuthFailed, RunTokenExpired on failure.
        """
        if not user.startswith(_USER_PREFIX):
            raise AuthFailed(f"Invalid user format: expected 'run-<uuid>', got {user!r}")

        run_id_str = user[len(_USER_PREFIX):]
        try:
            run_id = uuid.UUID(run_id_str)
        except ValueError:
            raise AuthFailed(f"Invalid run_id in user field: {run_id_str!r}")

        async with self._lock:
            entry = self._tokens.get(run_id)

        if entry is None:
            raise AuthFailed(f"No token found for run_id={run_id}")

        stored_token, claims = entry

        # Constant-time comparison
        if not hmac.compare_digest(stored_token, password):
            raise AuthFailed("Token HMAC mismatch")

        if time.time() > claims.expires_at:
            raise RunTokenExpired(f"Token for run_id={run_id} has expired")

        return claims

    async def revoke(self, run_id: uuid.UUID) -> None:
        """Revoke a token by run_id. No-op if already absent."""
        async with self._lock:
            self._tokens.pop(run_id, None)

    async def get(self, run_id: uuid.UUID) -> RunTokenClaims | None:
        """Return claims for a run_id without verification. Returns None if absent."""
        async with self._lock:
            entry = self._tokens.get(run_id)
        if entry is None:
            return None
        return entry[1]


__all__ = ["RunTokenClaims", "RunTokenStore"]
