"""Cache stats, PII detection, pool stats, and schema-cache endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..connectors.pool_manager import pool_manager
from ..connectors.schema_cache import schema_cache
from ..governance.cache import query_cache
from ..scope_guard import RequireScope
from .deps import StoreD, sanitize_db_error

router = APIRouter(prefix="/api")


@router.get("/cache/stats", dependencies=[RequireScope("read")])
async def cache_stats():
    """Get query cache statistics (Feature #30)."""
    return query_cache.stats()


@router.post("/cache/invalidate", status_code=200, dependencies=[RequireScope("write")])
async def invalidate_cache(connection_name: str | None = None):
    """Invalidate cached query results. Optionally filter by connection."""
    count = query_cache.invalidate(connection_name)
    return {"invalidated": count, "connection_name": connection_name}


@router.post("/connections/{name}/detect-pii", dependencies=[RequireScope("write")])
async def detect_pii(name: str, store: StoreD):
    """Auto-detect PII columns in a database schema based on naming patterns.

    Returns suggested PII rules for columns with names matching known
    PII patterns (email, ssn, phone, etc.). Results should be reviewed
    and saved to schema.yml annotations.
    """
    info = await store.get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    # Get schema (from cache if available)
    cached_schema = schema_cache.get(name)
    if cached_schema is None:
        try:
            extras = await store.get_credential_extras(name)
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                cached_schema = await connector.get_schema()
            schema_cache.put(name, cached_schema)
        except Exception as e:
            raise HTTPException(status_code=500, detail=sanitize_db_error(str(e)))

    from ..governance.pii import detect_pii_columns

    all_detections: dict[str, dict[str, str]] = {}
    for table_key, table_data in cached_schema.items():
        columns = [col["name"] for col in table_data.get("columns", [])]
        detected = detect_pii_columns(columns)
        if detected:
            all_detections[table_data.get("name", table_key)] = {
                col: rule.value for col, rule in detected.items()
            }

    return {
        "connection_name": name,
        "tables_scanned": len(cached_schema),
        "tables_with_pii": len(all_detections),
        "detections": all_detections,
    }


@router.get("/pool/stats", dependencies=[RequireScope("read")])
async def pool_stats():
    """Get connection pool statistics for monitoring."""
    return pool_manager.stats()


@router.get("/schema-cache/stats", dependencies=[RequireScope("read")])
async def schema_cache_stats():
    """Get schema cache statistics (Feature #18)."""
    return schema_cache.stats()


@router.post("/schema-cache/invalidate", status_code=200, dependencies=[RequireScope("write")])
async def invalidate_schema_cache(connection_name: str | None = None):
    """Invalidate cached schema data. Optionally filter by connection."""
    count = schema_cache.invalidate(connection_name)
    return {"invalidated": count, "connection_name": connection_name}
