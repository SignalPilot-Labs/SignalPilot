"""Cache stats, PII detection, pool stats, and schema-cache endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..auth import UserID
from ..connectors.pool_manager import pool_manager
from ..connectors.schema_cache import schema_cache
from ..governance.cache import query_cache
from ..scope_guard import RequireScope
from .deps import StoreD, sanitize_db_error  # noqa: F401 — StoreD used for org context

router = APIRouter(prefix="/api")


@router.get("/cache/stats", dependencies=[RequireScope("read")])
async def cache_stats(_: UserID, store: StoreD):
    """Get query cache statistics (Feature #30)."""
    return query_cache.stats(all_orgs=False)


@router.post("/cache/invalidate", status_code=200, dependencies=[RequireScope("write")])
async def invalidate_cache(_: UserID, store: StoreD, connection_name: str | None = None):
    """Invalidate cached query results. Optionally filter by connection."""
    count = query_cache.invalidate(connection_name, all_orgs=False)
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
            async with pool_manager.connection(
                info.db_type, conn_str, credential_extras=extras, connection_name=name
            ) as connector:
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
            all_detections[table_data.get("name", table_key)] = {col: rule.value for col, rule in detected.items()}

    return {
        "connection_name": name,
        "tables_scanned": len(cached_schema),
        "tables_with_pii": len(all_detections),
        "detections": all_detections,
    }


@router.get("/connections/{name}/pii", dependencies=[RequireScope("read")])
async def get_pii_config(name: str, store: StoreD):
    """Get PII redaction config for a connection."""
    return await store.get_pii_config(name)


@router.put("/connections/{name}/pii", dependencies=[RequireScope("write")])
async def set_pii_config(name: str, store: StoreD, body: dict):
    """Set PII redaction config for a connection.

    Body: {"enabled": true/false, "rules": {"column_name": "hash|mask|drop", ...}}
    Toggle enabled to activate/deactivate redaction at query time.
    """
    enabled = body.get("enabled", False)
    rules = body.get("rules", {})
    # Validate rule values
    valid_rules = {"hash", "mask", "hide"}
    for col, rule in rules.items():
        if rule not in valid_rules:
            raise HTTPException(
                status_code=422, detail=f"Invalid PII rule '{rule}' for column '{col}'. Must be hash, mask, or drop."
            )
    return await store.set_pii_config(name, enabled, rules)


@router.post("/connections/{name}/detect-and-save-pii", dependencies=[RequireScope("write")])
async def detect_and_save_pii(name: str, store: StoreD):
    """Auto-detect PII columns and save rules to the connection config.

    Detects PII by column naming patterns, saves the rules, and enables
    PII redaction on the connection. Returns the saved config.
    """
    # Run detection
    info = await store.get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    cached_schema = schema_cache.get(name)
    if cached_schema is None:
        try:
            extras = await store.get_credential_extras(name)
            async with pool_manager.connection(
                info.db_type, conn_str, credential_extras=extras, connection_name=name
            ) as connector:
                cached_schema = await connector.get_schema()
            schema_cache.put(name, cached_schema)
        except Exception as e:
            raise HTTPException(status_code=500, detail=sanitize_db_error(str(e)))

    from ..governance.pii import detect_pii_columns

    # Flatten all detections into a single column→rule map
    all_rules: dict[str, str] = {}
    for table_data in cached_schema.values():
        columns = [col["name"] for col in table_data.get("columns", [])]
        detected = detect_pii_columns(columns)
        for col, rule in detected.items():
            all_rules[col] = rule.value

    # Save and enable
    result = await store.set_pii_config(name, enabled=True, rules=all_rules)
    return {
        "connection_name": name,
        "columns_flagged": len(all_rules),
        "rules": all_rules,
        "enabled": True,
    }


@router.get("/pool/stats", dependencies=[RequireScope("read")])
async def pool_stats(_: UserID):
    """Get connection pool statistics for monitoring."""
    return pool_manager.stats()


@router.get("/schema-cache/stats", dependencies=[RequireScope("read")])
async def schema_cache_stats(_: UserID, store: StoreD):
    """Get schema cache statistics (Feature #18)."""
    return schema_cache.stats(all_orgs=False)


@router.post("/schema-cache/invalidate", status_code=200, dependencies=[RequireScope("write")])
async def invalidate_schema_cache(_: UserID, store: StoreD, connection_name: str | None = None):
    """Invalidate cached schema data. Optionally filter by connection."""
    count = schema_cache.invalidate(connection_name, all_orgs=False)
    return {"invalidated": count, "connection_name": connection_name}
