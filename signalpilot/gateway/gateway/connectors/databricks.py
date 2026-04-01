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

    def set_credential_extras(self, extras: dict) -> None:
        """Store structured credential data for connection."""
        self._credential_extras = extras

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

        self._conn = databricks_sql.connect(**connect_args)

    def _parse_connection(self, conn_str: str) -> dict:
        """Parse databricks://host|http_path|token format."""
        if conn_str.startswith("databricks://"):
            parts = conn_str[len("databricks://"):].split("|")
            return {
                "host": parts[0] if len(parts) > 0 else "",
                "http_path": parts[1] if len(parts) > 1 else "",
                "access_token": parts[2] if len(parts) > 2 else "",
                "catalog": parts[3] if len(parts) > 3 else "",
                "schema": parts[4] if len(parts) > 4 else "",
            }
        return {"host": conn_str, "http_path": "", "access_token": ""}

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            cursor = self._conn.cursor()
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

        # List schemas (databases)
        try:
            cursor.execute("SHOW SCHEMAS")
            schemas = [row[0] for row in cursor.fetchall()]
        except Exception:
            schemas = ["default"]

        for schema_name in schemas:
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
                        # Skip partition info lines
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
                        "columns": columns,
                    }
                except Exception:
                    continue

        cursor.close()
        return schema

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
