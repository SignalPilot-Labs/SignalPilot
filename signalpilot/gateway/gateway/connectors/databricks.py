"""Databricks connector — databricks-sql-connector backed.

Supports Databricks SQL Warehouses and Unity Catalog.
Uses personal access tokens (PAT) or OAuth for authentication.
"""

from __future__ import annotations

from typing import Any

from .base import BaseConnector

try:
    from databricks import sql as databricks_sql

    HAS_DATABRICKS = True
except ImportError:
    HAS_DATABRICKS = False


class DatabricksConnector(BaseConnector):
    def __init__(self):
        self._conn = None
        self._connect_params: dict = {}
        self._credential_extras: dict = {}
        self._connection_timeout: int = 30
        self._query_timeout: int | None = None

    def set_credential_extras(self, extras: dict) -> None:
        """Store structured credential data for connection."""
        self._credential_extras = extras
        if extras.get("connection_timeout"):
            self._connection_timeout = extras["connection_timeout"]
        if extras.get("query_timeout"):
            self._query_timeout = extras["query_timeout"]

    async def connect(self, connection_string: str) -> None:
        if not HAS_DATABRICKS:
            raise RuntimeError(
                "databricks-sql-connector not installed. "
                "Run: pip install databricks-sql-connector"
            )
        params = self._parse_connection(connection_string)
        # Merge credential_extras (takes precedence)
        if self._credential_extras:
            for key in ("http_path", "access_token", "catalog", "schema_name"):
                val = self._credential_extras.get(key)
                if val:
                    target = "schema" if key == "schema_name" else key
                    params[target] = val
        self._connect_params = params

        connect_args = {
            "server_hostname": params["host"],
            "http_path": params["http_path"],
            "access_token": params["access_token"],
        }
        if params.get("catalog"):
            connect_args["catalog"] = params["catalog"]
        if params.get("schema"):
            connect_args["schema"] = params["schema"]

        try:
            self._conn = databricks_sql.connect(**connect_args)
        except Exception as e:
            err_str = str(e).lower()
            if "unauthorized" in err_str or "403" in err_str or "401" in err_str:
                raise RuntimeError(f"Authentication failed: invalid access token") from e
            elif "not found" in err_str or "404" in err_str:
                raise RuntimeError(f"Warehouse not found: verify http_path '{params.get('http_path', '')}'") from e
            elif "timeout" in err_str or "timed out" in err_str:
                raise RuntimeError(f"Connection timed out: {e}") from e
            elif "connection" in err_str and ("refused" in err_str or "failed" in err_str):
                raise RuntimeError(f"Connection failed: verify hostname '{params.get('host', '')}'") from e
            raise RuntimeError(f"Databricks connection error: {e}") from e

    def _parse_connection(self, conn_str: str) -> dict:
        """Parse Databricks connection strings.

        Supported formats:
        - databricks://host|http_path|token|catalog|schema (pipe-delimited)
        - databricks://token@host/http_path?catalog=CAT&schema=SCH (URL format)
        - host only (use with credential_extras)
        """
        if conn_str.startswith("databricks://"):
            inner = conn_str[len("databricks://"):]

            # Pipe-delimited format (legacy)
            if "|" in inner:
                parts = inner.split("|")
                return {
                    "host": parts[0] if len(parts) > 0 else "",
                    "http_path": parts[1] if len(parts) > 1 else "",
                    "access_token": parts[2] if len(parts) > 2 else "",
                    "catalog": parts[3] if len(parts) > 3 else "",
                    "schema": parts[4] if len(parts) > 4 else "",
                }

            # URL format: databricks://token@host/http_path?catalog=CAT&schema=SCH
            from urllib.parse import urlparse, unquote, parse_qs
            parsed = urlparse(conn_str)
            query = parse_qs(parsed.query or "")
            return {
                "host": parsed.hostname or "",
                "http_path": parsed.path.lstrip("/") if parsed.path else "",
                "access_token": unquote(parsed.username or ""),
                "catalog": query.get("catalog", [""])[0],
                "schema": query.get("schema", [""])[0],
            }
        return {"host": conn_str, "http_path": "", "access_token": ""}

    def _ensure_connected(self) -> None:
        """Verify Databricks connection is alive; raise RuntimeError if lost."""
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            raise RuntimeError("Connection lost — please reconnect")

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            cursor = self._conn.cursor()
            # Databricks SQL Warehouses support SET for query timeout
            if timeout:
                try:
                    cursor.execute(f"SET statement_timeout = {timeout}")
                except Exception:
                    pass  # Best-effort — not all Databricks runtimes support this
            cursor.execute(sql, params or ())
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            cursor.close()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            raise RuntimeError(f"Databricks query error: {e}") from e

    async def get_schema(self) -> dict[str, Any]:
        if self._conn is None:
            raise RuntimeError("Not connected")

        schema: dict[str, Any] = {}
        cursor = self._conn.cursor()

        # Prefer information_schema (Unity Catalog, Databricks SQL) — single query for all columns
        # Falls back to SHOW TABLES + DESCRIBE TABLE for legacy Hive metastore
        try:
            cursor.execute("""
                SELECT
                    table_schema,
                    table_name,
                    column_name,
                    data_type,
                    is_nullable,
                    column_default,
                    ordinal_position,
                    comment
                FROM information_schema.columns
                WHERE table_schema NOT IN ('information_schema')
                ORDER BY table_schema, table_name, ordinal_position
            """)
            for row in cursor.fetchall():
                s_name = row[0]
                t_name = row[1]
                key = f"{s_name}.{t_name}"
                if key not in schema:
                    schema[key] = {
                        "schema": s_name,
                        "name": t_name,
                        "columns": [],
                    }
                schema[key]["columns"].append({
                    "name": row[2],
                    "type": row[3] or "string",
                    "nullable": row[4] == "YES" if row[4] else True,
                    "primary_key": False,
                    "comment": row[7] or "" if len(row) > 7 else "",
                })
            cursor.close()

            # Try to get table-level metadata (row counts, etc.)
            if schema:
                try:
                    cursor2 = self._conn.cursor()
                    cursor2.execute("""
                        SELECT table_schema, table_name, table_type
                        FROM information_schema.tables
                        WHERE table_schema NOT IN ('information_schema')
                    """)
                    for row in cursor2.fetchall():
                        key = f"{row[0]}.{row[1]}"
                        if key in schema:
                            tt = (row[2] or "TABLE").upper()
                            schema[key]["type"] = "view" if "VIEW" in tt else "table"
                    cursor2.close()
                except Exception:
                    pass

            return schema
        except Exception as e:
            import logging
            logging.getLogger(__name__).info(
                "information_schema not available, falling back to SHOW/DESCRIBE: %s", e
            )

        # Fallback: SHOW TABLES + DESCRIBE TABLE (legacy Hive metastore)
        try:
            cursor.execute("SHOW SCHEMAS")
            schemas_list = [row[0] for row in cursor.fetchall()]
        except Exception:
            schemas_list = ["default"]

        for schema_name in schemas_list:
            if schema_name.lower() in ("information_schema",):
                continue
            try:
                cursor.execute(f"SHOW TABLES IN `{schema_name}`")
                tables = cursor.fetchall()
            except Exception:
                continue

            for table_row in tables:
                table_name = table_row[1] if len(table_row) > 1 else table_row[0]
                key = f"{schema_name}.{table_name}"
                try:
                    cursor.execute(f"DESCRIBE TABLE `{schema_name}`.`{table_name}`")
                    col_rows = cursor.fetchall()
                    columns = []
                    for cr in col_rows:
                        col_name = cr[0]
                        col_type = cr[1] if len(cr) > 1 else "string"
                        comment = cr[2] if len(cr) > 2 else ""
                        if col_name.startswith("#") or col_name == "":
                            continue
                        columns.append({
                            "name": col_name,
                            "type": col_type,
                            "nullable": True,
                            "primary_key": False,
                            "comment": comment or "",
                        })
                    schema[key] = {
                        "schema": schema_name,
                        "name": table_name,
                        "type": "table",
                        "columns": columns,
                    }
                except Exception:
                    continue

        cursor.close()
        return schema

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values via single UNION ALL query (1 round trip)."""
        if self._conn is None or not columns:
            return {}
        try:
            sql = self._build_sample_union_sql(table, columns, limit, quote='`')
            cursor = self._conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            cursor.close()
            return self._parse_sample_union_result(rows)
        except Exception:
            # Fallback to per-column queries
            result: dict[str, list] = {}
            for col in columns[:20]:
                try:
                    cursor = self._conn.cursor()
                    # Quote table name parts to prevent SQL injection
                    safe_table = ".".join(f"`{p}`" for p in table.split("."))
                    cursor.execute(f"SELECT DISTINCT `{col}` FROM {safe_table} WHERE `{col}` IS NOT NULL LIMIT {limit}")
                    rows = cursor.fetchall()
                    cursor.close()
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
            cursor.close()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
