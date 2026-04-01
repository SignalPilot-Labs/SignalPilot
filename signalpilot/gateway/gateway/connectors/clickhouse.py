"""ClickHouse connector — clickhouse-driver (native TCP protocol) backed.

Supports ClickHouse Cloud, on-premise, and self-hosted instances.
Uses the native TCP protocol for best performance.
"""

from __future__ import annotations

from typing import Any

from .base import BaseConnector

try:
    from clickhouse_driver import Client as CHClient

    HAS_CLICKHOUSE = True
except ImportError:
    HAS_CLICKHOUSE = False


class ClickHouseConnector(BaseConnector):
    def __init__(self):
        self._client: CHClient | None = None
        self._database: str = "default"

    async def connect(self, connection_string: str) -> None:
        if not HAS_CLICKHOUSE:
            raise RuntimeError(
                "clickhouse-driver not installed. "
                "Run: pip install clickhouse-driver"
            )
        params = self._parse_connection_string(connection_string)
        self._database = params.get("database", "default")

        connect_args = {
            "host": params.get("host", "localhost"),
            "port": int(params.get("port", 9000)),
            "user": params.get("user", "default"),
            "password": params.get("password", ""),
            "database": self._database,
            "connect_timeout": 10,
            "send_receive_timeout": 30,
        }

        # SSL support
        if params.get("secure"):
            connect_args["secure"] = True
            connect_args["verify"] = True

        self._client = CHClient(**connect_args)

    def _parse_connection_string(self, conn_str: str) -> dict:
        """Parse clickhouse://user:pass@host:port/db or clickhouses://... format."""
        from urllib.parse import urlparse, unquote

        secure = False
        s = conn_str
        if s.startswith("clickhouses://"):
            secure = True
            s = "clickhouse://" + s[len("clickhouses://"):]
        elif not s.startswith("clickhouse://"):
            s = "clickhouse://" + s

        parsed = urlparse(s)
        result = {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or (9440 if secure else 9000),
            "user": unquote(parsed.username or "default"),
            "password": unquote(parsed.password or ""),
            "database": parsed.path.lstrip("/") or "default",
        }
        if secure:
            result["secure"] = True
        return result

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._client is None:
            raise RuntimeError("Not connected")
        try:
            settings = {}
            if timeout:
                settings["max_execution_time"] = timeout

            # clickhouse-driver treats empty tuple params as INSERT mode
            # Only pass params when we actually have them
            execute_args = {"with_column_types": True, "settings": settings}
            if params:
                result = self._client.execute(sql, params, **execute_args)
            else:
                result = self._client.execute(sql, **execute_args)
            if isinstance(result, tuple) and len(result) == 2:
                rows_data, columns_info = result
                col_names = [c[0] for c in columns_info]
                return [dict(zip(col_names, row)) for row in rows_data]
            return []
        except Exception as e:
            raise RuntimeError(f"ClickHouse query error: {e}") from e

    async def get_schema(self) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("Not connected")

        # ClickHouse uses system tables for metadata
        sql = """
            SELECT
                database,
                table,
                name AS column_name,
                type AS data_type,
                default_kind,
                comment,
                is_in_primary_key
            FROM system.columns
            WHERE database NOT IN ('system', 'INFORMATION_SCHEMA', 'information_schema')
            ORDER BY database, table, position
        """
        result = self._client.execute(sql, with_column_types=True)
        rows_data, columns_info = result
        col_names = [c[0] for c in columns_info]

        # Table engine and sorting key info (critical for ClickHouse query optimization)
        table_meta_sql = """
            SELECT
                database, name AS table_name,
                engine, sorting_key, primary_key,
                total_rows, total_bytes
            FROM system.tables
            WHERE database NOT IN ('system', 'INFORMATION_SCHEMA', 'information_schema')
        """
        table_meta: dict[str, dict] = {}
        try:
            meta_result = self._client.execute(table_meta_sql, with_column_types=True)
            meta_rows, meta_cols = meta_result
            meta_col_names = [c[0] for c in meta_cols]
            for r in meta_rows:
                rd = dict(zip(meta_col_names, r))
                key = f"{rd['database']}.{rd['table_name']}"
                table_meta[key] = {
                    "engine": rd.get("engine", ""),
                    "sorting_key": rd.get("sorting_key", ""),
                    "primary_key": rd.get("primary_key", ""),
                    "row_count": rd.get("total_rows", 0),
                    "total_bytes": rd.get("total_bytes", 0),
                }
        except Exception:
            pass

        schema: dict[str, Any] = {}
        for row_vals in rows_data:
            row = dict(zip(col_names, row_vals))
            key = f"{row['database']}.{row['table']}"
            if key not in schema:
                meta = table_meta.get(key, {})
                schema[key] = {
                    "schema": row["database"],
                    "name": row["table"],
                    "columns": [],
                    "engine": meta.get("engine", ""),
                    "sorting_key": meta.get("sorting_key", ""),
                    "row_count": meta.get("row_count", 0),
                    "total_bytes": meta.get("total_bytes", 0),
                }
            # ClickHouse Nullable types contain 'Nullable(' wrapper
            data_type = row["data_type"]
            nullable = "Nullable" in data_type
            if nullable:
                data_type = data_type.replace("Nullable(", "").rstrip(")")

            schema[key]["columns"].append({
                "name": row["column_name"],
                "type": data_type,
                "nullable": nullable,
                "primary_key": bool(row.get("is_in_primary_key", 0)),
                "comment": row.get("comment", ""),
            })
        return schema

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values for schema linking optimization."""
        if self._client is None:
            return {}
        result: dict[str, list] = {}
        for col in columns[:20]:
            try:
                rows = self._client.execute(
                    f'SELECT DISTINCT `{col}` FROM {table} WHERE `{col}` IS NOT NULL LIMIT {limit}'
                )
                values = [str(row[0]) for row in rows]
                if values:
                    result[col] = values
            except Exception:
                continue
        return result

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            self._client.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._client:
            self._client.disconnect()
            self._client = None
