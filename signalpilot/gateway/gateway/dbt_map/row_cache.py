"""Short TTL cache for the dbt-map index lookups.

Every dbt-map GET resolves the project's default branch and reads the latest
gateway_dbt_manifests row; against a remote database those two round trips
dominate the 20 s poll and the 304 path. Entries live for
SP_DBT_MAP_ROW_CACHE_SECONDS (default 5, 0 disables) and are dropped when a
compile is scheduled for the project, so a new compile is visible at once.
Only successful lookups are stored; exceptions propagate uncached.
"""

from __future__ import annotations

import os
import time
from collections import OrderedDict
from dataclasses import dataclass

DEFAULT_TTL_SECONDS = 5.0
MAX_KEYS = 512
_ENV = "SP_DBT_MAP_ROW_CACHE_SECONDS"

Key = tuple[str, str, str | None]


@dataclass(frozen=True)
class RowSnapshot:
    """The columns of GatewayDbtManifest the read routes use."""

    id: str
    project_id: str
    branch: str
    revision: int
    status: str
    trigger: str
    error: str | None
    dbt_version: str | None
    node_count: int
    manifest_bytes: int
    created_at: float
    updated_at: float
    graph_key: str | None
    manifest_key: str | None
    sql_key: str | None

    @classmethod
    def from_row(cls, row) -> RowSnapshot:
        return cls(
            id=row.id,
            project_id=row.project_id,
            branch=row.branch,
            revision=row.revision,
            status=row.status,
            trigger=row.trigger,
            error=row.error,
            dbt_version=row.dbt_version,
            node_count=row.node_count or 0,
            manifest_bytes=row.manifest_bytes or 0,
            created_at=row.created_at,
            updated_at=row.updated_at,
            graph_key=row.graph_key,
            manifest_key=row.manifest_key,
            sql_key=getattr(row, "sql_key", None),
        )


Lookup = tuple[str, RowSnapshot | None]


def ttl_seconds() -> float:
    raw = os.environ.get(_ENV)
    if raw is None or raw.strip() == "":
        return DEFAULT_TTL_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_TTL_SECONDS


class RowCache:
    def __init__(self, max_keys: int = MAX_KEYS) -> None:
        self.max_keys = max_keys
        self._entries: OrderedDict[Key, tuple[float, Lookup]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: Key) -> Lookup | None:
        hit = self._entries.get(key)
        if hit is None:
            self.misses += 1
            return None
        expires_at, value = hit
        if expires_at <= time.monotonic():
            self._entries.pop(key, None)
            self.misses += 1
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        return value

    def put(self, key: Key, value: Lookup) -> None:
        ttl = ttl_seconds()
        if ttl <= 0:
            return
        self._entries[key] = (time.monotonic() + ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_keys:
            self._entries.popitem(last=False)

    def invalidate_project(self, org_id: str, project_id: str) -> int:
        stale = [k for k in self._entries if k[0] == org_id and k[1] == project_id]
        for key in stale:
            del self._entries[key]
        return len(stale)

    def clear(self) -> None:
        self._entries.clear()
        self.hits = self.misses = 0

    def stats(self) -> dict[str, int]:
        return {"entries": len(self._entries), "hits": self.hits, "misses": self.misses}


row_cache = RowCache()
