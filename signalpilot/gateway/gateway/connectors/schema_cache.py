"""
Schema Cache — caches database introspection results to avoid repeated queries.

Feature #18: Schema caching — on session open, introspect and cache full schema
so list_tables / describe_table are instant.

Cache is refreshable on demand via invalidate().
Default TTL: 5 minutes (configurable).

Enhanced with schema fingerprinting for fast change detection and
diff history tracking for audit/notification.

Org isolation: all cache keys are prefixed with org_id resolved via require_org_id()
so two orgs with identically named connections cannot see each other's schemas.
"""

from __future__ import annotations

import hashlib
import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Any

from ..governance.context import require_org_id


def _normalize_schema(schema: dict[str, Any]) -> None:
    """Normalize schema in-place to ensure consistent structure across all connectors.

    Fills missing baseline fields so downstream consumers (DDL generation,
    schema linking, Spider2.0 agent context) don't need per-DB special casing.
    """
    for table_key, table_data in schema.items():
        # Table-level defaults
        table_data.setdefault("schema", "")
        table_data.setdefault("name", table_key.rsplit(".", 1)[-1])
        table_data.setdefault("type", "table")
        table_data.setdefault("columns", [])
        table_data.setdefault("foreign_keys", [])
        table_data.setdefault("row_count", 0)
        table_data.setdefault("description", "")

        # Normalize size: BigQuery uses size_bytes, others use size_mb
        if "size_bytes" in table_data and "size_mb" not in table_data:
            try:
                table_data["size_mb"] = round(int(table_data["size_bytes"]) / (1024 * 1024), 2)
            except (ValueError, TypeError):
                pass

        # Column-level defaults
        for col in table_data["columns"]:
            col.setdefault("name", "")
            col.setdefault("type", "unknown")
            col.setdefault("nullable", True)
            col.setdefault("primary_key", False)
            col.setdefault("comment", "")


def _schema_fingerprint(schema: dict[str, Any]) -> str:
    """Compute a fast structural fingerprint of a schema.

    Captures table names, column names+types, and FK relationships.
    Ignores volatile fields (row_count, stats, comments) so the fingerprint
    only changes when the actual DDL structure changes.
    """
    parts: list[str] = []
    for table_key in sorted(schema.keys()):
        table = schema[table_key]
        cols = table.get("columns", [])
        col_sigs = []
        for c in cols:
            sig = f"{c.get('name', '')}:{c.get('type', '')}:{c.get('nullable', '')}:{c.get('primary_key', '')}"
            col_sigs.append(sig)
        fks = table.get("foreign_keys", [])
        fk_sigs = []
        for fk in fks:
            fk_sigs.append(f"{fk.get('column', '')}->{fk.get('references_table', '')}.{fk.get('references_column', '')}")
        parts.append(f"{table_key}|{'|'.join(sorted(col_sigs))}|FK:{'|'.join(sorted(fk_sigs))}")
    combined = "\n".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


@dataclass
class _CachedSchema:
    """A cached schema result with expiration tracking and fingerprint."""
    data: dict[str, Any]
    cached_at: float
    ttl_seconds: float
    fingerprint: str = ""

    @property
    def is_expired(self) -> bool:
        return time.monotonic() - self.cached_at > self.ttl_seconds


@dataclass
class SchemaDiffEvent:
    """Records a schema change detected during refresh."""
    connection_name: str
    timestamp: float  # wall clock time.time()
    diff: dict[str, Any]
    old_fingerprint: str
    new_fingerprint: str
    table_count: int


