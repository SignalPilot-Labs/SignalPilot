"""PostgreSQL connector — asyncpg-backed."""

from __future__ import annotations

from typing import Any

from .base import BaseConnector

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False


class PostgresConnector(BaseConnector):
    def __init__(self):
        self._pool = None

    async def connect(self, connection_string: str) -> None:
        if not HAS_ASYNCPG:
            raise RuntimeError("asyncpg not installed. Run: pip install asyncpg")
        self._pool = await asyncpg.create_pool(connection_string, min_size=1, max_size=5)

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._pool is None:
            raise RuntimeError("Not connected")
        async with self._pool.acquire(timeout=10) as conn:
            # Set statement timeout on the DB side (Feature #8)
            # This cancels the query on the server, not just the client
            if timeout:
                timeout_ms = max(1, min(int(timeout), 300)) * 1000
                await conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
            # Wrap in read-only transaction (defense in depth)
            async with conn.transaction(readonly=True):
                rows = await conn.fetch(sql, *(params or []), timeout=timeout)
                return [dict(r) for r in rows]

    async def get_schema(self) -> dict[str, Any]:
        if self._pool is None:
            raise RuntimeError("Not connected")
        sql = """
            SELECT
                t.table_schema,
                t.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_primary_key
            FROM information_schema.tables t
            JOIN information_schema.columns c
                ON t.table_schema = c.table_schema
                AND t.table_name = c.table_name
            LEFT JOIN (
                SELECT kcu.table_schema, kcu.table_name, kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
            ) pk
                ON c.table_schema = pk.table_schema
                AND c.table_name = pk.table_name
                AND c.column_name = pk.column_name
            WHERE t.table_schema NOT IN ('pg_catalog', 'information_schema')
                AND t.table_type = 'BASE TABLE'
            ORDER BY t.table_schema, t.table_name, c.ordinal_position
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql)

        schema: dict[str, Any] = {}
        for row in rows:
            key = f"{row['table_schema']}.{row['table_name']}"
            if key not in schema:
                schema[key] = {
                    "schema": row["table_schema"],
                    "name": row["table_name"],
                    "columns": [],
                }
            schema[key]["columns"].append({
                "name": row["column_name"],
                "type": row["data_type"],
                "nullable": row["is_nullable"] == "YES",
                "primary_key": row["is_primary_key"],
            })
        return schema

    async def health_check(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None
