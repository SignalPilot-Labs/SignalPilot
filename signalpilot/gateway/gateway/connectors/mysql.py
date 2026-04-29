"""MySQL connector — PyMySQL/aiomysql-backed.

Supports MySQL 5.7+, MariaDB 10.2+, and cloud-managed instances (RDS, Cloud SQL, PlanetScale).
Uses PyMySQL for synchronous operations wrapped in async context.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .base import BaseConnector

try:
    import pymysql
    import pymysql.cursors

    HAS_PYMYSQL = True
except ImportError:
    HAS_PYMYSQL = False


class MySQLConnector(BaseConnector):
    def __init__(self):
        super().__init__()
        self._conn: pymysql.Connection | None = None
        self._connect_kwargs: dict = {}
        self._connect_params: dict = {}
        self._read_timeout: int = 30
        self._write_timeout: int = 30
        self._query_timeout: int = 30
        self._iam_auth: bool = False
        self._iam_region: str = "us-east-1"
        self._iam_access_key: str | None = None
        self._iam_secret_key: str | None = None

    # ─── Identifier quoting ───────────────────────────────────────────

    @property
    def _identifier_quote(self) -> str:
        return '`'

    # ─── Credential extras ────────────────────────────────────────────

    def set_credential_extras(self, extras: dict) -> None:
        """Extract SSL config, IAM auth, and timeout settings from credential extras."""
        super().set_credential_extras(extras)
        # Map query_timeout to read_timeout for pymysql
        if extras.get("query_timeout"):
            self._read_timeout = extras["query_timeout"]
        if extras.get("auth_method") == "iam":
            self._iam_auth = True
            self._iam_region = extras.get("aws_region", "us-east-1")
            self._iam_access_key = extras.get("aws_access_key_id")
            self._iam_secret_key = extras.get("aws_secret_access_key")

    def set_ssl_config(self, ssl_config: dict) -> None:
        """Set SSL configuration for the connection."""
        self._ssl_config = ssl_config

    # ─── Connect ──────────────────────────────────────────────────────

    async def connect(self, connection_string: str) -> None:
        if not HAS_PYMYSQL:
            raise RuntimeError("pymysql not installed. Run: pip install pymysql")

        params = self._parse_connection_string(connection_string)
        self._connect_params = params

        # For IAM auth, generate short-lived RDS token as password
        password = params.get("password", "")
        if self._iam_auth:
            host = params.get("host", "localhost")
            port = int(params.get("port", 3306))
            user = params.get("user", "root")
            password = self._generate_rds_iam_token(
                region=self._iam_region,
                host=host,
                port=port,
                username=user,
                access_key=self._iam_access_key,
                secret_key=self._iam_secret_key,
            )
            # IAM auth requires SSL
            if not self._ssl_config:
                self._ssl_config = {"enabled": True, "mode": "require"}

        connect_kwargs: dict = {
            "host": params.get("host", "localhost"),
            "port": int(params.get("port", 3306)),
            "user": params.get("user", "root"),
            "password": password,
            "database": params.get("database", ""),
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,
            "connect_timeout": self._connection_timeout,
            "read_timeout": self._read_timeout,
            "write_timeout": self._write_timeout,
            "autocommit": True,
        }

        # SSL support — pymysql uses ssl dict with ca/cert/key paths or content
        if self._ssl_config and self._ssl_config.get("enabled"):
            import ssl as ssl_module

            ssl_ctx = ssl_module.create_default_context()

            # Write PEM content to temp files using base class helper
            ssl_paths = self._write_ssl_files()

            if ssl_paths:
                connect_kwargs["ssl"] = ssl_paths
            else:
                # SSL enabled but no certs — enforce SSL with no cert verification
                connect_kwargs["ssl"] = {"check_hostname": False}

        # Store kwargs for reconnection
        self._connect_kwargs = connect_kwargs

        try:
            self._conn = pymysql.connect(**connect_kwargs)
            # Enforce read-only mode at session level (defense-in-depth)
            with self._conn.cursor() as cur:
                cur.execute("SET SESSION TRANSACTION READ ONLY")
        except pymysql.err.OperationalError as e:
            code = e.args[0] if e.args else 0
            if code == 1045:
                raise RuntimeError(f"Authentication failed: Access denied for user '{connect_kwargs.get('user', '')}'") from e
            elif code == 2003:
                raise RuntimeError(f"Connection failed: Can't connect to MySQL server on '{connect_kwargs.get('host', '')}:{connect_kwargs.get('port', 3306)}'") from e
            elif code == 1049:
                raise RuntimeError(f"Database not found: Unknown database '{connect_kwargs.get('database', '')}'") from e
            raise RuntimeError(f"MySQL connection error: {e}") from e

    def _parse_connection_string(self, conn_str: str) -> dict:
        """Parse mysql+pymysql://user:pass@host:port/db or mysql://... format."""
        from urllib.parse import urlparse, unquote

        # Normalize scheme
        s = conn_str
        for prefix in ("mysql+pymysql://", "mysql://", "mariadb://"):
            if s.startswith(prefix):
                s = "mysql://" + s[len(prefix):]
                break

        parsed = urlparse(s)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": unquote(parsed.username or "root"),
            "password": unquote(parsed.password or ""),
            "database": parsed.path.lstrip("/") if parsed.path else "",
        }

    # ─── Execute ──────────────────────────────────────────────────────

    async def _execute_impl(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")

        effective_timeout = timeout or self._read_timeout

        def _run():
            self._ensure_connected()
            with self._conn.cursor() as cursor:
                if effective_timeout:
                    cursor.execute(f"SET SESSION max_execution_time = {effective_timeout * 1000}")
                cursor.execute(sql, params or ())
                rows = cursor.fetchall()
                return list(rows) if rows else []

        try:
            result = await self._run_in_thread(_run, effective_timeout, label="MySQL")
        except pymysql.Error as e:
            raise RuntimeError(f"MySQL query error: {e}") from e
        return result

    # ─── Schema ───────────────────────────────────────────────────────

    async def _get_schema_impl(self) -> dict[str, Any]:
        import time as _time
        if self._conn is None:
            raise RuntimeError("Not connected")

        # Columns + primary keys + comments
        sql = """
            SELECT
                t.TABLE_SCHEMA,
                t.TABLE_NAME,
                t.TABLE_TYPE,
                t.TABLE_COMMENT,
                t.TABLE_ROWS,
                t.DATA_LENGTH,
                t.INDEX_LENGTH,
                c.COLUMN_NAME,
                c.DATA_TYPE,
                c.IS_NULLABLE,
                c.COLUMN_DEFAULT,
                c.COLUMN_KEY,
                c.COLUMN_COMMENT
            FROM information_schema.TABLES t
            JOIN information_schema.COLUMNS c
                ON t.TABLE_SCHEMA = c.TABLE_SCHEMA
                AND t.TABLE_NAME = c.TABLE_NAME
            WHERE t.TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
                AND t.TABLE_TYPE IN ('BASE TABLE', 'VIEW')
            ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME, c.ORDINAL_POSITION
        """
        # Foreign keys — critical for Spider2.0 join path discovery
        fk_sql = """
            SELECT
                TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME,
                REFERENCED_TABLE_SCHEMA, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE REFERENCED_TABLE_NAME IS NOT NULL
                AND TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
        """
        # Index metadata + cardinality in a single query (avoids redundant STATISTICS scan)
        idx_sql = """
            SELECT
                TABLE_SCHEMA, TABLE_NAME, INDEX_NAME, NON_UNIQUE,
                GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS columns,
                MAX(CASE WHEN SEQ_IN_INDEX = 1 THEN CARDINALITY END) AS lead_cardinality,
                MIN(CASE WHEN SEQ_IN_INDEX = 1 THEN COLUMN_NAME END) AS lead_column
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
            GROUP BY TABLE_SCHEMA, TABLE_NAME, INDEX_NAME, NON_UNIQUE
        """
        # PyMySQL is not thread-safe for concurrent queries on the same connection,
        # but we can batch queries to reduce round trips

        def _fetch(query: str) -> list:
            try:
                self._ensure_connected()
                with self._conn.cursor() as cursor:
                    cursor.execute(query)
                    return cursor.fetchall()
            except Exception:
                return []

        def _fetch_all_sequential() -> tuple:
            """Run all metadata queries sequentially — PyMySQL uses a single connection."""
            return (
                _fetch(sql),
                _fetch(fk_sql),
                _fetch(idx_sql),
            )

        # Run the synchronous queries in a thread pool to avoid blocking the event loop
        t0 = _time.monotonic()
        rows, fk_rows, idx_rows = await asyncio.to_thread(_fetch_all_sequential)
        elapsed_ms = (_time.monotonic() - t0) * 1000
        await self._audit_sql(sql.strip(), len(rows), elapsed_ms)
        await self._audit_sql(fk_sql.strip(), len(fk_rows), elapsed_ms)
        await self._audit_sql(idx_sql.strip(), len(idx_rows), elapsed_ms)

        # Build cardinality map from the combined index query
        cardinality: dict[str, int] = {}
        for r in idx_rows:
            lead_col = r.get("lead_column")
            lead_card = r.get("lead_cardinality")
            if lead_col and lead_card:
                card_key = f"{r['TABLE_SCHEMA']}.{r['TABLE_NAME']}.{lead_col}"
                existing = cardinality.get(card_key, 0)
                if (lead_card or 0) > existing:
                    cardinality[card_key] = lead_card

        # Build index map
        indexes: dict[str, list[dict]] = {}
        for r in idx_rows:
            key = f"{r['TABLE_SCHEMA']}.{r['TABLE_NAME']}"
            if key not in indexes:
                indexes[key] = []
            indexes[key].append({
                "name": r["INDEX_NAME"],
                "columns": r["columns"],
                "unique": not r["NON_UNIQUE"],
            })

        # Build FK map
        foreign_keys: dict[str, list[dict]] = {}
        for r in fk_rows:
            key = f"{r['TABLE_SCHEMA']}.{r['TABLE_NAME']}"
            if key not in foreign_keys:
                foreign_keys[key] = []
            foreign_keys[key].append({
                "column": r["COLUMN_NAME"],
                "references_schema": r["REFERENCED_TABLE_SCHEMA"],
                "references_table": r["REFERENCED_TABLE_NAME"],
                "references_column": r["REFERENCED_COLUMN_NAME"],
            })

        schema: dict[str, Any] = {}
        for row in rows:
            key = f"{row['TABLE_SCHEMA']}.{row['TABLE_NAME']}"
            if key not in schema:
                is_view = row.get("TABLE_TYPE") == "VIEW"
                data_len = row.get("DATA_LENGTH") or 0
                idx_len = row.get("INDEX_LENGTH") or 0
                size_mb = round((data_len + idx_len) / (1024 * 1024), 2)
                schema[key] = {
                    "schema": row["TABLE_SCHEMA"],
                    "name": row["TABLE_NAME"],
                    "type": "view" if is_view else "table",
                    "columns": [],
                    "foreign_keys": foreign_keys.get(key, []),
                    "indexes": indexes.get(key, []),
                    "row_count": row.get("TABLE_ROWS", 0),
                    "size_mb": size_mb,
                    "description": row.get("TABLE_COMMENT", ""),
                }
            col_entry: dict[str, Any] = {
                "name": row["COLUMN_NAME"],
                "type": row["DATA_TYPE"],
                "nullable": row["IS_NULLABLE"] == "YES",
                "primary_key": row["COLUMN_KEY"] == "PRI",
                "default": row.get("COLUMN_DEFAULT"),
                "comment": row.get("COLUMN_COMMENT", ""),
            }
            card_key = f"{row['TABLE_SCHEMA']}.{row['TABLE_NAME']}.{row['COLUMN_NAME']}"
            if card_key in cardinality:
                col_entry["stats"] = {"distinct_count": cardinality[card_key]}
            schema[key]["columns"].append(col_entry)
        return schema

    # ─── Sample values ────────────────────────────────────────────────

    async def _get_sample_values_impl(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values via single UNION ALL query (1 round trip)."""
        import time as _time
        if self._conn is None or not columns:
            return {}
        self._ensure_connected()
        try:
            sql = self._build_sample_union_sql(table, columns, limit, quote='`')
            t0 = _time.monotonic()
            with self._conn.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()
            await self._audit_sql(sql.strip(), len(rows), (_time.monotonic() - t0) * 1000)
            return self._parse_sample_union_result(rows)
        except Exception:
            # Fallback to per-column queries (uses _quote_table to prevent SQL injection)
            safe_table = self._quote_table(table)
            result: dict[str, list] = {}
            for col in columns[:20]:
                try:
                    safe_col = col.replace("`", "``")
                    with self._conn.cursor() as cursor:
                        cursor.execute(
                            f"SELECT DISTINCT `{safe_col}` FROM {safe_table} WHERE `{safe_col}` IS NOT NULL LIMIT {limit}"
                        )
                        rows = cursor.fetchall()
                        values = [str(r[col]) for r in rows if r[col] is not None]
                        if values:
                            result[col] = values
                except Exception:
                    continue
            return result

    # ─── Health check ─────────────────────────────────────────────────

    async def health_check(self) -> bool:
        if self._conn is None:
            return False
        try:
            self._ensure_connected()
            with self._conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except Exception:
            return False

    # ─── Connection management ────────────────────────────────────────

    def _ensure_connected(self) -> None:
        """Ensure connection is alive, reconnect if needed."""
        if self._conn is None:
            if self._connect_kwargs:
                self._conn = pymysql.connect(**self._connect_kwargs)
                with self._conn.cursor() as cur:
                    cur.execute("SET SESSION TRANSACTION READ ONLY")
            else:
                raise RuntimeError("Not connected")
            return
        try:
            self._conn.ping(reconnect=True)
        except Exception:
            # Connection truly dead — reconnect from scratch
            try:
                self._conn.close()
            except Exception:
                pass
            if self._connect_kwargs:
                self._conn = pymysql.connect(**self._connect_kwargs)
                with self._conn.cursor() as cur:
                    cur.execute("SET SESSION TRANSACTION READ ONLY")
            else:
                raise RuntimeError("Connection lost and cannot reconnect")

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
        self._cleanup_temp_files()
