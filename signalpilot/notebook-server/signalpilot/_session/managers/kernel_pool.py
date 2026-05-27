"""Pre-warmed kernel process pool for fast EDIT-mode session startup.

Two optimisation layers:

1. **Module pre-import** (``preload_kernel_modules``): Eagerly imports the
   heaviest modules that every kernel process needs.  On Linux with the
   ``forkserver`` start method the forked children inherit these modules
   via copy-on-write, avoiding redundant work on each spawn.  On other
   platforms the imports still warm the filesystem cache and bytecode.

2. **Queue pre-allocation** (``KernelPool``): Creating multiprocessing
   queues is surprisingly expensive (~200 ms per set) because each queue
   sets up an OS pipe and a background feeder thread.  The pool
   pre-allocates ``QueueManagerImpl`` instances in a background thread so
   that ``acquire()`` can hand one off instantly when a new session
   connects.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from signalpilot._session.managers.queue import QueueManagerImpl

if TYPE_CHECKING:
    pass

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Layer 1 — Heavy module pre-import
# ---------------------------------------------------------------------------

def preload_kernel_modules() -> None:
    """Import heavy modules so forkserver (or filesystem cache) benefits.

    Call once during server startup, *before* the first kernel process is
    created.  Safe to call on any platform.
    """
    # Each import is wrapped individually so a failure in one does not
    # block the others.
    _modules = [
        "signalpilot._runtime.runtime",
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


# ---------------------------------------------------------------------------
# Layer 2 — Pre-allocated QueueManager pool
# ---------------------------------------------------------------------------

class KernelPool:
    """Maintains a small pool of pre-allocated ``QueueManagerImpl`` objects.

    Usage::

        pool = KernelPool(pool_size=1)
        pool.start()             # kick off background pre-allocation

        qm = pool.acquire()     # instant if pool is warm, else None
        if qm is None:
            qm = QueueManagerImpl(use_multiprocessing=True)  # fallback
    """

    def __init__(self, pool_size: int = 1) -> None:
        self._pool_size = pool_size
        self._warm: list[QueueManagerImpl] = []
        self._lock = threading.Lock()
        self._filling = False

    # -- public API ---------------------------------------------------------

    def start(self) -> None:
        """Begin filling the pool in a background thread."""
        self._fill_pool_async()

    def acquire(self) -> QueueManagerImpl | None:
        """Pop a pre-warmed ``QueueManagerImpl``, or ``None`` if empty.

        Automatically triggers a background refill after each acquisition.
        """
        with self._lock:
            if self._warm:
                qm = self._warm.pop()
                # Start refilling in background to maintain pool depth
                self._fill_pool_async()
                return qm
        return None

    def shutdown(self) -> None:
        """Close any remaining pre-allocated queues."""
        with self._lock:
            for qm in self._warm:
                try:
                    qm.close_queues()
                except Exception:
                    pass
            self._warm.clear()

    # -- internals ----------------------------------------------------------

    def _fill_pool_async(self) -> None:
        """Spawn a daemon thread to fill the pool up to ``_pool_size``."""
        with self._lock:
            if self._filling:
                return
            deficit = self._pool_size - len(self._warm)
            if deficit <= 0:
                return
            self._filling = True

        thread = threading.Thread(
            target=self._fill_pool, args=(deficit,), daemon=True
        )
        thread.start()

    def _fill_pool(self, count: int) -> None:
        """Create *count* ``QueueManagerImpl`` instances and add them."""
        try:
            for _ in range(count):
                qm = QueueManagerImpl(use_multiprocessing=True)
                with self._lock:
                    self._warm.append(qm)
                LOGGER.debug(
                    "KernelPool: pre-warmed QueueManager (pool size: %d)",
                    len(self._warm),
                )
        except Exception:
            LOGGER.debug("KernelPool: error during pre-warming", exc_info=True)
        finally:
            with self._lock:
                self._filling = False


# ---------------------------------------------------------------------------
# Module-level singleton (lazily initialised by the server lifespan)
# ---------------------------------------------------------------------------

_default_pool: KernelPool | None = None


def get_default_pool() -> KernelPool | None:
    """Return the global pool, or ``None`` if not yet initialised."""
    return _default_pool


def initialize_pool(pool_size: int = 1) -> KernelPool:
    """Create and start the global pool.  Idempotent."""
    global _default_pool
    if _default_pool is None:
        _default_pool = KernelPool(pool_size=pool_size)
        _default_pool.start()
    return _default_pool


def shutdown_pool() -> None:
    """Shut down the global pool if it exists."""
    global _default_pool
    if _default_pool is not None:
        _default_pool.shutdown()
        _default_pool = None
