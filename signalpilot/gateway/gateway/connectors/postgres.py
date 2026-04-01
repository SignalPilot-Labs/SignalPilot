"""PostgreSQL connector — asyncpg-backed with connection pooling and rich diagnostics."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .base import BaseConnector, ConnectionTestResult

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False


class PostgresConnector(BaseConnector):
    """Async PostgreSQL connector using asyncpg with connection pooling."""

    CONNECT_TIMEOUT = 10.0
    QUERY_TIMEOUT = 30.0

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    async def connect(
        self,
        connection_string: str,
        *,
        connect_timeout: float | None = None,
        ssl: bool = False,
    ) -> None:
        if not HAS_ASYNCPG:
            raise RuntimeError("asyncpg not installed. Run: pip install asyncpg")

        timeout = connect_timeout or self.CONNECT_TIMEOUT

        # Build SSL context if requested
        ssl_ctx: Any = "prefer" if ssl else False

        self._pool = await asyncio.wait_for(
            asyncpg.create_pool(
                connection_string,
                min_size=1,
                max_size=5,
                command_timeout=self.QUERY_TIMEOUT,
                ssl=ssl_ctx,
            ),
            timeout=timeout,
        )

    async def execute(
        self,
        sql: str,
        params: list | None = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")

        query_timeout = timeout or self.QUERY_TIMEOUT

        async with self._pool.acquire() as conn:
            async with conn.transaction(readonly=True):
                rows = await asyncio.wait_for(
                    conn.fetch(sql, *(params or [])),
                    timeout=query_timeout,
                )
                return [dict(r) for r in rows]

    async def get_schema(self) -> dict[str, Any]:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")

        sql = """
            SELECT
                t.table_schema,
                t.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                c.character_maximum_length,
                (
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                            ON tc.constraint_name = kcu.constraint_name
                        WHERE tc.table_schema = t.table_schema
                            AND tc.table_name = t.table_name
                            AND kcu.column_name = c.column_name
                            AND tc.constraint_type = 'PRIMARY KEY'
                    )
                ) AS is_primary_key
            FROM information_schema.tables t
            JOIN information_schema.columns c
                ON t.table_schema = c.table_schema
                AND t.table_name = c.table_name
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
            col_info: dict[str, Any] = {
                "name": row["column_name"],
                "type": row["data_type"],
                "nullable": row["is_nullable"] == "YES",
                "primary_key": row["is_primary_key"],
            }
            if row["character_maximum_length"]:
                col_info["max_length"] = row["character_maximum_length"]
            schema[key]["columns"].append(col_info)
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

    async def test_connection(self) -> ConnectionTestResult:
        """Comprehensive connection test with rich PostgreSQL diagnostics."""
        if self._pool is None:
            return ConnectionTestResult(
                healthy=False,
                message="Not connected",
                error_code="NOT_CONNECTED",
                error_hint="Call connect() before testing.",
            )

        start = time.monotonic()
        try:
            async with self._pool.acquire() as conn:
                # Basic connectivity
                await conn.fetchval("SELECT 1")
                latency = (time.monotonic() - start) * 1000

                # Server version
                version = await conn.fetchval("SELECT version()")

                # Current database
                db_name = await conn.fetchval("SELECT current_database()")

                # Table count
                table_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                        AND table_type = 'BASE TABLE'
                """)

                # Schema preview (first 10 tables with column counts)
                schema_rows = await conn.fetch("""
                    SELECT
                        t.table_schema,
                        t.table_name,
                        COUNT(c.column_name) AS column_count,
                        pg_size_pretty(
                            pg_total_relation_size(
                                quote_ident(t.table_schema) || '.' || quote_ident(t.table_name)
                            )
                        ) AS table_size
                    FROM information_schema.tables t
                    LEFT JOIN information_schema.columns c
                        ON t.table_schema = c.table_schema AND t.table_name = c.table_name
                    WHERE t.table_schema NOT IN ('pg_catalog', 'information_schema')
                        AND t.table_type = 'BASE TABLE'
                    GROUP BY t.table_schema, t.table_name
                    ORDER BY t.table_schema, t.table_name
                    LIMIT 10
                """)
                schema_preview = [
                    {
                        "schema": r["table_schema"],
                        "table": r["table_name"],
                        "columns": r["column_count"],
                        "size": r["table_size"],
                    }
                    for r in schema_rows
                ]

                # SSL status
                ssl_active = await conn.fetchval("""
                    SELECT CASE WHEN ssl THEN true ELSE false END
                    FROM pg_stat_ssl WHERE pid = pg_backend_pid()
                """)

                # Connection stats
                max_conn = await conn.fetchval("SHOW max_connections")
                current_conn = await conn.fetchval("""
                    SELECT COUNT(*) FROM pg_stat_activity
                """)

                # Server uptime
                uptime = await conn.fetchval("""
                    SELECT pg_postmaster_start_time()::text
                """)

                return ConnectionTestResult(
                    healthy=True,
                    message="Connection successful",
                    latency_ms=round(latency, 2),
                    server_version=version,
                    database_name=db_name,
                    table_count=table_count,
                    schema_preview=schema_preview,
                    ssl_active=bool(ssl_active),
                    max_connections=int(max_conn) if max_conn else None,
                    current_connections=current_conn,
                    server_uptime=uptime,
                )

        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            msg, hint = self.friendly_error(e)
            return ConnectionTestResult(
                healthy=False,
                message=msg,
                latency_ms=round(latency, 2),
                error_code=type(e).__name__,
                error_hint=hint,
            )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    @staticmethod
    def friendly_error(error: Exception) -> tuple[str, str | None]:
        msg = str(error)
        hint = None

        if "could not connect" in msg.lower() or "connection refused" in msg.lower():
            hint = "Check that PostgreSQL is running and the host/port are correct."
        elif "password authentication failed" in msg.lower():
            hint = "The username or password is incorrect."
        elif "no pg_hba.conf entry" in msg.lower():
            hint = "The server is not configured to accept connections from this host. Check pg_hba.conf."
        elif "does not exist" in msg.lower() and "database" in msg.lower():
            hint = "The database name is incorrect — double-check the database field."
        elif "does not exist" in msg.lower() and "role" in msg.lower():
            hint = "The username (role) does not exist on this server."
        elif "timeout" in msg.lower():
            hint = "Connection timed out. The server may be unreachable or behind a firewall."
        elif "ssl" in msg.lower():
            hint = "SSL connection issue. Try enabling or disabling the SSL toggle."
        elif "too many clients" in msg.lower():
            hint = "The server has reached its maximum connection limit. Try again later."

        return msg, hint