class SchemaCache:
    """Thread-safe in-memory schema cache, org-scoped via contextvar.

    All public methods resolve org_id internally via require_org_id().
    Cache keys use the composite format "{org_id}::{connection_name}" so two
    orgs with the same connection name cannot see each other's cached schemas.

    Usage:
        # Set current_org_id_var before any call (Store.__init__ or explicit set).
        schema = cache.get("my-conn")
        if schema is None:
            schema = await connector.get_schema()
            cache.put("my-conn", schema)

        # Force refresh
        cache.invalidate("my-conn")
    """

    # Max diff events to keep per connection
    _MAX_DIFF_HISTORY = 20

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self._ttl = ttl_seconds
        self._cache: dict[str, _CachedSchema] = {}
        self._sample_cache: dict[str, _CachedSchema] = {}
        self._diff_history: dict[str, deque[SchemaDiffEvent]] = {}
        self._lock = Lock()

    def _schema_key(self, org_id: str, connection_name: str) -> str:
        return f"{org_id}::{connection_name}"

    def _sample_key(self, org_id: str, connection_name: str, table: str) -> str:
        return f"{org_id}::{connection_name}::{table}"

    def get(self, connection_name: str) -> dict[str, Any] | None:
        """Get cached schema for a connection. Returns None on miss or expiration."""
        org_id = require_org_id()
        key = self._schema_key(org_id, connection_name)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.is_expired:
                del self._cache[key]
                return None
            return entry.data

    def put(self, connection_name: str, schema: dict[str, Any], track_diff: bool = False) -> dict[str, Any] | None:
        """Cache schema data for a connection.

        Automatically normalizes schema structure (fills missing defaults)
        so downstream consumers get consistent fields regardless of DB type.

        Args:
            connection_name: Connection identifier.
            schema: Schema data dict.
            track_diff: If True and a previous schema exists, compute and store diff event.

        Returns:
            Diff dict if track_diff=True and changes were detected, else None.
        """
        org_id = require_org_id()
        key = self._schema_key(org_id, connection_name)
        diff_key = self._schema_key(org_id, connection_name)

        # Normalize: ensure consistent baseline fields across all connector types
        _normalize_schema(schema)
        new_fp = _schema_fingerprint(schema)
        diff_result = None
        with self._lock:
            old_entry = self._cache.get(key)
            if track_diff and old_entry is not None:
                old_fp = old_entry.fingerprint
                if old_fp and old_fp != new_fp:
                    # Structural change detected — compute detailed diff
                    diff_result = _compute_schema_diff(old_entry.data, schema)
                    if diff_result.get("has_changes"):
                        event = SchemaDiffEvent(
                            connection_name=connection_name,
                            timestamp=time.time(),
                            diff=diff_result,
                            old_fingerprint=old_fp,
                            new_fingerprint=new_fp,
                            table_count=len(schema),
                        )
                        if diff_key not in self._diff_history:
                            self._diff_history[diff_key] = deque(maxlen=self._MAX_DIFF_HISTORY)
                        self._diff_history[diff_key].append(event)
            self._cache[key] = _CachedSchema(
                data=schema,
                cached_at=time.monotonic(),
                ttl_seconds=self._ttl,
                fingerprint=new_fp,
            )
        return diff_result

    def diff(self, connection_name: str, new_schema: dict[str, Any]) -> dict[str, Any] | None:
        """Compare cached schema with new schema and return differences.

        Returns None if no cached schema exists.
        Returns a dict with added/removed/modified tables and columns.
        """
        org_id = require_org_id()
        key = self._schema_key(org_id, connection_name)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            old_schema = entry.data

        return _compute_schema_diff(old_schema, new_schema)

    def invalidate(self, connection_name: str | None = None, all_orgs: bool = False) -> int:
        """Invalidate cached schema.

        Args:
            connection_name: If given, only invalidate entries for this connection.
                             If None, invalidate all entries in scope.
            all_orgs: If True, invalidate across all orgs (admin callers).
                      If False (default), restrict to the current org.

        Returns number of entries invalidated.
        """
        if all_orgs:
            with self._lock:
                if connection_name is None:
                    count = len(self._cache)
                    self._cache.clear()
                    return count
                prefix = f"::{connection_name}"
                keys_to_remove = [k for k in self._cache if k.endswith(prefix)]
                for k in keys_to_remove:
                    del self._cache[k]
                return len(keys_to_remove)

        org_id = require_org_id()
        with self._lock:
            if connection_name is not None:
                key = self._schema_key(org_id, connection_name)
                if key in self._cache:
                    del self._cache[key]
                    return 1
                return 0
            # Invalidate all entries for this org
            org_prefix = f"{org_id}::"
            keys_to_remove = [k for k in self._cache if k.startswith(org_prefix)]
            for k in keys_to_remove:
                del self._cache[k]
            return len(keys_to_remove)

    # ─── Sample values cache ────────────────────────────────────────────
    def get_sample_values(self, connection_name: str, table: str) -> dict[str, list] | None:
        """Get cached sample values for a table. Returns None on miss."""
        org_id = require_org_id()
        key = self._sample_key(org_id, connection_name, table)
        with self._lock:
            entry = self._sample_cache.get(key)
            if entry is None:
                return None
            if entry.is_expired:
                del self._sample_cache[key]
                return None
            return entry.data

    def put_sample_values(self, connection_name: str, table: str, values: dict[str, list]) -> None:
        """Cache sample values for a table."""
        org_id = require_org_id()
        key = self._sample_key(org_id, connection_name, table)
        with self._lock:
            self._sample_cache[key] = _CachedSchema(
                data=values,
                cached_at=time.monotonic(),
                ttl_seconds=self._ttl * 2,  # Sample values expire slower
            )

    def get_fingerprint(self, connection_name: str) -> str | None:
        """Get the structural fingerprint of the cached schema. None if not cached."""
        org_id = require_org_id()
        key = self._schema_key(org_id, connection_name)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None or entry.is_expired:
                return None
            return entry.fingerprint

    def has_structural_change(self, connection_name: str, new_schema: dict[str, Any]) -> bool:
        """Fast check: has the schema structure changed since last cache?

        Uses fingerprint comparison — O(n) hash, no deep diff.
        Returns True if changed or if no cached schema exists.
        """
        org_id = require_org_id()
        key = self._schema_key(org_id, connection_name)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None or not entry.fingerprint:
                return True
            new_fp = _schema_fingerprint(new_schema)
            return entry.fingerprint != new_fp

    def get_diff_history(self, connection_name: str | None = None) -> list[dict[str, Any]]:
        """Get schema change history for the current org.

        Args:
            connection_name: If provided, get history for one connection.
                           If None, get all recent changes for the current org.

        Returns:
            List of diff events (newest first).
        """
        org_id = require_org_id()
        with self._lock:
            if connection_name is not None:
                key = self._schema_key(org_id, connection_name)
                events = list(self._diff_history.get(key, []))
            else:
                org_prefix = f"{org_id}::"
                events = []
                for diff_key, conn_events in self._diff_history.items():
                    if diff_key.startswith(org_prefix):
                        events.extend(conn_events)
            # Sort newest first
            events.sort(key=lambda e: e.timestamp, reverse=True)
            return [
                {
                    "connection_name": e.connection_name,
                    "timestamp": e.timestamp,
                    "diff": e.diff,
                    "old_fingerprint": e.old_fingerprint,
                    "new_fingerprint": e.new_fingerprint,
                    "table_count": e.table_count,
                }
                for e in events[:50]
            ]

    def stats(self, all_orgs: bool = False) -> dict[str, Any]:
        """Return cache statistics and purge expired entries.

        Args:
            all_orgs: If True, return global counts.
                      If False (default), return counts for the current org only.
        """
        with self._lock:
            # Lazy purge expired entries on stats() call
            expired_keys = [k for k, e in self._cache.items() if e.is_expired]
            for k in expired_keys:
                del self._cache[k]
            expired_samples = [k for k, e in self._sample_cache.items() if e.is_expired]
            for k in expired_samples:
                del self._sample_cache[k]

            if all_orgs:
                cached_connections = len(self._cache)
                cached_sample_tables = len(self._sample_cache)
                fingerprints = {
                    name: entry.fingerprint
                    for name, entry in self._cache.items()
                    if entry.fingerprint
                }
            else:
                org_id = require_org_id()
                org_prefix = f"{org_id}::"
                cached_connections = sum(1 for k in self._cache if k.startswith(org_prefix))
                cached_sample_tables = sum(1 for k in self._sample_cache if k.startswith(org_prefix))
                fingerprints = {
                    name: entry.fingerprint
                    for name, entry in self._cache.items()
                    if name.startswith(org_prefix) and entry.fingerprint
                }

            total_diff_events = sum(len(q) for q in self._diff_history.values())
            return {
                "cached_connections": cached_connections,
                "total_entries": cached_connections,
                "cached_sample_tables": cached_sample_tables,
                "purged": len(expired_keys) + len(expired_samples),
                "ttl_seconds": self._ttl,
                "fingerprints": fingerprints,
                "diff_events_total": total_diff_events,
            }


