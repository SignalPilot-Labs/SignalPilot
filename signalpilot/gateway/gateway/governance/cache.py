"""
Query deduplication and caching — Feature #30 from the feature table.

SHA-256 of normalized SQL -> cached result with TTL.
Same query within N minutes returns cached data, saving cost on repeated questions.
Keyed by (org_id, connection_name, sql, row_limit) so two orgs cannot see each other's
cached rows even when querying identically named connections.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from .context import require_org_id


@dataclass
class CacheEntry:
    """A cached query result."""
    key: str
    org_id: str
    connection_name: str
    rows: list[dict[str, Any]]
    tables: list[str]
    execution_ms: float
    sql_executed: str
    created_at: float = field(default_factory=time.time)
    hit_count: int = 0

    def is_expired(self, ttl_seconds: int) -> bool:
        return time.time() - self.created_at > ttl_seconds


class QueryCache:
    """In-memory LRU query result cache with TTL.

    Keyed by SHA-256 of (org_id, connection_name, normalized_sql, row_limit).
    Thread-safe via lock. Public method signatures are unchanged — org_id is
    resolved internally via require_org_id().
    """

    def __init__(self, max_entries: int = 1000, ttl_seconds: int = 300) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._lock = Lock()
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _make_key(org_id: str, connection_name: str, sql: str, row_limit: int) -> str:
        """Generate a deterministic, org-scoped cache key."""
        normalized = " ".join(sql.strip().lower().split())
        raw = f"{org_id}:{connection_name}:{normalized}:{row_limit}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, connection_name: str, sql: str, row_limit: int) -> CacheEntry | None:
        """Look up a cached result. Returns None on miss."""
        org_id = require_org_id()
        key = self._make_key(org_id, connection_name, sql, row_limit)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.is_expired(self._ttl):
                del self._cache[key]
                self._misses += 1
                return None
            entry.hit_count += 1
            self._hits += 1
            return entry

    def put(
        self,
        connection_name: str,
        sql: str,
        row_limit: int,
        rows: list[dict[str, Any]],
        tables: list[str],
        execution_ms: float,
        sql_executed: str,
    ) -> None:
        """Store a query result in the cache."""
        org_id = require_org_id()
        key = self._make_key(org_id, connection_name, sql, row_limit)
        with self._lock:
            # Evict oldest entries if at capacity
            if len(self._cache) >= self._max_entries:
                oldest_key = min(self._cache, key=lambda k: self._cache[k].created_at)
                del self._cache[oldest_key]

            self._cache[key] = CacheEntry(
                key=key,
                org_id=org_id,
                connection_name=connection_name,
                rows=rows,
                tables=tables,
                execution_ms=execution_ms,
                sql_executed=sql_executed,
            )

    def invalidate(self, connection_name: str | None = None, all_orgs: bool = False) -> int:
        """Invalidate cache entries.

        Args:
            connection_name: If given, only invalidate entries for this connection.
                             If None, invalidate all entries in scope.
            all_orgs: If True, invalidate across all orgs (admin callers).
                      If False (default), restrict to the current org via require_org_id().
        """
        if all_orgs:
            with self._lock:
                if connection_name is None:
                    count = len(self._cache)
                    self._cache.clear()
                    return count
                keys_to_remove = [
                    k for k, v in self._cache.items()
                    if v.connection_name == connection_name
                ]
                count = len(keys_to_remove)
                for k in keys_to_remove:
                    del self._cache[k]
                return count

        org_id = require_org_id()
        with self._lock:
            if connection_name is None:
                keys_to_remove = [k for k, v in self._cache.items() if v.org_id == org_id]
            else:
                keys_to_remove = [
                    k for k, v in self._cache.items()
                    if v.org_id == org_id and v.connection_name == connection_name
                ]
            count = len(keys_to_remove)
            for k in keys_to_remove:
                del self._cache[k]
            return count

    def stats(self, all_orgs: bool = False) -> dict[str, Any]:
        """Return cache statistics.

        Args:
            all_orgs: If True, return global counts.
                      If False (default), return counts for the current org only.
        """
        with self._lock:
            if all_orgs:
                entries = len(self._cache)
            else:
                org_id = require_org_id()
                entries = sum(1 for v in self._cache.values() if v.org_id == org_id)
            return {
                "entries": entries,
                "max_entries": self._max_entries,
                "ttl_seconds": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / max(1, self._hits + self._misses), 3),
            }


# Global cache singleton
query_cache = QueryCache()
