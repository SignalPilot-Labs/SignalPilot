"""PostgreSQL connector — asyncpg-backed."""

from __future__ import annotations

import asyncio
from typing import Any

from ..base import BaseConnector

try:
    import asyncpg

    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False


class PostgresConnector(BaseConnector):
    def __init__(self):
        super().__init__()
        self._pool = None
        self._command_timeout: int = 30
        self._pool_min_size: int = 1
        self._pool_max_size: int = 5
        self._iam_auth: bool = False
        self._iam_region: str = "us-east-1"
        self._iam_access_key: str | None = None
        self._iam_secret_key: str | None = None
        # Optional schema allowlist — restricts introspection to these schemas.
        # Recommended for large enterprise DBs so schema discovery doesn't scan
        # every schema in the instance.
        self._schema_allowlist: list[str] = []

    def _set_connector_specific_extras(self, extras: dict) -> None:
        """Handle postgres-specific extras: pool sizes, IAM auth, command timeout."""
        if extras.get("query_timeout"):
            self._command_timeout = extras["query_timeout"]
        schemas = extras.get("schemas") or extras.get("schema_allowlist")
        if schemas:
            if isinstance(schemas, str):
                schemas = [s.strip() for s in schemas.split(",") if s.strip()]
            # keep only safe identifiers (defensive: these are interpolated)
            self._schema_allowlist = [
                s for s in schemas if s.replace("_", "").isalnum()
            ]
        if extras.get("pool_min_size"):
            self._pool_min_size = max(1, min(extras["pool_min_size"], 20))
        if extras.get("pool_max_size"):
            self._pool_max_size = max(1, min(extras["pool_max_size"], 50))
        if extras.get("auth_method") == "iam":
            self._iam_auth = True
            self._iam_region = extras.get("aws_region", "us-east-1")
            self._iam_access_key = extras.get("aws_access_key_id")
            self._iam_secret_key = extras.get("aws_secret_access_key")

    async def connect(self, connection_string: str) -> None:
        if not HAS_ASYNCPG:
            raise RuntimeError("asyncpg not installed. Run: pip install asyncpg")

        # For IAM auth, replace password in connection string with RDS token
        if self._iam_auth:
            from urllib.parse import quote, urlparse, urlunparse

            parsed = urlparse(connection_string)
            host = parsed.hostname or "localhost"
            port = parsed.port or 5432
            username = parsed.username or "postgres"
            token = self._generate_rds_iam_token(
                region=self._iam_region,
                host=host,
                port=port,
                username=username,
                access_key=self._iam_access_key,
                secret_key=self._iam_secret_key,
            )
            # Rebuild URL with IAM token as password (URL-encoded since tokens contain special chars)
            netloc = f"{quote(username, safe='')}:{quote(token, safe='')}@{host}:{port}"
            connection_string = urlunparse(parsed._replace(netloc=netloc))
            # IAM auth requires SSL
            if not self._ssl_config:
                self._ssl_config = {"enabled": True, "mode": "require"}

        # Build SSL context if SSL config provided
        ssl_ctx = None
        if self._ssl_config and self._ssl_config.get("enabled"):
            ssl_ctx = self._build_ssl_context()

        try:
            connect_kwargs: dict[str, Any] = {
                "min_size": self._pool_min_size,
                "max_size": self._pool_max_size,
                "timeout": self._connection_timeout,
                "command_timeout": self._command_timeout,
            }
            if ssl_ctx is not None:
                connect_kwargs["ssl"] = ssl_ctx
            self._pool = await asyncpg.create_pool(
                connection_string,
                **connect_kwargs,
            )
        except asyncpg.InvalidCatalogNameError as e:
            raise RuntimeError(f"Database not found: {e}") from e
        except asyncpg.InvalidAuthorizationSpecificationError as e:
            raise RuntimeError(f"Authentication failed: {e}") from e
        except (TimeoutError, OSError) as e:
            raise RuntimeError(f"Connection failed (host unreachable or timeout): {e}") from e

    def _build_ssl_context(self):
        """Build an ssl.SSLContext from the stored SSL config.

        Uses base class _write_ssl_files() for temp file management,
        but builds an ssl.SSLContext since asyncpg requires one.
        """
        import ssl

        mode = self._ssl_config.get("mode", "require")

        # Map SSL mode to ssl module constants
        if mode in ("verify-ca", "verify-full"):
            ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            ctx.check_hostname = mode == "verify-full"
        else:
            # "require" mode — encrypt but don't verify certs
            ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        # Write PEM strings to temp files via base class
        paths = self._write_ssl_files()

        # Load CA certificate
        if "ca" in paths:
            ctx.load_verify_locations(paths["ca"])
            if mode in ("verify-ca", "verify-full"):
                ctx.verify_mode = ssl.CERT_REQUIRED

        # Load client certificate + key (mutual TLS)
        if "cert" in paths and "key" in paths:
            ctx.load_cert_chain(paths["cert"], paths["key"])

        return ctx

    async def _ensure_connected(self) -> None:
        """Verify connection is alive; raise RuntimeError if lost."""
        if self._pool is None:
            raise RuntimeError("Not connected")
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
        except Exception:
            try:
                await self._pool.close()
            except Exception:
                pass
            self._pool = None
            raise RuntimeError("Connection lost — please reconnect")

    async def _execute_impl(
        self, sql: str, params: list | None = None, timeout: int | None = None
    ) -> list[dict[str, Any]]:
        if self._pool is None:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            # Set statement timeout on the DB side (Feature #8)
            # This cancels the query on the server, not just the client
            if timeout:
                await conn.execute(f"SET LOCAL statement_timeout = {timeout * 1000}")
            # Wrap in read-only transaction (defense in depth)
            async with conn.transaction(readonly=True):
                rows = await conn.fetch(sql, *(params or []), timeout=timeout)
                return [dict(r) for r in rows]

    async def _get_schema_impl(self) -> dict[str, Any]:
        if self._pool is None:
            raise RuntimeError("Not connected")

        # Columns + primary keys + comments in one pass.
        #
        # Reads pg_catalog DIRECTLY rather than information_schema. Rationale:
        #   * Speed: the IS views apply per-row privilege functions and expand
        #     key_column_usage/constraint_column_usage joins. On a warehouse with
        #     hundreds of tables / thousands of columns this measured ~10.5 MINUTES;
        #     the catalog form below returns in ~10ms.
        #   * Defensible for ANY role: pg_catalog (pg_class/pg_attribute/...) is
        #     world-readable, so the query never errors regardless of the connecting
        #     user's grants — it just returns fewer rows.
        #   * Security / PII: every column is gated by has_column_privilege(), so a
        #     user only ever sees columns they can actually SELECT. A DBA who hides a
        #     PII column via column-level GRANTs (e.g. GRANT SELECT (a,b) excluding
        #     ssn) will NOT see that column appear in the schema map. We gate on
        #     has_column_privilege (true for table- OR column-level grants), NOT
        #     has_table_privilege (which is false for column-only grants and would
        #     wrongly hide the whole table).
        # Optional schema allowlist (extras["schemas"]) narrows the scan further.
        schema_filter = ""        # for queries aliased as n.nspname
        schema_filter_sn = ""     # for queries using the `schemaname` column
        if self._schema_allowlist:
            quoted = ", ".join(f"'{s}'" for s in self._schema_allowlist)
            schema_filter = f"AND n.nspname IN ({quoted})"
            schema_filter_sn = f"AND schemaname IN ({quoted})"
        sql = f"""
            SELECT
                n.nspname AS table_schema,
                c.relname AS table_name,
                CASE WHEN c.relkind IN ('v', 'm') THEN 'VIEW' ELSE 'BASE TABLE' END AS table_type,
                a.attname AS column_name,
                format_type(a.atttypid, a.atttypmod) AS data_type,
                CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END AS is_nullable,
                pg_get_expr(ad.adbin, ad.adrelid) AS column_default,
                COALESCE(a.attnum = ANY(pk.conkey), false) AS is_primary_key,
                col_description(c.oid, a.attnum) AS column_comment,
                obj_description(c.oid) AS table_comment
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a
                ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
            LEFT JOIN pg_attrdef ad
                ON ad.adrelid = c.oid AND ad.adnum = a.attnum
            LEFT JOIN pg_constraint pk
                ON pk.conrelid = c.oid AND pk.contype = 'p'
            WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')   -- table, partitioned, view, matview, foreign
                AND NOT c.relispartition                    -- list the parent, not every child partition
                AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                AND n.nspname NOT LIKE 'pg_toast%'
                AND n.nspname NOT LIKE 'pg_temp%'
                AND has_schema_privilege(n.oid, 'USAGE')
                AND has_column_privilege(c.oid, a.attnum, 'SELECT')
                {schema_filter}
            ORDER BY n.nspname, c.relname, a.attnum
        """

        # Foreign keys — critical for join-path discovery. From pg_constraint
        # directly (avoids the notoriously slow information_schema
        # constraint_column_usage view). conkey/confkey are parallel column-number
        # arrays; unnest WITH ORDINALITY pairs local <-> referenced columns.
        # Only surface an FK when the user can read BOTH ends (no leaking the
        # existence of tables/columns they can't access).
        fk_sql = f"""
            SELECT
                n.nspname AS table_schema,
                c.relname AS table_name,
                att.attname AS column_name,
                fn.nspname AS foreign_table_schema,
                fc.relname AS foreign_table_name,
                fatt.attname AS foreign_column_name
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_class fc ON fc.oid = con.confrelid
            JOIN pg_namespace fn ON fn.oid = fc.relnamespace
            JOIN LATERAL unnest(con.conkey, con.confkey) WITH ORDINALITY
                AS k(attnum, fattnum, ord) ON true
            JOIN pg_attribute att
                ON att.attrelid = con.conrelid AND att.attnum = k.attnum
            JOIN pg_attribute fatt
                ON fatt.attrelid = con.confrelid AND fatt.attnum = k.fattnum
            WHERE con.contype = 'f'
                AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                AND has_table_privilege(con.conrelid, 'SELECT')
                AND has_table_privilege(con.confrelid, 'SELECT')
                {schema_filter}
            ORDER BY n.nspname, c.relname, k.ord
        """

        # Row count estimates and table sizes. Gated by has_table_privilege so we
        # don't expose row counts of tables the user can't read.
        row_count_sql = """
            SELECT
                s.schemaname AS table_schema,
                s.relname AS table_name,
                s.n_live_tup AS estimated_row_count,
                pg_total_relation_size(s.relid) AS total_bytes
            FROM pg_stat_user_tables s
            WHERE has_table_privilege(s.relid, 'SELECT')
        """

        # Index metadata. Gated by has_table_privilege — index definitions contain
        # column names (which could be PII column names), so never surface indexes
        # for a table the user cannot read.
        index_sql = f"""
            SELECT
                schemaname AS table_schema,
                tablename AS table_name,
                indexname AS index_name,
                indexdef AS index_definition
            FROM pg_indexes
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                AND has_table_privilege(
                    format('%I.%I', schemaname, tablename)::regclass, 'SELECT')
                {schema_filter_sn}
            ORDER BY schemaname, tablename, indexname
        """

        # Column statistics from pg_stats. pg_stats is already privilege-aware
        # (it only returns rows for columns the caller may read), so this is
        # consistent with the PII gating above; the allowlist just narrows scope.
        stats_sql = f"""
            SELECT
                schemaname AS table_schema,
                tablename AS table_name,
                attname AS column_name,
                n_distinct,
                most_common_vals::text AS common_values
            FROM pg_stats
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                {schema_filter_sn}
        """

        # Run queries concurrently using separate connections from pool
        import time as _time

        async def _fetch(query: str):
            t0 = _time.monotonic()
            async with self._pool.acquire() as c:
                result = await c.fetch(query)
            elapsed = (_time.monotonic() - t0) * 1000
            await self._audit_sql(query.strip(), len(result), elapsed)
            return result

        rows, fk_rows, count_rows, idx_rows, stat_rows = await asyncio.gather(
            _fetch(sql),
            _fetch(fk_sql),
            _fetch(row_count_sql),
            _fetch(index_sql),
            _fetch(stats_sql),
        )

        # Build row count and table size maps
        row_counts: dict[str, int] = {}
        table_sizes: dict[str, float] = {}
        for r in count_rows:
            key = f"{r['table_schema']}.{r['table_name']}"
            row_counts[key] = r["estimated_row_count"]
            total_bytes = r.get("total_bytes") or 0
            table_sizes[key] = round(total_bytes / (1024 * 1024), 2)  # bytes → MB

        # Build foreign key map
        foreign_keys: dict[str, list[dict]] = {}
        for r in fk_rows:
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

        # Build column stats map (n_distinct: positive = exact count, negative = fraction of rows)
        col_stats: dict[str, dict] = {}
        for r in stat_rows:
            stat_key = f"{r['table_schema']}.{r['table_name']}.{r['column_name']}"
            n_distinct = r.get("n_distinct", 0)
            stats: dict[str, Any] = {}
            if n_distinct is not None:
                if n_distinct > 0:
                    stats["distinct_count"] = int(n_distinct)
                elif n_distinct < 0:
                    # Negative means fraction of rows (e.g., -1 = all unique)
                    stats["distinct_fraction"] = float(n_distinct)
            col_stats[stat_key] = stats

        # Build index map
        indexes: dict[str, list[dict]] = {}
        for r in idx_rows:
            key = f"{r['table_schema']}.{r['table_name']}"
            if key not in indexes:
                indexes[key] = []
            indexes[key].append(
                {
                    "name": r["index_name"],
                    "definition": r["index_definition"],
                }
            )

        # Build schema
        schema: dict[str, Any] = {}
        for row in rows:
            key = f"{row['table_schema']}.{row['table_name']}"
            if key not in schema:
                is_view = row["table_type"] == "VIEW"
                schema[key] = {
                    "schema": row["table_schema"],
                    "name": row["table_name"],
                    "type": "view" if is_view else "table",
                    "columns": [],
                    "foreign_keys": foreign_keys.get(key, []),
                    "indexes": indexes.get(key, []),
                    "row_count": row_counts.get(key, 0),
                    "size_mb": table_sizes.get(key, 0),
                    "description": row["table_comment"] or "",
                }
            stat_key = f"{row['table_schema']}.{row['table_name']}.{row['column_name']}"
            col_entry: dict[str, Any] = {
                "name": row["column_name"],
                "type": row["data_type"],
                "nullable": row["is_nullable"] == "YES",
                "primary_key": row["is_primary_key"],
                "default": row["column_default"],
                "comment": row["column_comment"] or "",
            }
            if stat_key in col_stats:
                col_entry["stats"] = col_stats[stat_key]
            schema[key]["columns"].append(col_entry)
        return schema

    async def _get_sample_values_impl(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values via single UNION ALL query (1 round trip)."""
        import time as _time

        if self._pool is None or not columns:
            return {}
        try:
            sql = self._build_sample_union_sql(table, columns, limit, quote='"')
            t0 = _time.monotonic()
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql)
            await self._audit_sql(sql, len(rows), (_time.monotonic() - t0) * 1000)
            return self._parse_sample_union_result([dict(r) for r in rows])
        except Exception:
            # Fallback to per-column queries if UNION ALL fails
            safe_table = self._quote_table(table)
            result: dict[str, list] = {}

            async def _sample(col: str):
                try:
                    safe_col = self._quote_identifier(col)
                    async with self._pool.acquire() as conn:
                        rows = await conn.fetch(
                            f"SELECT DISTINCT {safe_col} FROM {safe_table} WHERE {safe_col} IS NOT NULL LIMIT {limit}"
                        )
                        return col, [str(r[col]) for r in rows]
                except Exception:
                    return col, []

            tasks = [_sample(c) for c in columns[:20]]
            results = await asyncio.gather(*tasks)
            for col, values in results:
                if values:
                    result[col] = values
            return result

    async def health_check(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None
        self._cleanup_temp_files()
