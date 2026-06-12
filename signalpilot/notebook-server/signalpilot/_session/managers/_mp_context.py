"""Shared multiprocessing context helper for kernel and queue managers.

Uses ``forkserver`` on Linux for faster subprocess startup (the forkserver
process inherits pre-loaded heavy modules via copy-on-write), and falls
back to ``spawn`` everywhere else (macOS, Windows).

Forkserver configuration is **lazy** — ``set_forkserver_preload`` is called
on first use of ``get_mp_context()``, not at import time. This avoids
triggering forkserver initialization from background threads (which
deadlocks in Docker).
"""

from __future__ import annotations

import sys
import threading
from multiprocessing import get_context
from multiprocessing.context import BaseContext

_configured = False
_lock = threading.Lock()

_PRELOAD_MODULES = [
    # The forkserver imports these ONCE at startup; every kernel fork() then
    # inherits the already-imported modules via copy-on-write, so per-kernel
    # spawn skips re-importing the heavy signalpilot graph (~1.3s of
    # _islands/_ast/_client.agent/requests work measured via -X importtime).
    # `signalpilot` (top-level __init__) is the big one — it eagerly pulls App,
    # Cell, _islands, the ui plugins, and _client.agent->requests. Preloading it
    # means kernels fork instantly instead of paying that import each spawn.
    "signalpilot",
    "signalpilot._runtime.runtime",
    "signalpilot._runtime.app.kernel_runner",
    "signalpilot._messaging.notification",
    "signalpilot._ast.compiler",
]


def configure_forkserver() -> None:
    """Configure the forkserver preload list (Linux only). Idempotent."""
    global _configured
    if _configured:
        return
    with _lock:
        if _configured:
            return
        if sys.platform == "linux":
            from multiprocessing import set_forkserver_preload
            set_forkserver_preload(_PRELOAD_MODULES)
        _configured = True


def get_mp_context() -> BaseContext:
    """Return the preferred multiprocessing context for the current platform.

    Linux  -> ``forkserver`` (fast, pre-loaded modules via COW)
    Others -> ``spawn``      (safe default)

    Lazily configures forkserver preload on first call.
    """
    configure_forkserver()
    if sys.platform == "linux":
        return get_context("forkserver")
    return get_context("spawn")
