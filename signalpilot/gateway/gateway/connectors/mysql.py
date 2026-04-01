"""MySQL connector — aiomysql-backed with connection pooling and rich diagnostics."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .base import BaseConnector, ConnectionTestResult

try:
    import aiomysql
    HAS_AIOMYSQL = True
except ImportError:
    HAS_AIOMYSQL = False


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    """Parse a mysql://user:pass@host:port/database connection string."""
    from urllib.parse import urlparse

    parsed = urlparse(dsn)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": parsed.username or "root",
        "password": parsed.password or "",
        "db": (parsed.path or "/mysql").lstrip("/") or "mysql",
    }


class MySQLConnector(BaseConnector):
    """Async MySQL connector using aiomysql with connection pooling."""

    CONNECT_TIMEOUT = 10.0
    QUERY_TIMEOUT = 30.0

    def __init__(self) -> None:
        self._pool: aiomysql.Pool | None = None

    async def connect(
        self,
        connection_string: str,
        *,
        connect_timeout: float | None = None,
        ssl: bool = False,
    ) -> None:
        if not HAS_AIOMYSQL:
            raise RuntimeError(
                "aiomysql not installed. Run: pip install aiomysql"
            )

        timeout = connect_timeout or self.CONNECT_TIMEOUT
        params = _parse_mysql_dsn(connection_string)

        ssl_ctx: Any = None
        if ssl:
            import ssl as _ssl
            ssl_ctx = _ssl.create_default_context()

        self._pool = await asyncio.wait_for(
            aiomysql.create_pool(
                host=params["host"],
                port=params["port"],
                user=params["user"],
                password=params["password"],
                db=params["db"],
                minsize=1,
                maxsize=5,
                connect_timeout=int(timeout),
                ssl=ssl_ctx,
                autocommit=True,
            ),
            timeout=timeout + 2,
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

        async with self._pool.acquire() as conn:
            # Set read-only for defense in depth
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SET SESSION TRANSACTION READ ONLY")
                await cur.execute("START TRANSACTION")
                try:
                    await cur.execute(sql, params or ())
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]
                finally:
                    await cur.execute("ROLLBACK")

    async def get_schema(self) -> dict[str, Any]:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")

        sql = """
            SELECT
                t.TABLE_SCHEMA AS table_schema,
                t.TABLE_NAME AS table_name,
                c.COLUMN_NAME AS column_name,
                c.DATA_TYPE AS data_type,
                c.IS_NULLABLE AS is_nullable,
                c.COLUMN_DEFAULT AS column_default,
                c.CHARACTER_MAXIMUM_LENGTH AS max_length,
                c.COLUMN_KEY AS column_key
            FROM information_schema.TABLES t
            JOIN information_schema.COLUMNS c
                ON t.TABLE_SCHEMA = c.TABLE_SCHEMA
                AND t.TABLE_NAME = c.TABLE_NAME
            WHERE t.TABLE_SCHEMA = DATABASE()
                AND t.TABLE_TYPE = 'BASE TABLE'
            ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME, c.ORDINAL_POSITION
        """
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql)
                rows = await cur.fetchall()

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
                "primary_key": row["column_key"] == "PRI",
            }
            if row["max_length"]:
                col_info["max_length"] = row["max_length"]
            schema[key]["columns"].append(col_info)
        return schema

    async def health_check(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
                    await cur.fetchone()
            return True
        except Exception:
            return False

    async def test_connection(self) -> ConnectionTestResult:
        """Comprehensive connection test with rich MySQL diagnostics."""
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
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    # Basic connectivity
                    await cur.execute("SELECT 1")
                    await cur.fetchone()
                    latency = (time.monotonic() - start) * 1000

                    # Server version
                    await cur.execute("SELECT VERSION() AS version")
                    row = await cur.fetchone()
                    version = f"MySQL {row['version']}" if row else None

                    # Current database
                    await cur.execute("SELECT DATABASE() AS db")
                    row = await cur.fetchone()
                    db_name = row["db"] if row else None

                    # Table count
                    await cur.execute("""
                        SELECT COUNT(*) AS cnt FROM information_schema.TABLES
                        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
                    """)
                    row = await cur.fetchone()
                    table_count = row["cnt"] if row else 0

                    # Schema preview
                    await cur.execute("""
                        SELECT
                            t.TABLE_SCHEMA AS table_schema,
                            t.TABLE_NAME AS table_name,
                            COUNT(c.COLUMN_NAME) AS column_count,
                            CONCAT(
                                ROUND(t.DATA_LENGTH / 1024, 1), ' kB'
                            ) AS table_size
                        FROM information_schema.TABLES t
                        LEFT JOIN information_schema.COLUMNS c
                            ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
                        WHERE t.TABLE_SCHEMA = DATABASE()
                            AND t.TABLE_TYPE = 'BASE TABLE'
                        GROUP BY t.TABLE_SCHEMA, t.TABLE_NAME, t.DATA_LENGTH
                        ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME
                        LIMIT 10
                    """)
                    schema_rows = await cur.fetchall()
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
                    await cur.execute("SHOW STATUS LIKE 'Ssl_cipher'")
                    ssl_row = await cur.fetchone()
                    ssl_active = bool(ssl_row and ssl_row.get("Value"))

                    # Connection stats
                    await cur.execute("SHOW VARIABLES LIKE 'max_connections'")
                    max_row = await cur.fetchone()
                    max_conn = int(max_row["Value"]) if max_row else None

                    await cur.execute("SHOW STATUS LIKE 'Threads_connected'")
                    cur_row = await cur.fetchone()
                    current_conn = int(cur_row["Value"]) if cur_row else None

                    # Uptime
                    await cur.execute("SHOW STATUS LIKE 'Uptime'")
                    up_row = await cur.fetchone()
                    uptime = None
                    if up_row:
                        secs = int(up_row["Value"])
                        days, rem = divmod(secs, 86400)
                        hours, rem = divmod(rem, 3600)
                        mins, _ = divmod(rem, 60)
                        uptime = f"{days}d {hours}h {mins}m"

                    return ConnectionTestResult(
                        healthy=True,
                        message="Connection successful",
                        latency_ms=round(latency, 2),
                        server_version=version,
                        database_name=db_name,
                        table_count=table_count,
                        schema_preview=schema_preview,
                        ssl_active=ssl_active,
                        max_connections=max_conn,
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
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None

    @staticmethod
    def friendly_error(error: Exception) -> tuple[str, str | None]:
        msg = str(error)
        hint = None

        if "can't connect" in msg.lower() or "connection refused" in msg.lower():
            hint = "Check that MySQL is running and the host/port are correct."
        elif "access denied" in msg.lower():
            hint = "The username or password is incorrect."
        elif "unknown database" in msg.lower():
            hint = "The database name is incorrect — double-check the database field."
        elif "timeout" in msg.lower():
            hint = "Connection timed out. The server may be unreachable or behind a firewall."
        elif "ssl" in msg.lower():
            hint = "SSL connection issue. Try enabling or disabling the SSL toggle."
        elif "too many connections" in msg.lower():
            hint = "The server has reached its maximum connection limit. Try again later."

        return msg, hint
