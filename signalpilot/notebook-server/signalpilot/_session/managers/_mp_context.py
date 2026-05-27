# Copyright 2026 SignalPilot. All rights reserved.
"""Shared multiprocessing context helper for kernel and queue managers.

Uses ``forkserver`` on Linux for faster subprocess startup (the forkserver
process inherits pre-loaded heavy modules via copy-on-write), and falls
back to ``spawn`` everywhere else (macOS, Windows).
"""

from __future__ import annotations

import sys
from multiprocessing import get_context, set_forkserver_preload
from multiprocessing.context import BaseContext

# ---------------------------------------------------------------------------
# Pre-load heavy modules into the forkserver so forked children share them
# via copy-on-write.  This must happen at *import time* — before the first
# forkserver process is created — which is guaranteed because both
# kernel.py and queue.py import this module before spawning anything.
# ---------------------------------------------------------------------------
if sys.platform == "linux":
    set_forkserver_preload([
        "signalpilot._runtime.runtime",
        "signalpilot._messaging.notification",
        "signalpilot._ast.compiler",
    ])


def get_mp_context() -> BaseContext:
    """Return the preferred multiprocessing context for the current platform.

    Linux  -> ``forkserver`` (fast, pre-loaded modules via COW)
    Others -> ``spawn``      (safe default)
    """
    if sys.platform == "linux":
        return get_context("forkserver")
    return get_context("spawn")
