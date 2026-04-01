"""DuckDB connector — zero-config local analytics engine.

Supports local file databases and MotherDuck cloud connections.
Feature #9 from the feature table — P0 for demos and local dev.
"""

from __future__ import annotations

from typing import Any

from .base import BaseConnector

try:
    import duckdb

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


class DuckDBConnector(BaseConnector):
    def __init__(self):
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._db_path: str = ""

    async def connect(self, connection_string: str) -> None:
        if not HAS_DUCKDB:
            raise RuntimeError("duckdb not installed. Run: pip install duckdb")
        # connection_string is a file path, :memory:, or a MotherDuck URL (md:)
        self._db_path = connection_string
        self._conn = duckdb.connect(connection_string, read_only=True)

    async def execute(self, sql: str, params: list | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            if params:
                result = self._conn.execute(sql, params)
            else:
                result = self._conn.execute(sql)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return [{col: val for col, val in zip(columns, row)} for row in rows]
        except duckdb.Error as e:
            raise RuntimeError(f"DuckDB query error: {e}") from e

    async def get_schema(self) -> dict[str, Any]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        # Get all tables from all schemas
        tables_result = self._conn.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema')"
        )
        tables = tables_result.fetchall()

        schema: dict[str, Any] = {}
        for table_schema, table_name in tables:
            key = f"{table_schema}.{table_name}"
            # Get columns for this table
            cols_result = self._conn.execute(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = ? AND table_name = ? "
                "ORDER BY ordinal_position",
                [table_schema, table_name],
            )
            columns = []
            for col_name, data_type, is_nullable in cols_result.fetchall():
                columns.append({
                    "name": col_name,
                    "type": data_type,
                    "nullable": is_nullable == "YES",
                })
            schema[key] = {
                "schema": table_schema,
                "name": table_name,
                "columns": columns,
            }
        return schema

    async def health_check(self) -> bool:
        if self._conn is None:
            return False
        try:
            self._conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
