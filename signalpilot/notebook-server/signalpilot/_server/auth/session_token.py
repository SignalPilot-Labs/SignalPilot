"""Single source of truth for the per-session JWT.

Reads env once at first call (typically import-time from _server.start),
holds in module-private memory, deletes the env var so any subprocess env
constructed afterwards (e.g. kernel via construct_kernel_env) will not see it.
"""
from __future__ import annotations

import os
import threading

_TOKEN: str | None = None
_LOADED: bool = False
_LOCK: threading.Lock = threading.Lock()


def load_session_jwt() -> str:
    """Return the cached session JWT (or '' if env-var was unset).

    Side effect on first call: pops SP_SESSION_JWT from os.environ.
    Idempotent — subsequent calls return the cached value and never re-read env.
    """
    global _TOKEN, _LOADED
    if _LOADED:
        return _TOKEN or ""
    with _LOCK:
        if _LOADED:
            return _TOKEN or ""
        _TOKEN = os.environ.pop("SP_SESSION_JWT", "") or ""
        _LOADED = True
    return _TOKEN


def _reset_for_test() -> None:
    """Reset module state for test isolation. Must NOT be called in production."""
    global _TOKEN, _LOADED
    _TOKEN, _LOADED = None, False
