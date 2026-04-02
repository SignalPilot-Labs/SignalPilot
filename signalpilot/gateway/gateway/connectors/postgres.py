"""PostgreSQL connector — asyncpg-backed."""

from __future__ import annotations

import asyncio
from typing import Any

from .base import BaseConnector

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False


class PostgresConnector(BaseConnector):
    def __init__(self):
        self._pool = None
        self._ssl_config: dict | None = None
        self._temp_files: list[str] = []

    def set_ssl_config(self, ssl_config: dict) -> None:
        """Set SSL configuration (CA cert, client cert, client key as PEM strings)."""
        self._ssl_config = ssl_config

    async def connect(self, connection_string: str) -> None:
        if not HAS_ASYNCPG:
            raise RuntimeError("asyncpg not installed. Run: pip install asyncpg")

        # Build SSL context if SSL config provided
        ssl_ctx = None
        if self._ssl_config and self._ssl_config.get("enabled"):
            ssl_ctx = self._build_ssl_context()

        try:
            connect_kwargs: dict[str, Any] = {
                "min_size": 1,
                "max_size": 5,
                "timeout": 15,
                "command_timeout": 30,
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
        except (OSError, asyncio.TimeoutError) as e:
            raise RuntimeError(f"Connection failed (host unreachable or timeout): {e}") from e

    def _build_ssl_context(self):
        """Build an ssl.SSLContext from the stored SSL config."""
        import ssl
        import tempfile
        import os

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

        # Load CA certificate
        if self._ssl_config.get("ca_cert"):
            ca_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
            ca_file.write(self._ssl_config["ca_cert"].encode())
            ca_file.close()
            self._temp_files.append(ca_file.name)
            ctx.load_verify_locations(ca_file.name)
            if mode in ("verify-ca", "verify-full"):
                ctx.verify_mode = ssl.CERT_REQUIRED

        # Load client certificate + key (mutual TLS)
        if self._ssl_config.get("client_cert") and self._ssl_config.get("client_key"):
            cert_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
            cert_file.write(self._ssl_config["client_cert"].encode())
            cert_file.close()
            self._temp_files.append(cert_file.name)

            key_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
            key_file.write(self._ssl_config["client_key"].encode())
            key_file.close()
            os.chmod(key_file.name, 0o600)
            self._temp_files.append(key_file.name)

            ctx.load_cert_chain(cert_file.name, key_file.name)

        return ctx

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
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

    async def get_schema(self) -> dict[str, Any]:
        if self._pool is None:
            raise RuntimeError("Not connected")

        # Single optimized query: columns + primary keys + comments in one pass
        sql = """
            SELECT
                t.table_schema,
                t.table_name,
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
                AND t.table_type = 'BASE TABLE'
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

        # Row count estimates (fast, from pg_stat)
        row_count_sql = """
            SELECT
                schemaname AS table_schema,
                relname AS table_name,
                n_live_tup AS estimated_row_count
            FROM pg_stat_user_tables
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
        async def _fetch(query: str):
            async with self._pool.acquire() as c:
                return await c.fetch(query)

        rows, fk_rows, count_rows, idx_rows, stat_rows = await asyncio.gather(
            _fetch(sql),
            _fetch(fk_sql),
            _fetch(row_count_sql),
            _fetch(index_sql),
            _fetch(stats_sql),
        )

        # Build row count map
        row_counts: dict[str, int] = {}
        for r in count_rows:
            key = f"{r['table_schema']}.{r['table_name']}"
            row_counts[key] = r["estimated_row_count"]

        # Build foreign key map
        foreign_keys: dict[str, list[dict]] = {}
        for r in fk_rows:
            key = f"{r['table_schema']}.{r['table_name']}"
            if key not in foreign_keys:
                foreign_keys[key] = []
            foreign_keys[key].append({
                "column": r["column_name"],
                "references_schema": r["foreign_table_schema"],
                "references_table": r["foreign_table_name"],
                "references_column": r["foreign_column_name"],
            })

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
            indexes[key].append({
                "name": r["index_name"],
                "definition": r["index_definition"],
            })

        # Build schema
        schema: dict[str, Any] = {}
        for row in rows:
            key = f"{row['table_schema']}.{row['table_name']}"
            if key not in schema:
                schema[key] = {
                    "schema": row["table_schema"],
                    "name": row["table_name"],
                    "columns": [],
                    "foreign_keys": foreign_keys.get(key, []),
                    "indexes": indexes.get(key, []),
                    "row_count": row_counts.get(key, 0),
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

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values for schema linking optimization."""
        if self._pool is None:
            return {}

        result: dict[str, list] = {}
        # Run sample queries concurrently
        async def _sample(col: str):
            try:
                async with self._pool.acquire() as conn:
                    rows = await conn.fetch(
                        f'SELECT DISTINCT "{col}" FROM {table} WHERE "{col}" IS NOT NULL LIMIT {limit}'
                    )
                    return col, [r[col] for r in rows]
            except Exception:
                return col, []

        tasks = [_sample(c) for c in columns[:20]]  # Cap at 20 columns
        results = await asyncio.gather(*tasks)
        for col, values in results:
            if values:
                # Convert to strings for JSON serialization
                result[col] = [str(v) for v in values]
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
        # Cleanup temp SSL cert files
        import os
        for f in self._temp_files:
            try:
                os.unlink(f)
            except OSError:
                pass
        self._temp_files.clear()
