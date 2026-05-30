# DO NOT log token values from this module.
"""Single-use handshake tokens for the /notebook/{id}/_init endpoint.

Tokens are minted at explicit issuance sites and consumed exactly once on /_init.
No token value may appear in any log record — see top-of-file comment.
"""

from __future__ import annotations

import logging
import secrets
import time

logger = logging.getLogger(__name__)

# Token constants.
INIT_TOKEN_TTL_S: int = 60
INIT_TOKEN_BYTES: int = 32
INIT_TOKEN_MAX_ENTRIES: int = 10_000

# In-process store: token -> (session_id, user_id, expires_at_monotonic)
_store: dict[str, tuple[str, str, float]] = {}


def _evict_expired() -> None:
    """Remove all expired entries from _store in place."""
    now = time.monotonic()
    expired_keys = [k for k, (_, _, exp) in _store.items() if exp <= now]
    for k in expired_keys:
        del _store[k]


def _enforce_hard_cap() -> None:
    """Drop oldest entries until len(_store) < INIT_TOKEN_MAX_ENTRIES."""
    if len(_store) < INIT_TOKEN_MAX_ENTRIES:
        return
    logger.warning(
        "init_token store at hard cap (%d entries); evicting oldest entries",
        INIT_TOKEN_MAX_ENTRIES,
    )
    # Sort by expires_at_monotonic ascending; oldest expiry = issued longest ago.
    sorted_items = sorted(_store.items(), key=lambda kv: kv[1][2])
    # Drop entries from the front until we are under the cap.
    evict_count = len(_store) - INIT_TOKEN_MAX_ENTRIES + 1
    for key, _ in sorted_items[:evict_count]:
        del _store[key]


def issue_init_token(session_id: str, user_id: str) -> str:
    """Mint a single-use handshake token bound to (session_id, user_id).

    Opportunistically evicts expired entries and enforces the hard cap before
    inserting. Returns a 43-char URL-safe base64 string.
    """
    _evict_expired()
    _enforce_hard_cap()

    token = secrets.token_urlsafe(INIT_TOKEN_BYTES)
    expires_at = time.monotonic() + INIT_TOKEN_TTL_S
    _store[token] = (session_id, user_id, expires_at)
    return token


def consume_init_token(token: str, session_id: str, user_id: str) -> bool:
    """Atomically pop and validate a handshake token.

    Returns True iff the token exists in the store, matches (session_id, user_id),
    and has not expired. The pop is atomic under the GIL — guarantees single-use
    even under concurrent redemption attempts.

    Step ordering note: consume_init_token needs session_internal.user_id from
    the DB load step. Do NOT call this before the DB row is loaded.
    """
    entry = _store.pop(token, None)
    if entry is None:
        return False
    stored_session_id, stored_user_id, expires_at = entry
    if time.monotonic() > expires_at:
        return False
    if stored_session_id != session_id:
        return False
    if stored_user_id != user_id:
        return False
    return True
