"""Kernel startup warmup — eager module imports for faster subprocess spawn.

Calling ``preload_kernel_modules()`` during server startup eagerly imports
heavy modules so that:

- On Linux with the ``forkserver`` start method, forked children inherit
  them via copy-on-write (no redundant import work per kernel spawn).
- On all platforms, the filesystem cache and bytecode cache are warmed.

This module intentionally has **no background threads, no locks, and no
pool**. The previous ``KernelPool`` (pre-allocated ``QueueManagerImpl``
instances) was removed because it deadlocked in Docker: the pool's
background thread triggered forkserver initialization which hangs in
certain container runtimes, holding a lock that blocked all session creation.
"""

from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)


def preload_kernel_modules() -> None:
    """Import heavy modules so forkserver (or filesystem cache) benefits.

    Call once during server startup, *before* the first kernel process is
    created.  Safe to call on any platform.
    """
    _modules = [
        # `signalpilot` (top-level __init__) eagerly imports App/Cell/_islands/
        # the ui plugins/_client.agent->requests — ~1.3s measured. Importing it
        # here at server boot (before any user connects) means the forkserver and
        # every forked kernel inherit it via copy-on-write, so a kernel spawn pays
        # ~0 import cost instead of ~1.3s. This is the dominant per-spawn latency.
        "signalpilot",
        "signalpilot._runtime.runtime",
        "signalpilot._runtime.app.kernel_runner",
        "signalpilot._ast.compiler",
        "signalpilot._messaging.notification",
        "signalpilot._output.formatters.formatters",
        "signalpilot._runtime.commands",
        "signalpilot._runtime.kernel_lifecycle",
    ]
    for mod in _modules:
        try:
            __import__(mod)
        except Exception:
            LOGGER.debug("preload_kernel_modules: failed to import %s", mod, exc_info=True)

    LOGGER.info("Kernel module pre-import complete (%d modules)", len(_modules))
