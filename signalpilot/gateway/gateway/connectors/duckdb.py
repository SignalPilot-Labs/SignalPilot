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
        super().__init__()
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._db_path: str = ""
        self._credential_extras: dict = {}

    def set_credential_extras(self, extras: dict) -> None:
        """Store credential extras — primarily for MotherDuck token auth."""
        super().set_credential_extras(extras)
        self._credential_extras = extras
        if extras.get("motherduck_token"):
            self._credential_extras["motherduck_token"] = extras["motherduck_token"]

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
            self._is_memory = is_memory
            self._config = config
            # For file-based DBs: don't hold a persistent write lock — connect transiently per query.
            # This allows dbt to acquire write access between MCP queries.
            if not is_memory:
                self._conn = None  # will connect lazily per query
            else:
                self._conn = duckdb.connect(connection_string, read_only=False, config=config)
        except Exception as e:
            err = str(e).lower()
            if "motherduck" in err or "token" in err or "auth" in err:
                raise RuntimeError(f"MotherDuck authentication failed: {e}") from e
            raise RuntimeError(f"DuckDB connection error: {e}") from e

    def _open_transient(self):
        """Open a transient read-only connection for file-based DBs."""
        return duckdb.connect(self._db_path, read_only=True, config=self._config)

    def _ensure_connected(self) -> None:
        """Verify DuckDB connection is alive; raise RuntimeError if lost."""
        if self._conn is None and self._is_memory:
            raise RuntimeError("Not connected")
        if self._conn is not None:
            try:
                self._conn.execute("SELECT 1")
            except Exception:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
                if self._is_memory:
                    raise RuntimeError("Connection lost — please reconnect")

    async def _execute_impl(
        self, sql: str, params: list | None = None, timeout: int | None = None
    ) -> list[dict[str, Any]]:
        import asyncio

        effective_timeout = timeout or self._query_timeout

        # For file-based DBs, open a transient read-only connection per query
        # so we don't hold a persistent write lock that conflicts with dbt.
        use_transient = not self._is_memory

        def _run():
            conn = self._open_transient() if use_transient else self._conn
            try:
                if params:
                    result = conn.execute(sql, params)
                else:
                    result = conn.execute(sql)
                columns = [desc[0] for desc in result.description]
                rows = result.fetchall()
                return [{col: val for col, val in zip(columns, row, strict=False)} for row in rows]
            finally:
                if use_transient:
                    conn.close()

        try:
            if effective_timeout:
                return await asyncio.wait_for(asyncio.to_thread(_run), timeout=effective_timeout)
            return await asyncio.to_thread(_run)
        except TimeoutError:
            raise RuntimeError(f"DuckDB query timed out after {effective_timeout}s")
        except duckdb.Error as e:
            raise RuntimeError(f"DuckDB query error: {e}") from e

    async def _get_schema_impl(self) -> dict[str, Any]:
        # For file-based DBs, open a transient connection to avoid holding a write lock
        conn = self._open_transient() if not self._is_memory else self._conn
        if conn is None:
            raise RuntimeError("Not connected")
        try:
            return await self._get_schema_with_conn(conn)
        finally:
            if not self._is_memory:
                conn.close()

    async def _get_schema_with_conn(self, conn) -> dict[str, Any]:
        import time as _time

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
        t0 = _time.monotonic()
        cols_result = conn.execute(cols_sql)
        all_cols = cols_result.fetchall()
        await self._audit_sql(cols_sql.strip(), len(all_cols), (_time.monotonic() - t0) * 1000)

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
            t0 = _time.monotonic()
            pk_result = conn.execute(pk_sql)
            pk_rows = pk_result.fetchall()
            await self._audit_sql(pk_sql.strip(), len(pk_rows), (_time.monotonic() - t0) * 1000)
            for row in pk_rows:
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
            t0 = _time.monotonic()
            fk_result = conn.execute(fk_sql)
            fk_rows = fk_result.fetchall()
            await self._audit_sql(fk_sql.strip(), len(fk_rows), (_time.monotonic() - t0) * 1000)
            for row in fk_rows:
                key = f"{row[0]}.{row[1]}"
                if key not in foreign_keys:
                    foreign_keys[key] = []
                foreign_keys[key].append(
                    {
                        "column": row[2],
                        "references_schema": row[3],
                        "references_table": row[4],
                        "references_column": row[5],
                    }
                )
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
            t0 = _time.monotonic()
            count_result = conn.execute(count_sql)
            count_rows = count_result.fetchall()
            await self._audit_sql(count_sql.strip(), len(count_rows), (_time.monotonic() - t0) * 1000)
            for row in count_rows:
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
            t0 = _time.monotonic()
            cc_result = conn.execute(cc_sql)
            cc_rows = cc_result.fetchall()
            await self._audit_sql(cc_sql.strip(), len(cc_rows), (_time.monotonic() - t0) * 1000)
            for row in cc_rows:
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
            schema[key]["columns"].append(
                {
                    "name": col_name,
                    "type": data_type,
                    "nullable": is_nullable == "YES",
                    "default": col_default,
                    "primary_key": f"{table_schema}.{table_name}.{col_name}" in pk_cols,
                    "comment": col_comments.get(col_comment_key, ""),
                }
            )
        return schema

    async def _get_sample_values_impl(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values via single UNION ALL query (1 round trip)."""
        import time as _time

        if not columns:
            return {}
        conn = self._open_transient() if not self._is_memory else self._conn
        if conn is None:
            return {}
        try:
            sql = self._build_sample_union_sql(table, columns, limit, quote='"')
            t0 = _time.monotonic()
            result = conn.execute(sql)
            rows = result.fetchall()
            await self._audit_sql(sql, len(rows), (_time.monotonic() - t0) * 1000)
            return self._parse_sample_union_result(rows)
        except Exception:
            # Fallback to per-column queries
            result: dict[str, list] = {}
            safe_table = self._quote_table(table)
            for col in columns[:20]:
                try:
                    safe_col = self._quote_identifier(col)
                    fallback_sql = (
                        f"SELECT DISTINCT {safe_col} FROM {safe_table} WHERE {safe_col} IS NOT NULL LIMIT {limit}"
                    )
                    t0 = _time.monotonic()
                    r = conn.execute(fallback_sql)
                    values = [str(row[0]) for row in r.fetchall()]
                    await self._audit_sql(fallback_sql, len(values), (_time.monotonic() - t0) * 1000)
                    if values:
                        result[col] = values
                except Exception:
                    continue
            return result
        finally:
            if not self._is_memory:
                conn.close()

    async def health_check(self) -> bool:
        try:
            conn = self._open_transient() if not self._is_memory else self._conn
            if conn is None:
                return False
            result = conn.execute("SELECT 1")
            result.fetchall()
            if not self._is_memory:
                conn.close()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
