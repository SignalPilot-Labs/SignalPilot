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

    def _set_connector_specific_extras(self, extras: dict) -> None:
        """Handle postgres-specific extras: pool sizes, IAM auth, command timeout."""
        if extras.get("query_timeout"):
            self._command_timeout = extras["query_timeout"]
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

        # Single optimized query: columns + primary keys + comments in one pass
        sql = """
            SELECT
                t.table_schema,
                t.table_name,
                t.table_type,
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_primary_key,
                col_description(pgc.oid, c.ordinal_position) AS column_comment,
                obj_description(pgc.oid) AS table_comment
            FROM information_schema.tables t
            JOIN information_schema.columns c
                ON t.table_schema = c.table_schema
                AND t.table_name = c.table_name
            LEFT JOIN pg_catalog.pg_class pgc
                ON pgc.relname = t.table_name
                AND pgc.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = t.table_schema)
            LEFT JOIN (
                SELECT kcu.table_schema, kcu.table_name, kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
            ) pk
                ON c.table_schema = pk.table_schema
                AND c.table_name = pk.table_name
                AND c.column_name = pk.column_name
            WHERE t.table_schema NOT IN ('pg_catalog', 'information_schema')
                AND t.table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY t.table_schema, t.table_name, c.ordinal_position
        """

        # Foreign keys query — critical for Spider2.0 (join path discovery)
        fk_sql = """
            SELECT
                tc.table_schema,
                tc.table_name,
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
                AND tc.table_schema = ccu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
        """

        # Row count estimates and table sizes (fast, from pg_stat + pg_class)
        row_count_sql = """
            SELECT
                s.schemaname AS table_schema,
                s.relname AS table_name,
                s.n_live_tup AS estimated_row_count,
                pg_total_relation_size(s.relid) AS total_bytes
            FROM pg_stat_user_tables s
        """

        # Index metadata — helps Spider2.0 agent plan optimal queries
        index_sql = """
            SELECT
                schemaname AS table_schema,
                tablename AS table_name,
                indexname AS index_name,
                indexdef AS index_definition
            FROM pg_indexes
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            ORDER BY schemaname, tablename, indexname
        """

        # Column statistics from pg_stats — helps Spider2.0 understand data distribution
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