def _compute_schema_diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Compute differences between two schema snapshots."""
    old_tables = set(old.keys())
    new_tables = set(new.keys())

    added_tables = sorted(new_tables - old_tables)
    removed_tables = sorted(old_tables - new_tables)

    modified_tables: list[dict[str, Any]] = []
    for table_key in sorted(old_tables & new_tables):
        old_t = old[table_key]
        new_t = new[table_key]

        old_cols = {c["name"]: c for c in old_t.get("columns", [])}
        new_cols = {c["name"]: c for c in new_t.get("columns", [])}

        added_cols = sorted(set(new_cols.keys()) - set(old_cols.keys()))
        removed_cols = sorted(set(old_cols.keys()) - set(new_cols.keys()))

        # Check for type changes
        type_changes = []
        for col_name in sorted(set(old_cols.keys()) & set(new_cols.keys())):
            old_type = old_cols[col_name].get("type", "")
            new_type = new_cols[col_name].get("type", "")
            if old_type != new_type:
                type_changes.append({
                    "column": col_name,
                    "old_type": old_type,
                    "new_type": new_type,
                })

        if added_cols or removed_cols or type_changes:
            change: dict[str, Any] = {"table": table_key}
            if added_cols:
                change["added_columns"] = added_cols
            if removed_cols:
                change["removed_columns"] = removed_cols
            if type_changes:
                change["type_changes"] = type_changes
            modified_tables.append(change)

    has_changes = bool(added_tables or removed_tables or modified_tables)
    return {
        "has_changes": has_changes,
        "added_tables": added_tables,
        "removed_tables": removed_tables,
        "modified_tables": modified_tables,
    }


# Global singleton
schema_cache = SchemaCache()
