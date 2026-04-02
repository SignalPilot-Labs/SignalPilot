"""Trino connector — trino Python client backed.

Supports Trino (formerly PrestoSQL) for federated SQL queries across
data sources. Used by HEX, Starburst, and many analytics platforms.

Schema introspection uses information_schema for speed (batch queries)
with SHOW COLUMNS fallback for catalogs that don't expose it.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .base import BaseConnector

try:
    import trino as trino_lib

    HAS_TRINO = True
except ImportError:
    HAS_TRINO = False


class TrinoConnector(BaseConnector):
    def __init__(self):
        self._conn = None
        self._connect_params: dict = {}
        self._credential_extras: dict = {}
        self._request_timeout: int | None = None

    def set_credential_extras(self, extras: dict) -> None:
        self._credential_extras = extras
        if extras.get("query_timeout"):
            self._request_timeout = extras["query_timeout"]

    async def connect(self, connection_string: str) -> None:
        if not HAS_TRINO:
            raise RuntimeError("trino not installed. Run: pip install trino")

        params = self._parse_connection(connection_string)
        # Merge credential extras
        if self._credential_extras:
            for key in ("username", "password", "catalog", "schema_name"):
                val = self._credential_extras.get(key)
                if val:
                    target = "schema" if key == "schema_name" else key
                    params[target] = val

        self._connect_params = params

        connect_kwargs: dict[str, Any] = {
            "host": params.get("host", "localhost"),
            "port": int(params.get("port", 8080)),
            "user": params.get("username", "trino"),
        }

        if params.get("catalog"):
            connect_kwargs["catalog"] = params["catalog"]
        if params.get("schema"):
            connect_kwargs["schema"] = params["schema"]

        # Authentication — support both password and password-less SSL
        has_password = bool(params.get("password"))
        use_https = params.get("https", False) or has_password

        if use_https:
            connect_kwargs["http_scheme"] = "https"
            if has_password:
                connect_kwargs["auth"] = trino_lib.auth.BasicAuthentication(
                    params["username"], params["password"]
                )
            # SSL verification — allow disabling for self-signed certs
            if params.get("verify", "true").lower() in ("false", "0", "no"):
                connect_kwargs["verify"] = False

        # Request timeout for all queries — from URL param or credential extras
        if params.get("request_timeout"):
            connect_kwargs["request_timeout"] = int(params["request_timeout"])
        elif self._request_timeout:
            connect_kwargs["request_timeout"] = self._request_timeout

        try:
            self._conn = trino_lib.dbapi.connect(**connect_kwargs)
        except Exception as e:
            err_str = str(e).lower()
            if "unauthorized" in err_str or "401" in err_str or "authentication" in err_str:
                raise RuntimeError(f"Authentication failed: {e}") from e
            elif "connection refused" in err_str or "connect" in err_str:
                raise RuntimeError(
                    f"Connection failed: cannot connect to Trino at "
                    f"{params.get('host', '')}:{params.get('port', 8080)}"
                ) from e
            raise RuntimeError(f"Trino connection error: {e}") from e

    def _parse_connection(self, conn_str: str) -> dict:
        """Parse trino://user@host:port/catalog/schema?param=value."""
        if conn_str.startswith("trino://") or conn_str.startswith("trino+https://"):
            from urllib.parse import urlparse, unquote, parse_qs

            # Handle trino+https:// scheme for SSL without password
            use_https = conn_str.startswith("trino+https://")
            if use_https:
                conn_str = "trino://" + conn_str[len("trino+https://"):]

            parsed = urlparse(conn_str)
            path_parts = [p for p in (parsed.path or "").split("/") if p]
            query = parse_qs(parsed.query or "")

            result = {
                "host": parsed.hostname or "localhost",
                "port": parsed.port or 8080,
                "username": unquote(parsed.username or "trino"),
                "password": unquote(parsed.password or ""),
                "catalog": path_parts[0] if len(path_parts) > 0 else "",
                "schema": path_parts[1] if len(path_parts) > 1 else query.get("schema", [""])[0],
                "https": use_https,
            }

            # Parse query params
            if query.get("verify"):
                result["verify"] = query["verify"][0]
            if query.get("request_timeout"):
                result["request_timeout"] = query["request_timeout"][0]

            return result

        # Fallback: treat as host
        return {"host": conn_str, "port": 8080, "username": "trino"}

    def _ensure_connected(self) -> None:
        """Verify connection is alive; raise if lost."""
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
        except Exception:
            self._conn = None
            raise RuntimeError("Connection lost — please reconnect")

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            cursor = self._conn.cursor()
            # Set session-level query timeout if supported
            if timeout:
                try:
                    cursor.execute(f"SET SESSION query_max_run_time = '{timeout}s'")
                except Exception:
                    pass  # Older Trino versions may not support this
                cursor = self._conn.cursor()  # Fresh cursor after SET
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            err_str = str(e)
            if "QUERY_EXCEEDED" in err_str or "exceeded" in err_str.lower():
                raise RuntimeError(f"Trino query timeout: {e}") from e
            raise RuntimeError(f"Trino query error: {e}") from e

    async def get_schema(self) -> dict[str, Any]:
        """Fetch schema using information_schema (fast batch) with SHOW COLUMNS fallback."""
        if self._conn is None:
            raise RuntimeError("Not connected")

        schema: dict[str, Any] = {}
        cursor = self._conn.cursor()

        # Determine catalogs to introspect
        catalogs = []
        if self._connect_params.get("catalog"):
            catalogs = [self._connect_params["catalog"]]
        else:
            try:
                cursor.execute("SHOW CATALOGS")
                catalogs = [row[0] for row in cursor.fetchall()
                           if row[0] not in ("system",)]
            except Exception:
                catalogs = []

        for catalog in catalogs:
            # Try fast path: information_schema batch query
            try:
                schema.update(self._fetch_schema_via_information_schema(catalog))
                continue
            except Exception:
                pass

            # Fallback: SHOW commands (slower but works with all connectors)
            schema.update(self._fetch_schema_via_show(catalog))

        return schema

    def _fetch_schema_via_information_schema(self, catalog: str) -> dict[str, Any]:
        """Fast batch schema introspection via information_schema."""
        cursor = self._conn.cursor()

        # Columns + table metadata in one query (with column comment if available)
        col_sql = f"""
            SELECT
                c.table_schema,
                c.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                c.ordinal_position,
                t.table_type,
                c.comment
            FROM {catalog}.information_schema.columns c
            JOIN {catalog}.information_schema.tables t
                ON c.table_schema = t.table_schema
                AND c.table_name = t.table_name
            WHERE c.table_schema NOT IN ('information_schema')
                AND t.table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY c.table_schema, c.table_name, c.ordinal_position
        """

        try:
            cursor.execute(col_sql)
            rows = cursor.fetchall()
        except Exception:
            # Fallback without comment column (not all catalogs have it)
            col_sql_no_comment = f"""
                SELECT
                    c.table_schema,
                    c.table_name,
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.column_default,
                    c.ordinal_position,
                    t.table_type
                FROM {catalog}.information_schema.columns c
                JOIN {catalog}.information_schema.tables t
                    ON c.table_schema = t.table_schema
                    AND c.table_name = t.table_name
                WHERE c.table_schema NOT IN ('information_schema')
                    AND t.table_type IN ('BASE TABLE', 'VIEW')
                ORDER BY c.table_schema, c.table_name, c.ordinal_position
            """
            cursor.execute(col_sql_no_comment)
            rows = cursor.fetchall()

        # Try to get table constraints (primary keys, foreign keys)
        pk_set: set[str] = set()
        foreign_keys: dict[str, list[dict]] = {}
        try:
            pk_sql = f"""
                SELECT
                    tc.table_schema,
                    tc.table_name,
                    kcu.column_name
                FROM {catalog}.information_schema.table_constraints tc
                JOIN {catalog}.information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
            """
            cursor.execute(pk_sql)
            for r in cursor.fetchall():
                pk_set.add(f"{r[0]}.{r[1]}.{r[2]}")

            # Foreign keys
            fk_sql = f"""
                SELECT
                    tc.table_schema,
                    tc.table_name,
                    kcu.column_name,
                    ccu.table_schema AS ref_schema,
                    ccu.table_name AS ref_table,
                    ccu.column_name AS ref_column
                FROM {catalog}.information_schema.table_constraints tc
                JOIN {catalog}.information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN {catalog}.information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
            """
            cursor.execute(fk_sql)
            for r in cursor.fetchall():
                key = f"{catalog}.{r[0]}.{r[1]}"
                if key not in foreign_keys:
                    foreign_keys[key] = []
                foreign_keys[key].append({
                    "column": r[2],
                    "references_schema": r[3],
                    "references_table": r[4],
                    "references_column": r[5],
                })
        except Exception:
            pass  # Not all Trino connectors expose constraints

        schema: dict[str, Any] = {}
        for row in rows:
            table_schema, table_name, col_name, data_type, nullable, default, ordinal, table_type = row[:8]
            col_comment = row[8] if len(row) > 8 else ""
            key = f"{catalog}.{table_schema}.{table_name}"
            pk_key = f"{table_schema}.{table_name}.{col_name}"

            if key not in schema:
                schema[key] = {
                    "schema": f"{catalog}.{table_schema}",
                    "name": table_name,
                    "type": "view" if table_type == "VIEW" else "table",
                    "columns": [],
                    "foreign_keys": foreign_keys.get(key, []),
                }
            schema[key]["columns"].append({
                "name": col_name,
                "type": data_type,
                "nullable": nullable == "YES",
                "primary_key": pk_key in pk_set,
                "default": default,
                "comment": col_comment or "",
            })

        return schema

    def _fetch_schema_via_show(self, catalog: str) -> dict[str, Any]:
        """Fallback schema introspection via SHOW commands."""
        cursor = self._conn.cursor()
        schema: dict[str, Any] = {}

        try:
            cursor.execute(f"SHOW SCHEMAS IN {catalog}")
            schemas = [row[0] for row in cursor.fetchall()
                      if row[0] not in ("information_schema",)]
        except Exception:
            return schema

        for schema_name in schemas:
            try:
                cursor.execute(f"SHOW TABLES IN {catalog}.{schema_name}")
                tables = [row[0] for row in cursor.fetchall()]
            except Exception:
                continue

            for table_name in tables:
                key = f"{catalog}.{schema_name}.{table_name}"
                try:
                    cursor.execute(f"SHOW COLUMNS IN {catalog}.{schema_name}.{table_name}")
                    columns = []
                    for row in cursor.fetchall():
                        columns.append({
                            "name": row[0],
                            "type": row[1],
                            "nullable": True,
                            "primary_key": False,
                            "comment": row[3] if len(row) > 3 and row[3] else "",
                        })
                    schema[key] = {
                        "schema": f"{catalog}.{schema_name}",
                        "name": table_name,
                        "columns": columns,
                    }
                except Exception:
                    continue

        return schema

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values via single UNION ALL query (1 round trip)."""
        if self._conn is None or not columns:
            return {}
        try:
            sql = self._build_sample_union_sql(table, columns, limit, quote='"')
            cursor = self._conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            return self._parse_sample_union_result(rows)
        except Exception:
            # Fallback to per-column queries
            result: dict[str, list] = {}
            for col in columns[:20]:
                try:
                    cursor = self._conn.cursor()
                    cursor.execute(
                        f'SELECT DISTINCT "{col}" FROM {table} WHERE "{col}" IS NOT NULL LIMIT {limit}'
                    )
                    rows = cursor.fetchall()
                    values = [str(row[0]) for row in rows if row[0] is not None]
                    if values:
                        result[col] = values
                except Exception:
                    continue
            return result

    async def health_check(self) -> bool:
        if self._conn is None:
            return False
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchall()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
