"""Redshift connector — psycopg2-backed (wire-compatible with PostgreSQL).

Supports Amazon Redshift clusters and Redshift Serverless.
Uses the same PostgreSQL wire protocol but with Redshift-specific schema queries.
"""

from __future__ import annotations

import logging
from typing import Any

from ..base import BaseConnector

logger = logging.getLogger(__name__)

try:
    import psycopg2
    import psycopg2.extras

    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


class RedshiftConnector(BaseConnector):
    def __init__(self):
        super().__init__()
        self._connect_timeout: int = self._connection_timeout
        self._query_timeout: int = self._query_timeout
        # IAM auth for Redshift (GetClusterCredentials or Serverless GetCredentials)
        self._iam_auth: bool = False
        self._iam_region: str = "us-east-1"
        self._iam_access_key: str = ""
        self._iam_secret_key: str = ""
        self._iam_cluster_id: str = ""  # For provisioned Redshift
        self._iam_workgroup: str = ""  # For Redshift Serverless

    def _set_connector_specific_extras(self, extras: dict) -> None:
        """Handle Redshift-specific IAM config and timeout mapping."""
        # Map base connection_timeout to Redshift's _connect_timeout
        self._connect_timeout = self._connection_timeout
        # IAM auth configuration
        if extras.get("auth_method") == "iam" or extras.get("iam_auth"):
            self._iam_auth = True
            self._iam_region = extras.get("aws_region", "us-east-1")
            self._iam_access_key = extras.get("aws_access_key_id", "")
            self._iam_secret_key = extras.get("aws_secret_access_key", "")
            self._iam_cluster_id = extras.get("cluster_id", "")
            self._iam_workgroup = extras.get("workgroup", "")

    def _generate_iam_credentials(self, db_user: str, db_name: str, host: str) -> tuple[str, str]:
        """Generate temporary credentials via Redshift GetClusterCredentials or Serverless GetCredentials.

        Returns (username, password) tuple with temporary IAM-based credentials.
        """
        try:
            import boto3
        except ImportError:
            raise RuntimeError("boto3 required for IAM auth. Run: pip install boto3")

        boto_kwargs: dict = {"region_name": self._iam_region}
        if self._iam_access_key and self._iam_secret_key:
            boto_kwargs["aws_access_key_id"] = self._iam_access_key
            boto_kwargs["aws_secret_access_key"] = self._iam_secret_key

        if self._iam_workgroup:
            # Redshift Serverless — use redshift-serverless client
            client = boto3.client("redshift-serverless", **boto_kwargs)
            resp = client.get_credentials(
                workgroupName=self._iam_workgroup,
                dbName=db_name,
            )
            return resp["dbUser"], resp["dbPassword"]
        # Provisioned Redshift — use redshift client
        cluster_id = self._iam_cluster_id
        if not cluster_id:
            # Try to extract cluster ID from host: cluster-id.xxx.region.redshift.amazonaws.com
            parts = host.split(".")
            if parts:
                cluster_id = parts[0]
        if not cluster_id:
            raise RuntimeError("IAM auth requires a cluster_id or a standard Redshift endpoint hostname")
        client = boto3.client("redshift", **boto_kwargs)
        resp = client.get_cluster_credentials(
            ClusterIdentifier=cluster_id,
            DbUser=db_user or "admin",
            DbName=db_name or "dev",
            AutoCreate=False,
        )
        return resp["DbUser"], resp["DbPassword"]

    async def connect(self, connection_string: str) -> None:
        if not HAS_PSYCOPG2:
            raise RuntimeError("psycopg2 not installed. Run: pip install psycopg2-binary")
        # Normalize redshift:// to postgresql:// for psycopg2
        dsn = connection_string
        if dsn.startswith("redshift://"):
            dsn = "postgresql://" + dsn[len("redshift://") :]

        # IAM auth: replace password with temporary credentials
        if self._iam_auth:
            from urllib.parse import quote, urlparse, urlunparse

            parsed = urlparse(dsn)
            host = parsed.hostname or "localhost"
            db_user = parsed.username or "admin"
            db_name = (parsed.path or "/dev").lstrip("/") or "dev"
            iam_user, iam_pass = self._generate_iam_credentials(db_user, db_name, host)
            dsn = urlunparse(
                (
                    parsed.scheme,
                    f"{quote(iam_user)}:{quote(iam_pass)}@{parsed.hostname}:{parsed.port or 5439}",
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                )
            )
            # IAM auth requires SSL
            if not self._ssl_config:
                self._ssl_config = {"enabled": True, "mode": "require"}

        # Build SSL kwargs from ssl_config if provided
        ssl_kwargs = self._build_ssl_kwargs() if self._ssl_config and self._ssl_config.get("enabled") else {}

        try:
            self._conn = psycopg2.connect(dsn, connect_timeout=self._connect_timeout, **ssl_kwargs)
            self._conn.set_session(readonly=True, autocommit=True)
        except psycopg2.OperationalError as e:
            self._cleanup_temp_files()
            err_str = str(e).lower()
            if "password authentication failed" in err_str:
                raise RuntimeError(f"Authentication failed: {e}") from e
            if "could not connect" in err_str or "connection refused" in err_str:
                raise RuntimeError(f"Connection failed (host unreachable or timeout): {e}") from e
            raise RuntimeError(f"Redshift connection error: {e}") from e
        except Exception as e:
            self._cleanup_temp_files()
            raise RuntimeError(f"Redshift connection error: {e}") from e

    def _build_ssl_kwargs(self) -> dict:
        """Build psycopg2 SSL keyword arguments from ssl_config."""
        kwargs: dict = {}
        mode = self._ssl_config.get("mode", "require")
        kwargs["sslmode"] = mode

        paths = self._write_ssl_files()
        if "ca" in paths:
            kwargs["sslrootcert"] = paths["ca"]
        if "cert" in paths:
            kwargs["sslcert"] = paths["cert"]
        if "key" in paths:
            kwargs["sslkey"] = paths["key"]

        return kwargs

    def _ensure_connected(self) -> None:
        """Verify connection is alive; reconnect if stale."""
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            raise RuntimeError("Connection lost — please reconnect")

    async def _execute_impl(
        self, sql: str, params: list | None = None, timeout: int | None = None
    ) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")

        effective_timeout = timeout or self._query_timeout

        def _run():
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                if effective_timeout:
                    cursor.execute(f"SET statement_timeout = {effective_timeout * 1000}")
                cursor.execute(sql, params or ())
                rows = cursor.fetchall()
                return [dict(r) for r in rows]

        try:
            return await self._run_in_thread(_run, effective_timeout, label="Redshift")
        except psycopg2.Error as e:
            try:
                self._conn.rollback()
            except Exception:
                pass
            raise RuntimeError(f"Redshift query error: {e}") from e

    async def _get_schema_impl(self) -> dict[str, Any]:
        if self._conn is None:
            raise RuntimeError("Not connected")

        # Combined columns + primary key + encoding + view detection query
        # Merges the former views_sql query into the main column query (6→5 queries)
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
                CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_primary_key,
                CASE WHEN v.viewname IS NOT NULL THEN true ELSE false END AS is_view
            FROM pg_table_def td
            LEFT JOIN (
                SELECT n.nspname AS table_schema, cl.relname AS table_name, a.attname AS column_name
                FROM pg_constraint con
                JOIN pg_class cl ON con.conrelid = cl.oid
                JOIN pg_namespace n ON cl.relnamespace = n.oid
                JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attnum = ANY(con.conkey)
                WHERE con.contype = 'p' AND n.nspname NOT IN ('pg_catalog', 'information_schema')
            ) pk ON td.schemaname = pk.table_schema AND td.tablename = pk.table_name AND td."column" = pk.column_name
            LEFT JOIN pg_views v ON td.schemaname = v.schemaname AND td.tablename = v.viewname
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

        # Column and table comments via pg_description (Redshift supports COMMENT ON)
        comments_sql = """
            SELECT
                n.nspname AS table_schema,
                c.relname AS table_name,
                a.attname AS column_name,
                d.description AS column_comment,
                td.description AS table_comment
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = a.attnum
            LEFT JOIN pg_description td ON td.objoid = c.oid AND td.objsubid = 0
            WHERE a.attnum > 0
                AND NOT a.attisdropped
                AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_internal')
                AND (d.description IS NOT NULL OR td.description IS NOT NULL)
        """

        import asyncio
        import time as _time

        # psycopg2 connections are NOT thread-safe — run all queries
        # sequentially in a single background thread to avoid corruption
        def _fetch(query: str, label: str = "") -> list:
            try:
                with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(query)
                    return cursor.fetchall()
            except Exception as e:
                logger.info("Redshift metadata query failed (%s): %s", label, e)
                return []

        def _fetch_all():
            return (
                _fetch(sql, "columns"),
                _fetch(fk_sql, "foreign_keys"),
                _fetch(table_info_sql, "table_info"),
                _fetch(stats_sql, "stats"),
                _fetch(comments_sql, "comments"),
            )

        t0 = _time.monotonic()
        rows, fk_rows_raw, table_info_raw, stats_raw, comments_raw = await asyncio.to_thread(_fetch_all)
        elapsed_ms = (_time.monotonic() - t0) * 1000
        await self._audit_sql(sql.strip(), len(rows), elapsed_ms)

        # Build FK map
        foreign_keys: dict[str, list[dict]] = {}
        for r in fk_rows_raw:
            key = f"{r['table_schema']}.{r['table_name']}"
            if key not in foreign_keys:
                foreign_keys[key] = []
            foreign_keys[key].append(
                {
                    "column": r["column_name"],
                    "references_schema": r["foreign_table_schema"],
                    "references_table": r["foreign_table_name"],
                    "references_column": r["foreign_column_name"],
                }
            )

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

        # Build comments maps (column + table)
        col_comments: dict[str, str] = {}
        table_comments: dict[str, str] = {}
        for r in comments_raw:
            key = f"{r['table_schema']}.{r['table_name']}"
            if r.get("table_comment") and key not in table_comments:
                table_comments[key] = r["table_comment"]
            if r.get("column_comment"):
                col_key = f"{key}.{r['column_name']}"
                col_comments[col_key] = r["column_comment"]

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
                    "type": "view" if row.get("is_view") else "table",
                    "columns": [],
                    "foreign_keys": foreign_keys.get(key, []),
                    "row_count": ti.get("row_count", 0),
                    "size_mb": ti.get("size_mb", 0),
                    "diststyle": ti.get("diststyle", ""),
                    "sortkey": "",  # Will be filled from sort_key_cols
                    "description": table_comments.get(key, ""),
                }

            # Track sort key columns by position
            sk_pos = row.get("sort_key_position", 0) or 0
            if sk_pos > 0:
                if key not in sort_key_cols:
                    sort_key_cols[key] = []
                sort_key_cols[key].append((sk_pos, row["column_name"]))

            col_comment_key = f"{key}.{row['column_name']}"
            col_entry: dict[str, Any] = {
                "name": row["column_name"],
                "type": row["data_type"],
                "nullable": row["is_nullable"] == "YES",
                "primary_key": bool(row.get("is_primary_key", False)),
                "comment": col_comments.get(col_comment_key, ""),
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

    async def _get_sample_values_impl(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values via single UNION ALL query (1 round trip)."""
        import time as _time

        if self._conn is None or not columns:
            return {}
        try:
            sql = self._build_sample_union_sql(table, columns, limit, quote='"')

            def _run():
                with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(sql)
                    return cursor.fetchall()

            t0 = _time.monotonic()
            rows = await self._run_in_thread(_run, label="Redshift")
            await self._audit_sql(sql.strip(), len(rows), (_time.monotonic() - t0) * 1000)
            return self._parse_sample_union_result(rows)
        except Exception:
            # Fallback to per-column queries if UNION ALL fails
            safe_table = self._quote_table(table)
            result: dict[str, list] = {}
            for col in columns[:20]:
                try:
                    safe_col = self._quote_identifier(col)
                    with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                        cursor.execute(
                            f"SELECT DISTINCT {safe_col} FROM {safe_table} WHERE {safe_col} IS NOT NULL LIMIT {limit}"
                        )
                        rows = cursor.fetchall()
                        values = [str(r[col]) for r in rows if r.get(col) is not None]
                        if values:
                            result[col] = values
                except Exception:
                    continue
            return result

    async def close(self) -> None:
        """Close connection and clean up temp files."""
        await super().close()
