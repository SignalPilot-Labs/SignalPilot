from __future__ import annotations

import asyncio
import time

from fastapi import HTTPException

from gateway.api.connections._router import router
from gateway.api.deps import StoreD, sanitize_db_error
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache
from gateway.models import ConnectionUpdate
from gateway.scope_guard import RequireScope


@router.post("/connections/{name}/schema/refresh", dependencies=[RequireScope("write")])
async def refresh_connection_schema(name: str, store: StoreD):
    """Force-refresh the cached schema for a connection."""
    info = await store.get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    schema_cache.invalidate(name)

    try:
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
            schema = await connector.get_schema()
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e)))

    schema_cache.put(name, schema)
    now = time.time()
    await store.update_connection(name, ConnectionUpdate(last_schema_refresh=now))

    return {
        "connection_name": name,
        "table_count": len(schema),
        "refreshed_at": now,
        "next_refresh_in": info.schema_refresh_interval,
        "message": "Schema refreshed successfully",
    }


@router.post("/connections/schema/warmup", dependencies=[RequireScope("write")])
async def warmup_all_schemas(store: StoreD):
    """Parallel schema warmup for all connections."""

    connections = await store.list_connections()
    if not connections:
        return {"warmed": 0, "results": [], "duration_ms": 0}

    start = time.monotonic()

    async def _warmup_one(info) -> dict:
        name = info.name
        cached = schema_cache.get(name)
        if cached is not None:
            return {"name": name, "status": "cached", "table_count": len(cached)}
        conn_str = await store.get_connection_string(name)
        if not conn_str:
            return {"name": name, "status": "skipped", "error": "no credentials"}
        try:
            extras = await store.get_credential_extras(name)
            async with pool_manager.connection(
                info.db_type, conn_str, credential_extras=extras, connection_name=name
            ) as connector:
                schema = await connector.get_schema()
                schema_cache.put(name, schema)

                _categorical_patterns = {
                    "status",
                    "state",
                    "type",
                    "category",
                    "region",
                    "country",
                    "city",
                    "gender",
                    "role",
                    "department",
                    "dept",
                    "tier",
                    "priority",
                    "severity",
                    "channel",
                    "source",
                    "currency",
                    "payment_method",
                    "payment_type",
                    "order_status",
                    "plan",
                    "segment",
                    "class",
                    "grade",
                    "level",
                    "phase",
                }
                _string_types = {
                    "varchar",
                    "nvarchar",
                    "text",
                    "char",
                    "nchar",
                    "character varying",
                    "enum",
                    "string",
                    "String",
                }
                sample_count = 0
                for table_key, table_data in list(schema.items())[:30]:
                    if schema_cache.get_sample_values(name, table_key) is not None:
                        continue
                    low_card_cols = []
                    for col in table_data.get("columns", []):
                        col_name = col.get("name", "")
                        col_type = col.get("type", "").lower().split("(")[0]
                        stats = col.get("stats", {})
                        dc = stats.get("distinct_count", 0) if stats else 0
                        df = abs(stats.get("distinct_fraction", 0)) if stats else 0
                        if dc and dc <= 50:
                            low_card_cols.append(col_name)
                        elif df and df < 0.05:
                            low_card_cols.append(col_name)
                        elif not stats and col_type in _string_types:
                            col_lower = col_name.lower()
                            if (
                                col_lower in _categorical_patterns
                                or col_lower.endswith("_type")
                                or col_lower.endswith("_status")
                            ):
                                low_card_cols.append(col_name)
                    if low_card_cols:
                        try:
                            samples = await connector.get_sample_values(table_key, low_card_cols[:10], limit=5)
                            if samples:
                                schema_cache.put_sample_values(name, table_key, samples)
                                sample_count += len(samples)
                        except Exception:
                            pass

            now = time.time()
            await store.update_connection(name, ConnectionUpdate(last_schema_refresh=now))
            return {"name": name, "status": "ok", "table_count": len(schema), "sample_columns": sample_count}
        except Exception as e:
            return {"name": name, "status": "error", "error": sanitize_db_error(str(e))[:200]}

    results = await asyncio.gather(*[_warmup_one(c) for c in connections], return_exceptions=False)
    elapsed = (time.monotonic() - start) * 1000

    ok_count = sum(1 for r in results if r["status"] in ("ok", "cached"))
    total_tables = sum(r.get("table_count", 0) for r in results)
    return {
        "warmed": ok_count,
        "total_connections": len(connections),
        "total_tables": total_tables,
        "results": results,
        "duration_ms": round(elapsed, 1),
    }
