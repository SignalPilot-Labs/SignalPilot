"""Redshift connector — psycopg2-backed (wire-compatible with PostgreSQL).

Supports Amazon Redshift clusters and Redshift Serverless.
Uses the same PostgreSQL wire protocol but with Redshift-specific schema queries.
"""

from __future__ import annotations

from typing import Any

from .base import BaseConnector

try:
    import psycopg2
    import psycopg2.extras

    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


class RedshiftConnector(BaseConnector):
    def __init__(self):
        self._conn = None

    async def connect(self, connection_string: str) -> None:
        if not HAS_PSYCOPG2:
            raise RuntimeError(
                "psycopg2 not installed. Run: pip install psycopg2-binary"
            )
        # Normalize redshift:// to postgresql:// for psycopg2
        dsn = connection_string
        if dsn.startswith("redshift://"):
            dsn = "postgresql://" + dsn[len("redshift://"):]

        self._conn = psycopg2.connect(dsn, connect_timeout=15)
        self._conn.set_session(readonly=True, autocommit=True)

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                if timeout:
                    cursor.execute(f"SET statement_timeout = {timeout * 1000}")
                cursor.execute(sql, params or ())
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
        except psycopg2.Error as e:
            # Reset the connection state after error
            try:
                self._conn.rollback()
            except Exception:
                pass
            raise RuntimeError(f"Redshift query error: {e}") from e

    async def get_schema(self) -> dict[str, Any]:
        if self._conn is None:
            raise RuntimeError("Not connected")

        # Columns with types
        sql = """
            SELECT
                schemaname AS table_schema,
                tablename AS table_name,
                "column" AS column_name,
                type AS data_type,
                CASE WHEN notnull THEN 'NO' ELSE 'YES' END AS is_nullable
            FROM pg_table_def
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema', 'pg_internal')
            ORDER BY schemaname, tablename, colnum
        """
        # Primary keys
        pk_sql = """
            SELECT
                n.nspname AS table_schema,
                cl.relname AS table_name,
                a.attname AS column_name
            FROM pg_constraint con
            JOIN pg_class cl ON con.conrelid = cl.oid
            JOIN pg_namespace n ON cl.relnamespace = n.oid
            JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attnum = ANY(con.conkey)
            WHERE con.contype = 'p'
                AND n.nspname NOT IN ('pg_catalog', 'information_schema')
        """
        # Foreign keys (critical for Spider2.0 join path discovery)
        fk_sql = """
            SELECT
                n.nspname AS table_schema,
                cl.relname AS table_name,
                a.attname AS column_name,
                n2.nspname AS foreign_table_schema,
                cl2.relname AS foreign_table_name,
                a2.attname AS foreign_column_name
            FROM pg_constraint con
            JOIN pg_class cl ON con.conrelid = cl.oid
            JOIN pg_namespace n ON cl.relnamespace = n.oid
            JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attnum = ANY(con.conkey)
            JOIN pg_class cl2 ON con.confrelid = cl2.oid
            JOIN pg_namespace n2 ON cl2.relnamespace = n2.oid
            JOIN pg_attribute a2 ON a2.attrelid = cl2.oid AND a2.attnum = ANY(con.confkey)
            WHERE con.contype = 'f'
                AND n.nspname NOT IN ('pg_catalog', 'information_schema')
        """
        # Row counts
        row_count_sql = """
            SELECT
                schemaname AS table_schema,
                relname AS table_name,
                n_live_tup AS estimated_row_count
            FROM pg_stat_user_tables
        """
        # Redshift distribution and sort key info
        dist_sort_sql = """
            SELECT
                schemaname AS table_schema,
                tablename AS table_name,
                diststyle,
                sortkey1
            FROM pg_table_def
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema', 'pg_internal')
            GROUP BY schemaname, tablename, diststyle, sortkey1
        """

        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()

        # Best-effort metadata enrichment
        pk_set: set[tuple] = set()
        foreign_keys: dict[str, list[dict]] = {}
        row_counts: dict[str, int] = {}

        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(pk_sql)
                pk_set = {(r["table_schema"], r["table_name"], r["column_name"]) for r in cursor.fetchall()}
        except Exception:
            pass

        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(fk_sql)
                for r in cursor.fetchall():
                    key = f"{r['table_schema']}.{r['table_name']}"
                    if key not in foreign_keys:
                        foreign_keys[key] = []
                    foreign_keys[key].append({
                        "column": r["column_name"],
                        "references_schema": r["foreign_table_schema"],
                        "references_table": r["foreign_table_name"],
                        "references_column": r["foreign_column_name"],
                    })
        except Exception:
            pass

        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(row_count_sql)
                for r in cursor.fetchall():
                    row_counts[f"{r['table_schema']}.{r['table_name']}"] = r["estimated_row_count"]
        except Exception:
            pass

        schema: dict[str, Any] = {}
        for row in rows:
            key = f"{row['table_schema']}.{row['table_name']}"
            if key not in schema:
                schema[key] = {
                    "schema": row["table_schema"],
                    "name": row["table_name"],
                    "columns": [],
                    "foreign_keys": foreign_keys.get(key, []),
                    "row_count": row_counts.get(key, 0),
                }
            schema[key]["columns"].append({
                "name": row["column_name"],
                "type": row["data_type"],
                "nullable": row["is_nullable"] == "YES",
                "primary_key": (row["table_schema"], row["table_name"], row["column_name"]) in pk_set,
            })

        return schema

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values for schema linking optimization."""
        if self._conn is None:
            return {}
        result: dict[str, list] = {}
        for col in columns[:20]:
            try:
                with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(
                        f'SELECT DISTINCT "{col}" FROM {table} WHERE "{col}" IS NOT NULL LIMIT {limit}'
                    )
                    rows = cursor.fetchall()
                    values = [str(r[col]) for r in rows if r.get(col) is not None]
                    if values:
                        result[col] = values
            except Exception:
                continue
        return result

    async def health_check(self) -> bool:
        if self._conn is None:
            return False
        try:
            with self._conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
