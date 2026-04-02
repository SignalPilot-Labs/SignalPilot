"""Redshift connector — psycopg2-backed (wire-compatible with PostgreSQL).

Supports Amazon Redshift clusters and Redshift Serverless.
Uses the same PostgreSQL wire protocol but with Redshift-specific schema queries.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseConnector

logger = logging.getLogger(__name__)

try:
    import psycopg2
    import psycopg2.extras

    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


class RedshiftConnector(BaseConnector):
    def __init__(self):
        self._conn = None
        self._ssl_config: dict | None = None
        self._temp_files: list[str] = []

    def set_ssl_config(self, ssl_config: dict) -> None:
        """Set SSL configuration (CA cert, client cert, client key as PEM strings)."""
        self._ssl_config = ssl_config

    def set_credential_extras(self, extras: dict) -> None:
        """Extract SSL config from credential extras."""
        if extras.get("ssl_config"):
            self.set_ssl_config(extras["ssl_config"])

    async def connect(self, connection_string: str) -> None:
        if not HAS_PSYCOPG2:
            raise RuntimeError(
                "psycopg2 not installed. Run: pip install psycopg2-binary"
            )
        # Normalize redshift:// to postgresql:// for psycopg2
        dsn = connection_string
        if dsn.startswith("redshift://"):
            dsn = "postgresql://" + dsn[len("redshift://"):]

        # Build SSL kwargs from ssl_config if provided
        ssl_kwargs = self._build_ssl_kwargs() if self._ssl_config and self._ssl_config.get("enabled") else {}

        try:
            self._conn = psycopg2.connect(dsn, connect_timeout=15, **ssl_kwargs)
            self._conn.set_session(readonly=True, autocommit=True)
        except psycopg2.OperationalError as e:
            err_str = str(e).lower()
            if "password authentication failed" in err_str:
                raise RuntimeError(f"Authentication failed: {e}") from e
            elif "could not connect" in err_str or "connection refused" in err_str:
                raise RuntimeError(f"Connection failed (host unreachable or timeout): {e}") from e
            raise RuntimeError(f"Redshift connection error: {e}") from e

    def _build_ssl_kwargs(self) -> dict:
        """Build psycopg2 SSL keyword arguments from ssl_config."""
        import tempfile
        import os

        kwargs: dict = {}
        mode = self._ssl_config.get("mode", "require")
        kwargs["sslmode"] = mode

        if self._ssl_config.get("ca_cert"):
            ca_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
            ca_file.write(self._ssl_config["ca_cert"].encode())
            ca_file.close()
            self._temp_files.append(ca_file.name)
            kwargs["sslrootcert"] = ca_file.name

        if self._ssl_config.get("client_cert"):
            cert_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
            cert_file.write(self._ssl_config["client_cert"].encode())
            cert_file.close()
            self._temp_files.append(cert_file.name)
            kwargs["sslcert"] = cert_file.name

        if self._ssl_config.get("client_key"):
            key_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
            key_file.write(self._ssl_config["client_key"].encode())
            key_file.close()
            os.chmod(key_file.name, 0o600)
            self._temp_files.append(key_file.name)
            kwargs["sslkey"] = key_file.name

        return kwargs

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

        # Combined columns + primary key + encoding query (reduces round trips)
        sql = """
            SELECT
                td.schemaname AS table_schema,
                td.tablename AS table_name,
                td."column" AS column_name,
                td.type AS data_type,
                td.encoding AS column_encoding,
                CASE WHEN td.notnull THEN 'NO' ELSE 'YES' END AS is_nullable,
                CASE WHEN td.distkey THEN true ELSE false END AS is_dist_key,
                td.sortkey AS sort_key_position,
                CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_primary_key
            FROM pg_table_def td
            LEFT JOIN (
                SELECT n.nspname AS table_schema, cl.relname AS table_name, a.attname AS column_name
                FROM pg_constraint con
                JOIN pg_class cl ON con.conrelid = cl.oid
                JOIN pg_namespace n ON cl.relnamespace = n.oid
                JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attnum = ANY(con.conkey)
                WHERE con.contype = 'p' AND n.nspname NOT IN ('pg_catalog', 'information_schema')
            ) pk ON td.schemaname = pk.table_schema AND td.tablename = pk.table_name AND td."column" = pk.column_name
            WHERE td.schemaname NOT IN ('pg_catalog', 'information_schema', 'pg_internal')
            ORDER BY td.schemaname, td.tablename, td.colnum
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
        # Table-level metadata from SVV_TABLE_INFO (diststyle, sort keys, row counts)
        # This is the correct Redshift system view — pg_table_def does NOT have diststyle
        table_info_sql = """
            SELECT
                "schema" AS table_schema,
                "table" AS table_name,
                diststyle,
                sortkey1,
                sortkey_num,
                tbl_rows::bigint AS estimated_row_count,
                size AS size_mb,
                pct_used
            FROM svv_table_info
            WHERE "schema" NOT IN ('pg_catalog', 'information_schema', 'pg_internal')
        """
        # Column statistics from pg_stats (data distribution for Spider2.0)
        stats_sql = """
            SELECT
                schemaname AS table_schema,
                tablename AS table_name,
                attname AS column_name,
                n_distinct,
                most_common_vals::text AS common_values
            FROM pg_stats
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        """

        import asyncio

        # Run all metadata queries concurrently via thread pool
        def _fetch(query: str, label: str = "") -> list:
            try:
                with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(query)
                    return cursor.fetchall()
            except Exception as e:
                logger.info("Redshift metadata query failed (%s): %s", label, e)
                return []

        rows, fk_rows_raw, table_info_raw, stats_raw = await asyncio.gather(
            asyncio.to_thread(_fetch, sql, "columns"),
            asyncio.to_thread(_fetch, fk_sql, "foreign_keys"),
            asyncio.to_thread(_fetch, table_info_sql, "table_info"),
            asyncio.to_thread(_fetch, stats_sql, "stats"),
        )

        # Build FK map
        foreign_keys: dict[str, list[dict]] = {}
        for r in fk_rows_raw:
            key = f"{r['table_schema']}.{r['table_name']}"
            if key not in foreign_keys:
                foreign_keys[key] = []
            foreign_keys[key].append({
                "column": r["column_name"],
                "references_schema": r["foreign_table_schema"],
                "references_table": r["foreign_table_name"],
                "references_column": r["foreign_column_name"],
            })

        # Build table info map (from SVV_TABLE_INFO — authoritative for diststyle/sortkeys/rows)
        table_info: dict[str, dict] = {}
        for r in table_info_raw:
            key = f"{r['table_schema']}.{r['table_name']}"
            table_info[key] = {
                "diststyle": r.get("diststyle", ""),
                "sortkey1": r.get("sortkey1", ""),
                "sortkey_num": r.get("sortkey_num", 0),
                "row_count": r.get("estimated_row_count", 0) or 0,
                "size_mb": r.get("size_mb", 0) or 0,
            }

        # Build column stats map
        col_stats: dict[str, dict] = {}
        for r in stats_raw:
            stat_key = f"{r['table_schema']}.{r['table_name']}.{r['column_name']}"
            n_distinct = r.get("n_distinct")
            stats: dict[str, Any] = {}
            if n_distinct is not None:
                if n_distinct > 0:
                    stats["distinct_count"] = int(n_distinct)
                elif n_distinct < 0:
                    stats["distinct_fraction"] = float(n_distinct)
            col_stats[stat_key] = stats

        schema: dict[str, Any] = {}
        # Track sort key columns per table (from pg_table_def.sortkey column position)
        sort_key_cols: dict[str, list[tuple[int, str]]] = {}

        for row in rows:
            key = f"{row['table_schema']}.{row['table_name']}"
            if key not in schema:
                ti = table_info.get(key, {})
                schema[key] = {
                    "schema": row["table_schema"],
                    "name": row["table_name"],
                    "columns": [],
                    "foreign_keys": foreign_keys.get(key, []),
                    "row_count": ti.get("row_count", 0),
                    "size_mb": ti.get("size_mb", 0),
                    "diststyle": ti.get("diststyle", ""),
                    "sortkey": "",  # Will be filled from sort_key_cols
                }

            # Track sort key columns by position
            sk_pos = row.get("sort_key_position", 0) or 0
            if sk_pos > 0:
                if key not in sort_key_cols:
                    sort_key_cols[key] = []
                sort_key_cols[key].append((sk_pos, row["column_name"]))

            col_entry: dict[str, Any] = {
                "name": row["column_name"],
                "type": row["data_type"],
                "nullable": row["is_nullable"] == "YES",
                "primary_key": bool(row.get("is_primary_key", False)),
                "comment": "",
            }
            # Redshift column encoding (useful for query optimization)
            encoding = row.get("column_encoding", "")
            if encoding and encoding != "none":
                col_entry["encoding"] = encoding
            # Distribution key flag
            if row.get("is_dist_key"):
                col_entry["dist_key"] = True
            # Sort key position
            if sk_pos > 0:
                col_entry["sort_key_position"] = sk_pos
            # Column statistics
            stat_key = f"{row['table_schema']}.{row['table_name']}.{row['column_name']}"
            if stat_key in col_stats:
                col_entry["stats"] = col_stats[stat_key]

            schema[key]["columns"].append(col_entry)

        # Fill in composite sort keys (ordered by position)
        for key, cols in sort_key_cols.items():
            if key in schema:
                cols.sort(key=lambda x: x[0])
                schema[key]["sortkey"] = ", ".join(c[1] for c in cols)

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
        import os
        for f in self._temp_files:
            try:
                os.unlink(f)
            except OSError:
                pass
        self._temp_files.clear()
