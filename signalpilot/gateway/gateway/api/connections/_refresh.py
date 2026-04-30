from __future__ import annotations

import asyncio
import logging

from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache

logger = logging.getLogger(__name__)


async def _auto_schema_refresh(name: str, db_type: str, store):
    """Background task: fetch schema for newly created connections."""
    await asyncio.sleep(2)
    try:
        conn_str = await store.get_connection_string(name)
        if not conn_str:
            return
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(
            db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
            schema = await connector.get_schema()
            schema_cache.put(name, schema)
            logger.info("Auto-refreshed schema for new connection '%s': %d tables", name, len(schema))

            _cat_names = {
                "status",
                "state",
                "type",
                "category",
                "region",
                "country",
                "city",
                "role",
                "department",
                "channel",
                "source",
                "currency",
            }
            _str_types = {"varchar", "nvarchar", "text", "char", "character varying", "string"}
            for table_key, table_data in list(schema.items())[:20]:
                sample_cols = []
                for col in table_data.get("columns", []):
                    cn = col.get("name", "").lower()
                    ct = col.get("type", "").lower().split("(")[0]
                    stats = col.get("stats", {})
                    dc = stats.get("distinct_count", 0) if stats else 0
                    if (dc and dc <= 50) or (
                        ct in _str_types and (cn in _cat_names or cn.endswith(("_type", "_status")))
                    ):
                        sample_cols.append(col["name"])
                if sample_cols:
                    try:
                        values = await connector.get_sample_values(table_key, sample_cols[:10], limit=5)
                        if values:
                            schema_cache.put_sample_values(name, table_key, values)
                    except Exception:
                        pass
    except Exception as e:
        logger.warning("Auto-schema-refresh failed for '%s': %s", name, e)
