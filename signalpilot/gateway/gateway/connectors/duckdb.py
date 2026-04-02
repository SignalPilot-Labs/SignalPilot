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
        # In-memory and MotherDuck databases cannot be opened in read_only mode
        is_memory = connection_string == ":memory:" or connection_string.startswith("md:")
        self._conn = duckdb.connect(connection_string, read_only=not is_memory)

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            # DuckDB supports PRAGMA to limit execution time (seconds)
            if timeout:
                self._conn.execute(f"SET timeout = '{timeout}s'")
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

        # Single optimized query for all columns across all tables
        cols_sql = """
            SELECT
                c.table_schema, c.table_name, c.column_name,
                c.data_type, c.is_nullable, c.column_default
            FROM information_schema.columns c
            JOIN information_schema.tables t
                ON c.table_schema = t.table_schema AND c.table_name = t.table_name
            WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
                AND t.table_type = 'BASE TABLE'
            ORDER BY c.table_schema, c.table_name, c.ordinal_position
        """
        cols_result = self._conn.execute(cols_sql)
        all_cols = cols_result.fetchall()

        # Foreign keys (DuckDB supports them for constraint metadata)
        fk_sql = """
            SELECT
                tc.table_schema, tc.table_name,
                kcu.column_name,
                ccu.table_schema AS foreign_table_schema,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
        """
        foreign_keys: dict[str, list[dict]] = {}
        try:
            fk_result = self._conn.execute(fk_sql)
            for row in fk_result.fetchall():
                key = f"{row[0]}.{row[1]}"
                if key not in foreign_keys:
                    foreign_keys[key] = []
                foreign_keys[key].append({
                    "column": row[2],
                    "references_schema": row[3],
                    "references_table": row[4],
                    "references_column": row[5],
                })
        except Exception:
            pass  # FK query may fail on older DuckDB versions

        schema: dict[str, Any] = {}
        for table_schema, table_name, col_name, data_type, is_nullable, col_default in all_cols:
            key = f"{table_schema}.{table_name}"
            if key not in schema:
                schema[key] = {
                    "schema": table_schema,
                    "name": table_name,
                    "columns": [],
                    "foreign_keys": foreign_keys.get(key, []),
                }
            schema[key]["columns"].append({
                "name": col_name,
                "type": data_type,
                "nullable": is_nullable == "YES",
                "default": col_default,
            })
        return schema

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values for schema linking optimization."""
        if self._conn is None:
            return {}
        result: dict[str, list] = {}
        for col in columns[:20]:
            try:
                r = self._conn.execute(
                    f'SELECT DISTINCT "{col}" FROM {table} WHERE "{col}" IS NOT NULL LIMIT {limit}'
                )
                values = [str(row[0]) for row in r.fetchall()]
                if values:
                    result[col] = values
            except Exception:
                continue
        return result

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
