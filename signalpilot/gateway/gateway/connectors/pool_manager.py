"""Connection pool manager — reuses connector instances instead of recreating per query.

Fixes MED-06: Connection pool recreated per query causing resource leaks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .base import BaseConnector
from .registry import get_connector

log = logging.getLogger("pool_manager")


class PoolManager:
    """Manages a cache of connected connectors, keyed by (db_type, connection_string).

    Connectors are reused across requests and cleaned up after idle timeout.
    """

    def __init__(self, idle_timeout_sec: int = 300):
        self._pools: dict[str, tuple[BaseConnector, float]] = {}
        self._idle_timeout = idle_timeout_sec
        self._lock = asyncio.Lock()

    async def acquire(self, db_type: str, connection_string: str) -> BaseConnector:
        """Get or create a connected connector for the given connection."""
        key = f"{db_type}:{connection_string}"
        async with self._lock:
            if key in self._pools:
                connector, _ = self._pools[key]
                self._pools[key] = (connector, time.monotonic())
                # Verify it's still healthy
                try:
                    if await connector.health_check():
                        return connector
                except Exception as e:
                    log.warning("Health check failed for %s: %s", key.split(":")[0], e)
                # Stale — close and recreate
                try:
                    await connector.close()
                except Exception as e:
                    log.debug("Error closing stale connector: %s", e)
                del self._pools[key]

            connector = get_connector(db_type)
            await connector.connect(connection_string)
            self._pools[key] = (connector, time.monotonic())
            return connector

    async def release(self, db_type: str, connection_string: str) -> None:
        """Mark a connector as available (updates last-used time)."""
        key = f"{db_type}:{connection_string}"
        async with self._lock:
            if key in self._pools:
                connector, _ = self._pools[key]
                self._pools[key] = (connector, time.monotonic())

    async def cleanup_idle(self) -> int:
        """Close connectors that have been idle longer than timeout. Returns count closed."""
        now = time.monotonic()
        closed = 0
        async with self._lock:
            stale_keys = [
                k for k, (_, last_used) in self._pools.items()
                if now - last_used > self._idle_timeout
            ]
            for key in stale_keys:
                connector, _ = self._pools.pop(key)
                try:
                    await connector.close()
                except Exception:
                    pass
                closed += 1
        return closed

    async def close_all(self) -> None:
        """Close all managed connectors."""
        async with self._lock:
            for connector, _ in self._pools.values():
                try:
                    await connector.close()
                except Exception:
                    pass
            self._pools.clear()

    @property
    def pool_count(self) -> int:
        return len(self._pools)


# Global pool manager singleton
pool_manager = PoolManager()
