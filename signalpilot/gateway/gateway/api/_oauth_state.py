"""OAuth state token generation and verification for GitHub App installs.

This module owns the HMAC key resolution, state encode/decode, and the nonce
TTL store.  It is a pure module — no FastAPI imports, no ``gateway.api.*`` or
``gateway.store.*`` imports.  The only intra-gateway import is
``gateway.runtime.mode.is_cloud_mode``.

Design decisions:

State format (v2)::

    payload = f"v2:{org_id}:{nonce_hex}:{issued_at_unix_int}"
    sig     = hmac_sha256(key, payload.encode()).hexdigest()   # 64 hex chars
    state   = f"{payload}.{sig}"

The ``v2:`` prefix gates future migrations.  Any state missing the prefix is
rejected.  Timestamp is *inside* the signed payload so tampering the timestamp
breaks the HMAC.  Full SHA-256 hex (64 chars) — no truncation, no off-by-one
risk.

Nonce store trade-offs:

The ``_NonceStore`` is a process-local in-memory dict.  This is acceptable
because:

- The gateway runs as a single process per pod for the OAuth callback path.
- The TTL is short (10 minutes); states do not survive restart.
- 128-bit nonces over a 10-minute window have negligible accidental collision
  probability.
- Only states that pass HMAC + expiry checks reach ``reserve``, so an
  unauthenticated attacker cannot stuff the dict.

This mirrors the ``dbt_proxy/tokens.py`` in-memory pattern already in the
codebase.  For multi-replica deployments a shared store (Redis, DB) would be
needed; document as a known gap if you move to active-active.

Key resolution (local mode):

In local mode with no ``SP_ENCRYPTION_KEY`` set, ``get_state_hmac_key()``
generates a random 32-byte key per process and caches it.  States minted before
a pod restart are therefore unverifiable after restart.  This is acceptable for
local development — users simply retry the GitHub install flow.  Mention this
in release notes when deploying to a shared dev environment.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
import time

from ..runtime.mode import is_cloud_mode

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────

STATE_TTL_SECONDS: int = 600   # 10 minutes — GitHub-recommended OAuth state window
NONCE_BYTES: int = 16          # 128-bit nonce, hex-encoded → 32 hex chars

# ─── HMAC Key (lazy, cached) ─────────────────────────────────────────────────

_HMAC_KEY: bytes | None = None
_KEY_LOCK: threading.Lock = threading.Lock()


def get_state_hmac_key() -> bytes:
    """Return the HMAC key for OAuth state signing.

    Resolution order:

    1. Cached value — returned immediately on subsequent calls.
    2. ``SP_ENCRYPTION_KEY`` env var — derives a 32-byte key via SHA-256.
    3. Cloud mode + key absent — raises ``RuntimeError``.  Do NOT cache.
    4. Local mode + key absent — generates ``secrets.token_bytes(32)`` once,
       caches it, and returns it.  Dev-UX note: the random key is not persisted;
       in-flight OAuth flows started before a pod restart will fail verification
       after the restart.  Users must retry the install flow.
    """
    global _HMAC_KEY

    # Fast path — already resolved.
    if _HMAC_KEY is not None:
        return _HMAC_KEY

    with _KEY_LOCK:
        # Double-checked locking — another thread may have resolved between the
        # global read and lock acquisition.
        if _HMAC_KEY is not None:
            return _HMAC_KEY

        raw = os.getenv("SP_ENCRYPTION_KEY")

        if raw is not None:
            derived = hashlib.sha256(raw.encode()).digest()
            _HMAC_KEY = derived
            return _HMAC_KEY

        if is_cloud_mode():
            raise RuntimeError(
                "SP_ENCRYPTION_KEY required in cloud mode for OAuth state signing"
            )

        # Local mode — generate a random key once per process.
        _HMAC_KEY = secrets.token_bytes(32)
        return _HMAC_KEY


# ─── Nonce Store ─────────────────────────────────────────────────────────────


class _NonceStore:
    """In-process nonce TTL store for OAuth state replay prevention.

    Guarded by ``threading.Lock``; FastAPI handlers may run on the threadpool
    for non-async paths.  ``reserve`` returns ``True`` on first insertion and
    ``False`` on replay (nonce already present).  ``_gc`` purges expired entries
    and is called opportunistically on every ``reserve`` call — cheap given the
    low call rate and short TTL.
    """

    def __init__(self) -> None:
        self._entries: dict[str, float] = {}   # nonce_hex → expires_at_unix
        self._lock: threading.Lock = threading.Lock()

    def reserve(self, nonce_hex: str, expires_at: float) -> bool:
        """Insert *nonce_hex* with expiry *expires_at*.

        Returns ``True`` if newly inserted (first use), ``False`` if already
        present (replay attack).
        """
        with self._lock:
            self._gc()
            if nonce_hex in self._entries:
                return False
            self._entries[nonce_hex] = expires_at
            return True

    def _gc(self) -> None:
        """Remove expired entries from the store (called under lock)."""
        now = time.time()
        expired = [k for k, v in self._entries.items() if v <= now]
        for k in expired:
            del self._entries[k]


# Module-level singleton — one nonce store per process.
_NONCE_STORE: _NonceStore = _NonceStore()

# ─── State Encoding ───────────────────────────────────────────────────────────


def make_state(org_id: str) -> str:
    """Mint a signed OAuth state token for *org_id*.

    Format::

        state = f"v2:{org_id}:{nonce_hex}:{issued_at_unix_int}.{sig_hex}"

    The timestamp and nonce are embedded *inside* the signed payload so any
    tampering invalidates the HMAC.
    """
    key = get_state_hmac_key()
    nonce_hex = secrets.token_hex(NONCE_BYTES)
    issued_at = int(time.time())
    payload = f"v2:{org_id}:{nonce_hex}:{issued_at}"
    sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


# ─── State Verification ──────────────────────────────────────────────────────


def verify_state(state: str | None) -> str | None:
    """Verify a signed OAuth state token and return *org_id* on success.

    Returns ``None`` on any failure.  The caller must NOT differentiate the
    failure reason in user-facing messages — return a single generic 400.

    Verification order (LOAD-BEARING — do NOT reorder):

    1. Empty/None guard.
    2. Format split (last ``.``).
    3. HMAC constant-time compare.
    4. Prefix + field parse (``v2:``).
    5. Expiry check.
    6. Nonce reserve (replay prevention) — LAST, only after all other checks.
    7. Return *org_id*.
    """
    # Step 1 — empty/None guard.  Fail closed before any other check.
    if not state:
        logger.warning(
            "oauth_state_rejected",
            extra={"reason": "empty", "remote_ip": None, "org_id_hint": None},
        )
        return None

    # Step 2 — format: split on the LAST dot.
    dot_idx = state.rfind(".")
    if dot_idx == -1:
        logger.warning(
            "oauth_state_rejected",
            extra={"reason": "format", "remote_ip": None, "org_id_hint": None},
        )
        return None

    payload = state[:dot_idx]
    sig = state[dot_idx + 1:]

    if not payload or not sig:
        logger.warning(
            "oauth_state_rejected",
            extra={"reason": "format", "remote_ip": None, "org_id_hint": None},
        )
        return None

    # Step 3 — HMAC verification (constant-time).
    key = get_state_hmac_key()
    expected_sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        logger.warning(
            "oauth_state_rejected",
            extra={"reason": "signature", "remote_ip": None, "org_id_hint": None},
        )
        return None

    # Step 4 — prefix + field parse.
    fields = payload.split(":")
    if len(fields) != 4 or fields[0] != "v2":
        logger.warning(
            "oauth_state_rejected",
            extra={"reason": "format", "remote_ip": None, "org_id_hint": None},
        )
        return None

    _, org_id, nonce_hex, issued_at_str = fields

    # Step 5 — expiry.
    try:
        issued_at = int(issued_at_str)
    except ValueError:
        logger.warning(
            "oauth_state_rejected",
            extra={"reason": "format", "remote_ip": None, "org_id_hint": None},
        )
        return None

    if time.time() - issued_at > STATE_TTL_SECONDS:
        logger.warning(
            "oauth_state_rejected",
            extra={"reason": "expired", "remote_ip": None, "org_id_hint": None},
        )
        return None

    # Step 6 — nonce reserve (replay prevention).  Only reached after all
    # other checks pass, so garbage inputs cannot grow the dict.
    expires_at = issued_at + STATE_TTL_SECONDS
    if not _NONCE_STORE.reserve(nonce_hex, float(expires_at)):
        logger.warning(
            "oauth_state_rejected",
            extra={"reason": "replay", "remote_ip": None, "org_id_hint": None},
        )
        return None

    # Step 7 — success.
    return org_id


__all__ = ["STATE_TTL_SECONDS", "NONCE_BYTES", "get_state_hmac_key", "make_state", "verify_state"]
