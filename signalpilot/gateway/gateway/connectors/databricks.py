"""Databricks connector — databricks-sql-connector backed.

Supports Databricks SQL Warehouses and Unity Catalog.
Authentication methods:
  - Personal Access Token (PAT) — simplest, workspace-scoped
  - OAuth M2M (service principal) — production-grade, uses client_id/client_secret
  - OAuth U2M — user-to-machine, browser-based OAuth flow

HEX pattern: Databricks recommends OAuth M2M for automated/service connections.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseConnector

logger = logging.getLogger(__name__)

try:
    from databricks import sql as databricks_sql

    HAS_DATABRICKS = True
except ImportError:
    HAS_DATABRICKS = False


class DatabricksConnector(BaseConnector):
    def __init__(self):
        super().__init__()
        self._conn = None
        self._connect_params: dict = {}
        self._credential_extras: dict = {}
        # Auth method: "pat" (default), "oauth_m2m", "oauth_u2m"
        self._auth_method: str = "pat"
        self._oauth_client_id: str = ""
        self._oauth_client_secret: str = ""

    @property
    def _identifier_quote(self) -> str:
        return "`"

    def set_credential_extras(self, extras: dict) -> None:
        """Store structured credential data for connection."""
        super().set_credential_extras(extras)
        self._credential_extras = extras
        if extras.get("auth_method"):
            self._auth_method = extras["auth_method"]
        if extras.get("oauth_client_id"):
            self._oauth_client_id = extras["oauth_client_id"]
        if extras.get("oauth_client_secret"):
            self._oauth_client_secret = extras["oauth_client_secret"]

    async def connect(self, connection_string: str) -> None:
        if not HAS_DATABRICKS:
            raise RuntimeError("databricks-sql-connector not installed. Run: pip install databricks-sql-connector")
        params = self._parse_connection(connection_string)
        # Merge credential_extras (takes precedence)
        if self._credential_extras:
            for key in (
                "http_path",
                "access_token",
                "catalog",
                "schema_name",
                "auth_method",
                "oauth_client_id",
                "oauth_client_secret",
            ):
                val = self._credential_extras.get(key)
                if val:
                    target = "schema" if key == "schema_name" else key
                    params[target] = val
        self._connect_params = params

        connect_args: dict[str, Any] = {
            "server_hostname": params["host"],
            "http_path": params["http_path"],
        }
        if params.get("catalog"):
            connect_args["catalog"] = params["catalog"]
        if params.get("schema"):
            connect_args["schema"] = params["schema"]

        # Auth method routing (HEX pattern: PAT -> OAuth M2M -> OAuth U2M)
        auth_method = params.get("auth_method", self._auth_method)

        if auth_method == "oauth_m2m":
            # OAuth Machine-to-Machine (service principal) — production-grade
            client_id = params.get("oauth_client_id", self._oauth_client_id)
            client_secret = params.get("oauth_client_secret", self._oauth_client_secret)
            if not client_id or not client_secret:
                raise RuntimeError(
                    "OAuth M2M requires client_id and client_secret. "
                    "Create a service principal in Databricks Account Console -> "
                    "User Management -> Service Principals."
                )
            try:
                from databricks.sdk.core import oauth_service_principal

                credentials_provider = oauth_service_principal(
                    host=f"https://{params['host']}",
                    client_id=client_id,
                    client_secret=client_secret,
                )
                connect_args["credentials_provider"] = credentials_provider
            except ImportError:
                # Fallback: try using databricks-sdk's Config
                try:
                    from databricks.sdk.core import Config

                    config = Config(
                        host=f"https://{params['host']}",
                        client_id=client_id,
                        client_secret=client_secret,
                    )
                    connect_args["credentials_provider"] = config.authenticate
                except ImportError:
                    raise RuntimeError("OAuth M2M requires databricks-sdk. Run: pip install databricks-sdk")
            logger.info("Databricks: using OAuth M2M (service principal) auth")
        elif auth_method == "oauth_u2m":
            # OAuth User-to-Machine — browser-based, for interactive use
            try:
                from databricks.sdk.core import Config

                config = Config(host=f"https://{params['host']}", auth_type="external-browser")
                connect_args["credentials_provider"] = config.authenticate
                logger.info("Databricks: using OAuth U2M (browser) auth")
            except ImportError:
                raise RuntimeError("OAuth U2M requires databricks-sdk. Run: pip install databricks-sdk")
        else:
            # PAT (Personal Access Token) — default
            if not params.get("access_token"):
                raise RuntimeError(
                    "PAT auth requires an access_token. "
                    "Generate one at: Workspace Settings -> User Settings -> Developer -> Access Tokens"
                )
            connect_args["access_token"] = params["access_token"]

        try:
            self._conn = databricks_sql.connect(**connect_args)
        except Exception as e:
            err_str = str(e).lower()
            if "unauthorized" in err_str or "403" in err_str or "401" in err_str:
                raise RuntimeError(f"Authentication failed: invalid credentials for {auth_method} auth") from e
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
            inner = conn_str[len("databricks://") :]

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
            from urllib.parse import parse_qs, unquote, urlparse

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

    async def _execute_impl(
        self, sql: str, params: list | None = None, timeout: int | None = None
    ) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")

        effective_timeout = timeout or self._query_timeout

        def _run():
            cursor = self._conn.cursor()
            # Databricks SQL Warehouses support SET for query timeout
            if effective_timeout:
                try:
                    cursor.execute(f"SET statement_timeout = {effective_timeout}")
                except Exception:
                    pass  # Best-effort — not all Databricks runtimes support this
            cursor.execute(sql, params or ())
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            cursor.close()
            return [dict(zip(columns, row)) for row in rows]

        try:
            return await self._run_in_thread(_run, timeout=effective_timeout, label="Databricks")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Databricks query error: {e}") from e

    async def _get_schema_impl(self) -> dict[str, Any]:
        import time as _time

        if self._conn is None:
            raise RuntimeError("Not connected")

        schema: dict[str, Any] = {}
        cursor = self._conn.cursor()

        # Prefer information_schema (Unity Catalog, Databricks SQL) — single query for all columns
        # Falls back to SHOW TABLES + DESCRIBE TABLE for legacy Hive metastore
        try:
            _col_sql = """
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
            """
            t0 = _time.monotonic()
            cursor.execute(_col_sql)
            _col_rows = cursor.fetchall()
            await self._audit_sql(_col_sql.strip(), len(_col_rows), (_time.monotonic() - t0) * 1000)
            for row in _col_rows:
                s_name = row[0]
                t_name = row[1]
                key = f"{s_name}.{t_name}"
                if key not in schema:
                    schema[key] = {
                        "schema": s_name,
                        "name": t_name,
                        "columns": [],
                        "foreign_keys": [],
                        "row_count": 0,
                    }
                schema[key]["columns"].append(
                    {
                        "name": row[2],
                        "type": row[3] or "string",
                        "nullable": row[4] == "YES" if row[4] else True,
                        "primary_key": False,
                        "comment": row[7] or "" if len(row) > 7 else "",
                    }
                )
            cursor.close()

            # Try to get table-level metadata (type, row counts)
            if schema:
                try:
                    cursor2 = self._conn.cursor()
                    _tables_sql = """
                        SELECT table_schema, table_name, table_type
                        FROM information_schema.tables
                        WHERE table_schema NOT IN ('information_schema')
                    """
                    t0 = _time.monotonic()
                    cursor2.execute(_tables_sql)
                    _tables_rows = cursor2.fetchall()
                    await self._audit_sql(_tables_sql.strip(), len(_tables_rows), (_time.monotonic() - t0) * 1000)
                    for row in _tables_rows:
                        key = f"{row[0]}.{row[1]}"
                        if key in schema:
                            tt = (row[2] or "TABLE").upper()
                            schema[key]["type"] = "view" if "VIEW" in tt else "table"
                    cursor2.close()
                except Exception:
                    pass

            # Primary keys via table_constraints + constraint_column_usage (Unity Catalog)
            try:
                pk_cursor = self._conn.cursor()
                _pk_sql = """
                    SELECT
                        tc.table_schema,
                        tc.table_name,
                        ccu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.constraint_column_usage ccu
                        ON tc.constraint_catalog = ccu.constraint_catalog
                        AND tc.constraint_schema = ccu.constraint_schema
                        AND tc.constraint_name = ccu.constraint_name
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                        AND tc.table_schema NOT IN ('information_schema')
                """
                t0 = _time.monotonic()
                pk_cursor.execute(_pk_sql)
                _pk_rows = pk_cursor.fetchall()
                await self._audit_sql(_pk_sql.strip(), len(_pk_rows), (_time.monotonic() - t0) * 1000)
                for row in _pk_rows:
                    key = f"{row[0]}.{row[1]}"
                    pk_col = row[2]
                    if key in schema:
                        for col in schema[key]["columns"]:
                            if col["name"] == pk_col:
                                col["primary_key"] = True
                pk_cursor.close()
            except Exception as e:
                import logging

                logging.getLogger(__name__).debug("PK query not supported: %s", e)

            # Foreign keys via referential_constraints (Unity Catalog)
            try:
                fk_cursor = self._conn.cursor()
                _fk_sql = """
                    SELECT
                        tc.table_schema AS fk_schema,
                        tc.table_name AS fk_table,
                        kcu.column_name AS fk_column,
                        ccu.table_schema AS pk_schema,
                        ccu.table_name AS pk_table,
                        ccu.column_name AS pk_column
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.constraint_schema = kcu.constraint_schema
                    JOIN information_schema.constraint_column_usage ccu
                        ON tc.constraint_name = ccu.constraint_name
                        AND tc.constraint_schema = ccu.constraint_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                        AND tc.table_schema NOT IN ('information_schema')
                """
                t0 = _time.monotonic()
                fk_cursor.execute(_fk_sql)
                _fk_rows = fk_cursor.fetchall()
                await self._audit_sql(_fk_sql.strip(), len(_fk_rows), (_time.monotonic() - t0) * 1000)
                for row in _fk_rows:
                    key = f"{row[0]}.{row[1]}"
                    if key in schema:
                        if "foreign_keys" not in schema[key]:
                            schema[key]["foreign_keys"] = []
                        schema[key]["foreign_keys"].append(
                            {
                                "column": row[2],
                                "references_schema": row[3],
                                "references_table": row[4],
                                "references_column": row[5],
                            }
                        )
                fk_cursor.close()
            except Exception as e:
                import logging

                logging.getLogger(__name__).debug("FK query not supported: %s", e)

            # Row counts via DESCRIBE DETAIL (Delta tables — batch up to 50 tables)
            tables_to_detail = [(k, v) for k, v in schema.items() if v.get("type") != "view"][:50]
            for key, table_data in tables_to_detail:
                try:
                    rc_cursor = self._conn.cursor()
                    safe_table = f"`{table_data['schema']}`.`{table_data['name']}`"
                    _detail_sql = f"DESCRIBE DETAIL {safe_table}"
                    t0 = _time.monotonic()
                    rc_cursor.execute(_detail_sql)
                    col_names = [d[0] for d in rc_cursor.description] if rc_cursor.description else []
                    detail = rc_cursor.fetchone()
                    await self._audit_sql(_detail_sql.strip(), 1 if detail else 0, (_time.monotonic() - t0) * 1000)
                    rc_cursor.close()
                    if detail and col_names:
                        row_dict = dict(zip(col_names, detail))
                        if "numFiles" in row_dict:
                            table_data["num_files"] = row_dict["numFiles"]
                        if "sizeInBytes" in row_dict:
                            size_bytes = row_dict["sizeInBytes"] or 0
                            table_data["size_mb"] = round(size_bytes / (1024 * 1024), 2)
                except Exception:
                    pass

            return schema
        except Exception as e:
            import logging

            logging.getLogger(__name__).info("information_schema not available, falling back to SHOW/DESCRIBE: %s", e)

        # Fallback: SHOW TABLES + DESCRIBE TABLE (legacy Hive metastore)
        try:
            _show_schemas_sql = "SHOW SCHEMAS"
            t0 = _time.monotonic()
            cursor.execute(_show_schemas_sql)
            _schemas_rows = cursor.fetchall()
            await self._audit_sql(_show_schemas_sql.strip(), len(_schemas_rows), (_time.monotonic() - t0) * 1000)
            schemas_list = [row[0] for row in _schemas_rows]
        except Exception:
            schemas_list = ["default"]

        for schema_name in schemas_list:
            if schema_name.lower() in ("information_schema",):
                continue
            try:
                _show_tables_sql = f"SHOW TABLES IN `{schema_name}`"
                t0 = _time.monotonic()
                cursor.execute(_show_tables_sql)
                tables = cursor.fetchall()
                await self._audit_sql(_show_tables_sql.strip(), len(tables), (_time.monotonic() - t0) * 1000)
            except Exception:
                continue

            for table_row in tables:
                table_name = table_row[1] if len(table_row) > 1 else table_row[0]
                key = f"{schema_name}.{table_name}"
                try:
                    _describe_sql = f"DESCRIBE TABLE `{schema_name}`.`{table_name}`"
                    t0 = _time.monotonic()
                    cursor.execute(_describe_sql)
                    col_rows = cursor.fetchall()
                    await self._audit_sql(_describe_sql.strip(), len(col_rows), (_time.monotonic() - t0) * 1000)
                    columns = []
                    for cr in col_rows:
                        col_name = cr[0]
                        col_type = cr[1] if len(cr) > 1 else "string"
                        comment = cr[2] if len(cr) > 2 else ""
                        if col_name.startswith("#") or col_name == "":
                            continue
                        columns.append(
                            {
                                "name": col_name,
                                "type": col_type,
                                "nullable": True,
                                "primary_key": False,
                                "comment": comment or "",
                            }
                        )
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

    async def _get_sample_values_impl(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values via single UNION ALL query (1 round trip)."""
        import time as _time

        if self._conn is None or not columns:
            return {}
        try:
            sql = self._build_sample_union_sql(table, columns, limit, quote="`")
            cursor = self._conn.cursor()
            t0 = _time.monotonic()
            cursor.execute(sql)
            rows = cursor.fetchall()
            await self._audit_sql(sql.strip(), len(rows), (_time.monotonic() - t0) * 1000)
            cursor.close()
            return self._parse_sample_union_result(rows)
        except Exception:
            # Fallback to per-column queries
            result: dict[str, list] = {}
            safe_table = self._quote_table(table)
            for col in columns[:20]:
                try:
                    cursor = self._conn.cursor()
                    safe_col = self._quote_identifier(col)
                    _col_sql = (
                        f"SELECT DISTINCT {safe_col} FROM {safe_table} WHERE {safe_col} IS NOT NULL LIMIT {limit}"
                    )
                    t0 = _time.monotonic()
                    cursor.execute(_col_sql)
                    rows = cursor.fetchall()
                    await self._audit_sql(_col_sql.strip(), len(rows), (_time.monotonic() - t0) * 1000)
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
