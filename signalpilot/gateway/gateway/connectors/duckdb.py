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
        self._credential_extras: dict = {}
        self._query_timeout: int | None = None

    def set_credential_extras(self, extras: dict) -> None:
        """Store credential extras — primarily for MotherDuck token auth."""
        self._credential_extras = extras
        if extras.get("query_timeout"):
            self._query_timeout = extras["query_timeout"]

    async def connect(self, connection_string: str) -> None:
        if not HAS_DUCKDB:
            raise RuntimeError("duckdb not installed. Run: pip install duckdb")

        # MotherDuck token from credential_extras takes precedence
        motherduck_token = self._credential_extras.get("motherduck_token", "")

        # connection_string is a file path, :memory:, or a MotherDuck URL (md:)
        self._db_path = connection_string
        is_memory = connection_string == ":memory:" or connection_string.startswith("md:")

        config = {}
        if motherduck_token and connection_string.startswith("md:"):
            config["motherduck_token"] = motherduck_token

        try:
            self._conn = duckdb.connect(connection_string, read_only=not is_memory, config=config)
        except Exception as e:
            err = str(e).lower()
            if "motherduck" in err or "token" in err or "auth" in err:
                raise RuntimeError(f"MotherDuck authentication failed: {e}") from e
            raise RuntimeError(f"DuckDB connection error: {e}") from e

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")

        import asyncio

        effective_timeout = timeout or self._query_timeout

        def _run():
            if params:
                result = self._conn.execute(sql, params)
            else:
                result = self._conn.execute(sql)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return [{col: val for col, val in zip(columns, row)} for row in rows]

        try:
            if effective_timeout:
                # DuckDB has no native query timeout — use asyncio timeout on thread
                return await asyncio.wait_for(
                    asyncio.to_thread(_run), timeout=effective_timeout
                )
            return await asyncio.to_thread(_run)
        except asyncio.TimeoutError:
            # Interrupt the connection to cancel the query
            try:
                self._conn.interrupt()
            except Exception:
                pass
            raise RuntimeError(f"DuckDB query timed out after {effective_timeout}s")
        except duckdb.Error as e:
            raise RuntimeError(f"DuckDB query error: {e}") from e

    async def get_schema(self) -> dict[str, Any]:
        if self._conn is None:
            raise RuntimeError("Not connected")

        # Single optimized query for all columns across all tables
        cols_sql = """
            SELECT
                c.table_schema, c.table_name, c.column_name,
                c.data_type, c.is_nullable, c.column_default,
                t.table_type
            FROM information_schema.columns c
            JOIN information_schema.tables t
                ON c.table_schema = t.table_schema AND c.table_name = t.table_name
            WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
                AND t.table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY c.table_schema, c.table_name, c.ordinal_position
        """
        cols_result = self._conn.execute(cols_sql)
        all_cols = cols_result.fetchall()

        # Primary keys
        pk_sql = """
            SELECT tc.table_schema, tc.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
        """
        pk_cols: set[str] = set()
        try:
            pk_result = self._conn.execute(pk_sql)
            for row in pk_result.fetchall():
                pk_cols.add(f"{row[0]}.{row[1]}.{row[2]}")
        except Exception:
            pass

        # Foreign keys
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
            pass

        # Row counts — duckdb_tables().estimated_size IS the estimated row count
        row_counts: dict[str, int] = {}
        table_comments: dict[str, str] = {}
        try:
            count_sql = """
                SELECT schema_name, table_name, estimated_size, comment
                FROM duckdb_tables()
                WHERE NOT internal
            """
            count_result = self._conn.execute(count_sql)
            for row in count_result.fetchall():
                key = f"{row[0]}.{row[1]}"
                row_counts[key] = row[2] or 0
                if row[3]:
                    table_comments[key] = row[3]
        except Exception:
            pass

        # Column comments via duckdb_columns()
        col_comments: dict[str, str] = {}
        try:
            cc_sql = """
                SELECT schema_name, table_name, column_name, comment
                FROM duckdb_columns()
                WHERE comment IS NOT NULL AND comment != ''
            """
            cc_result = self._conn.execute(cc_sql)
            for row in cc_result.fetchall():
                col_key = f"{row[0]}.{row[1]}.{row[2]}"
                col_comments[col_key] = row[3]
        except Exception:
            pass

        schema: dict[str, Any] = {}
        for row in all_cols:
            table_schema, table_name, col_name, data_type, is_nullable, col_default = row[:6]
            table_type = row[6] if len(row) > 6 else "BASE TABLE"
            key = f"{table_schema}.{table_name}"
            if key not in schema:
                schema[key] = {
                    "schema": table_schema,
                    "name": table_name,
                    "type": "view" if table_type == "VIEW" else "table",
                    "columns": [],
                    "foreign_keys": foreign_keys.get(key, []),
                    "row_count": row_counts.get(key, 0),
                    "description": table_comments.get(key, ""),
                }
            col_comment_key = f"{table_schema}.{table_name}.{col_name}"
            schema[key]["columns"].append({
                "name": col_name,
                "type": data_type,
                "nullable": is_nullable == "YES",
                "default": col_default,
                "primary_key": f"{table_schema}.{table_name}.{col_name}" in pk_cols,
                "comment": col_comments.get(col_comment_key, ""),
            })
        return schema

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values via single UNION ALL query (1 round trip)."""
        if self._conn is None or not columns:
            return {}
        try:
            sql = self._build_sample_union_sql(table, columns, limit, quote='"')
            result = self._conn.execute(sql)
            rows = result.fetchall()
            return self._parse_sample_union_result(rows)
        except Exception:
            # Fallback to per-column queries
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
