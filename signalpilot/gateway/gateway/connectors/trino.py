"""Trino connector — trino Python client backed.

Supports Trino (formerly PrestoSQL) for federated SQL queries across
data sources. Used by HEX, Starburst, and many analytics platforms.
"""

from __future__ import annotations

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

    def set_credential_extras(self, extras: dict) -> None:
        self._credential_extras = extras

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

        # Authentication
        if params.get("password"):
            connect_kwargs["http_scheme"] = "https"
            connect_kwargs["auth"] = trino_lib.auth.BasicAuthentication(
                params["username"], params["password"]
            )

        try:
            self._conn = trino_lib.dbapi.connect(**connect_kwargs)
        except Exception as e:
            err_str = str(e).lower()
            if "unauthorized" in err_str or "401" in err_str or "authentication" in err_str:
                raise RuntimeError(f"Authentication failed: {e}") from e
            elif "connection refused" in err_str or "connect" in err_str:
                raise RuntimeError(f"Connection failed: cannot connect to Trino at {params.get('host', '')}:{params.get('port', 8080)}") from e
            raise RuntimeError(f"Trino connection error: {e}") from e

    def _parse_connection(self, conn_str: str) -> dict:
        """Parse trino://user@host:port/catalog/schema or trino://user:pass@host:port/catalog."""
        if conn_str.startswith("trino://"):
            from urllib.parse import urlparse, unquote, parse_qs

            parsed = urlparse(conn_str)
            path_parts = [p for p in (parsed.path or "").split("/") if p]
            query = parse_qs(parsed.query or "")

            return {
                "host": parsed.hostname or "localhost",
                "port": parsed.port or 8080,
                "username": unquote(parsed.username or "trino"),
                "password": unquote(parsed.password or ""),
                "catalog": path_parts[0] if len(path_parts) > 0 else "",
                "schema": path_parts[1] if len(path_parts) > 1 else query.get("schema", [""])[0],
            }

        # Fallback: treat as host
        return {"host": conn_str, "port": 8080, "username": "trino"}

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            cursor = self._conn.cursor()
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            raise RuntimeError(f"Trino query error: {e}") from e

    async def get_schema(self) -> dict[str, Any]:
        if self._conn is None:
            raise RuntimeError("Not connected")

        schema: dict[str, Any] = {}
        cursor = self._conn.cursor()

        # Get catalogs
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
            # Get schemas in catalog
            try:
                cursor.execute(f"SHOW SCHEMAS IN {catalog}")
                schemas = [row[0] for row in cursor.fetchall()
                          if row[0] not in ("information_schema",)]
            except Exception:
                continue

            for schema_name in schemas:
                # Get tables
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
        if self._conn is None:
            return {}
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
