from __future__ import annotations

from typing import Any

from gateway.api.connections._router import router
from gateway.api.deps import StoreD
from gateway.connectors.health_monitor import health_monitor
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache
from gateway.security.scope_guard import RequireScope


@router.get("/connections/stats", dependencies=[RequireScope("read")])
async def get_connections_stats(store: StoreD):
    """Dashboard-level statistics for all connections."""
    connections = await store.list_connections()
    stats: list[dict] = []
    for conn in connections:
        conn_dict = conn.model_dump() if hasattr(conn, "model_dump") else dict(conn)
        name = conn_dict.get("name", "")
        db_type = conn_dict.get("db_type", "")
        entry: dict[str, Any] = {
            "name": name,
            "db_type": db_type,
            "description": conn_dict.get("description", ""),
            "tags": conn_dict.get("tags", []),
        }
        cached = schema_cache.get(name)
        if cached:
            entry["schema_tables"] = len(cached)
            entry["schema_columns"] = sum(len(t.get("columns", [])) for t in cached.values())
            entry["total_rows"] = sum(t.get("row_count", 0) or 0 for t in cached.values())
            total_mb = sum(t.get("size_mb", 0) or 0 for t in cached.values())
            if total_mb:
                entry["total_size_mb"] = round(total_mb, 2)
            entry["schema_cached"] = True
            fp = schema_cache.get_fingerprint(name)
            if fp:
                entry["schema_fingerprint"] = fp
        else:
            entry["schema_cached"] = False

        health = health_monitor.connection_stats(name, 300)
        if health:
            entry["health_status"] = health.get("status", "unknown")
            entry["latency_p50_ms"] = health.get("latency_p50_ms")
            entry["error_rate"] = health.get("error_rate", 0)
        else:
            entry["health_status"] = "unknown"

        pool_stats_data = pool_manager.stats()
        for p in pool_stats_data.get("pools", []):
            if name in p.get("key", ""):
                entry["pool_idle_seconds"] = p.get("idle_seconds", 0)
                break

        stats.append(entry)
    return {"connections": stats, "total": len(stats)}
