"""
Schema Cache — caches database introspection results to avoid repeated queries.

Feature #18: Schema caching — on session open, introspect and cache full schema
so list_tables / describe_table are instant.

Cache is refreshable on demand via invalidate().
Default TTL: 5 minutes (configurable).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class _CachedSchema:
    """A cached schema result with expiration tracking."""
    data: dict[str, Any]
    cached_at: float
    ttl_seconds: float

    @property
    def is_expired(self) -> bool:
        return time.monotonic() - self.cached_at > self.ttl_seconds


class SchemaCache:
    """Thread-safe in-memory schema cache keyed by connection name.

    Usage:
        cache = SchemaCache(ttl_seconds=300)

        # Check cache first
        schema = cache.get("my-conn")
        if schema is None:
            schema = await connector.get_schema()
            cache.put("my-conn", schema)

        # Force refresh
        cache.invalidate("my-conn")
    """

    def __init__(self, ttl_seconds: float = 300.0):
        self._ttl = ttl_seconds
        self._cache: dict[str, _CachedSchema] = {}
        self._lock = Lock()

    def get(self, connection_name: str) -> dict[str, Any] | None:
        """Get cached schema for a connection. Returns None on miss or expiration."""
        with self._lock:
            entry = self._cache.get(connection_name)
            if entry is None:
                return None
            if entry.is_expired:
                del self._cache[connection_name]
                return None
            return entry.data

    def put(self, connection_name: str, schema: dict[str, Any]) -> None:
        """Cache schema data for a connection."""
        with self._lock:
            self._cache[connection_name] = _CachedSchema(
                data=schema,
                cached_at=time.monotonic(),
                ttl_seconds=self._ttl,
            )

    def invalidate(self, connection_name: str | None = None) -> int:
        """Invalidate cached schema. If connection_name is None, clear all.

        Returns number of entries invalidated.
        """
        with self._lock:
            if connection_name:
                if connection_name in self._cache:
                    del self._cache[connection_name]
                    return 1
                return 0
            count = len(self._cache)
            self._cache.clear()
            return count

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            active = sum(1 for e in self._cache.values() if not e.is_expired)
            return {
                "cached_connections": active,
                "total_entries": len(self._cache),
                "ttl_seconds": self._ttl,
            }


# Global singleton
schema_cache = SchemaCache()
