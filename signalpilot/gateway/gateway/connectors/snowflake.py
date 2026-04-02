"""Snowflake connector — snowflake-connector-python backed.

Supports account/user/password auth, key-pair auth, and warehouse/role configuration.
Tier 1 connector matching HEX's Snowflake integration.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseConnector

logger = logging.getLogger(__name__)

try:
    import snowflake.connector

    HAS_SNOWFLAKE = True
except ImportError:
    HAS_SNOWFLAKE = False


class SnowflakeConnector(BaseConnector):
    def __init__(self):
        self._conn = None
        self._connect_params: dict = {}
        self._credential_extras: dict = {}

    def set_credential_extras(self, extras: dict) -> None:
        """Store structured credential data for connection."""
        self._credential_extras = extras

    def _load_private_key(self, key_pem: str, passphrase: str | None = None) -> bytes:
        """Load a PEM-encoded private key and return DER bytes for Snowflake key-pair auth."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend

        pwd = passphrase.encode() if passphrase else None
        private_key = serialization.load_pem_private_key(
            key_pem.encode(),
            password=pwd,
            backend=default_backend(),
        )
        return private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    async def connect(self, connection_string: str) -> None:
        if not HAS_SNOWFLAKE:
            raise RuntimeError(
                "snowflake-connector-python not installed. "
                "Run: pip install snowflake-connector-python"
            )
        params = self._parse_connection(connection_string)
        self._connect_params = params

        # Merge in credential_extras (takes precedence — they have the actual secrets)
        if self._credential_extras:
            for key in ("account", "username", "password", "warehouse", "schema_name", "role",
                        "private_key", "private_key_passphrase"):
                val = self._credential_extras.get(key)
                if val:
                    # Map schema_name -> schema for snowflake-connector
                    target_key = "schema" if key == "schema_name" else key
                    # Map username -> user for snowflake-connector
                    target_key = "user" if key == "username" else target_key
                    params[target_key] = val

        connect_args = {
            "account": params.get("account", ""),
            "user": params.get("user", ""),
            "login_timeout": 15,
            "network_timeout": 30,
        }

        # Key-pair auth takes precedence over password auth (HEX pattern)
        if params.get("private_key"):
            try:
                pk_bytes = self._load_private_key(
                    params["private_key"],
                    params.get("private_key_passphrase"),
                )
                connect_args["private_key"] = pk_bytes
            except Exception as e:
                raise RuntimeError(f"Invalid private key: {e}") from e
        elif params.get("password"):
            connect_args["password"] = params["password"]

        if params.get("database"):
            connect_args["database"] = params["database"]
        if params.get("warehouse"):
            connect_args["warehouse"] = params["warehouse"]
        if params.get("schema"):
            connect_args["schema"] = params["schema"]
        if params.get("role"):
            connect_args["role"] = params["role"]

        try:
            self._conn = snowflake.connector.connect(**connect_args)
        except snowflake.connector.errors.DatabaseError as e:
            err_str = str(e).lower()
            if "incorrect username or password" in err_str or "authentication" in err_str:
                raise RuntimeError(f"Authentication failed: {str(e).split(chr(10))[0]}") from e
            elif "account" in err_str and ("not found" in err_str or "invalid" in err_str):
                raise RuntimeError(f"Account not found: verify account identifier '{params.get('account', '')}'") from e
            elif "warehouse" in err_str and "does not exist" in err_str:
                raise RuntimeError(f"Warehouse not found: '{params.get('warehouse', '')}'") from e
            raise RuntimeError(f"Snowflake connection error: {str(e).split(chr(10))[0]}") from e
        except Exception as e:
            err_str = str(e).lower()
            if "timeout" in err_str or "timed out" in err_str:
                raise RuntimeError(f"Connection timed out: {e}") from e
            raise RuntimeError(f"Snowflake connection error: {e}") from e

    def _parse_connection(self, conn_str: str) -> dict:
        """Parse Snowflake connection strings.

        Supports:
        - snowflake://account|user|pass|db|wh|schema|role (legacy SignalPilot format)
        - snowflake://user:pass@account/db/schema?warehouse=WH&role=ROLE (standard URL)
        - account identifier only (for use with credential_extras)
        """
        if conn_str.startswith("snowflake://"):
            inner = conn_str[len("snowflake://"):]

            # Check for pipe-delimited format (legacy)
            if "|" in inner:
                parts = inner.split("|")
                return {
                    "account": parts[0] if len(parts) > 0 else "",
                    "user": parts[1] if len(parts) > 1 else "",
                    "password": parts[2] if len(parts) > 2 else "",
                    "database": parts[3] if len(parts) > 3 else "",
                    "warehouse": parts[4] if len(parts) > 4 else "",
                    "schema": parts[5] if len(parts) > 5 else "",
                    "role": parts[6] if len(parts) > 6 else "",
                }

            # Standard URL format: snowflake://user:pass@account/db/schema?warehouse=WH&role=ROLE
            from urllib.parse import urlparse, unquote, parse_qs

            parsed = urlparse(conn_str)
            path_parts = [p for p in (parsed.path or "").split("/") if p]
            query = parse_qs(parsed.query or "")

            return {
                "account": parsed.hostname or "",
                "user": unquote(parsed.username or ""),
                "password": unquote(parsed.password or ""),
                "database": path_parts[0] if len(path_parts) > 0 else "",
                "schema": path_parts[1] if len(path_parts) > 1 else "",
                "warehouse": query.get("warehouse", [""])[0],
                "role": query.get("role", [""])[0],
            }

        # Fallback: treat as account identifier (credential_extras will fill the rest)
        return {"account": conn_str, "user": "", "password": ""}

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            cursor = self._conn.cursor(snowflake.connector.DictCursor)
            if timeout:
                cursor.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {timeout}")
            cursor.execute(sql, params or ())
            rows = cursor.fetchall()
            cursor.close()
            return list(rows) if rows else []
        except snowflake.connector.Error as e:
            raise RuntimeError(f"Snowflake query error: {e}") from e

    async def get_schema(self) -> dict[str, Any]:
        if self._conn is None:
            raise RuntimeError("Not connected")

        import asyncio

        # Use INFORMATION_SCHEMA for comprehensive metadata
        col_sql = """
            SELECT
                TABLE_SCHEMA,
                TABLE_NAME,
                COLUMN_NAME,
                DATA_TYPE,
                IS_NULLABLE,
                COLUMN_DEFAULT,
                COMMENT
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA NOT IN ('INFORMATION_SCHEMA')
            ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
        """
        rc_sql = """
            SELECT TABLE_SCHEMA, TABLE_NAME, ROW_COUNT
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA NOT IN ('INFORMATION_SCHEMA')
                AND TABLE_TYPE = 'BASE TABLE'
        """
        fk_sql = """
            SELECT
                FK_SCHEMA_NAME, FK_TABLE_NAME, FK_COLUMN_NAME,
                PK_SCHEMA_NAME, PK_TABLE_NAME, PK_COLUMN_NAME
            FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                ON rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                AND rc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA
            WHERE rc.CONSTRAINT_SCHEMA NOT IN ('INFORMATION_SCHEMA')
        """
        pk_sql = """
            SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE ccu
                USING (CONSTRAINT_CATALOG, CONSTRAINT_SCHEMA, CONSTRAINT_NAME)
            WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                AND tc.TABLE_SCHEMA NOT IN ('INFORMATION_SCHEMA')
        """

        # Clustering keys — SHOW TABLES returns cluster_by (not in information_schema)
        # Run as a 5th parallel query
        cluster_sql = "SHOW TABLES IN DATABASE"

        # Run all metadata queries concurrently via thread pool (5 parallel queries)
        def _fetch(query: str, label: str = "") -> list:
            try:
                cursor = self._conn.cursor(snowflake.connector.DictCursor)
                cursor.execute(query)
                result = cursor.fetchall()
                cursor.close()
                return result
            except Exception as e:
                logger.info("Snowflake metadata query failed (%s): %s", label, e)
                return []

        rows, rc_rows, fk_rows_raw, pk_rows, cluster_rows = await asyncio.gather(
            asyncio.to_thread(_fetch, col_sql, "columns"),
            asyncio.to_thread(_fetch, rc_sql, "row_counts"),
            asyncio.to_thread(_fetch, fk_sql, "foreign_keys"),
            asyncio.to_thread(_fetch, pk_sql, "primary_keys"),
            asyncio.to_thread(_fetch, cluster_sql, "clustering"),
        )

        # Build row count map
        row_counts: dict[str, int] = {}
        for r in rc_rows:
            key = f"{r['TABLE_SCHEMA']}.{r['TABLE_NAME']}"
            row_counts[key] = r.get("ROW_COUNT", 0) or 0

        # Build FK map
        foreign_keys: dict[str, list[dict]] = {}
        for r in fk_rows_raw:
            key = f"{r['FK_SCHEMA_NAME']}.{r['FK_TABLE_NAME']}"
            if key not in foreign_keys:
                foreign_keys[key] = []
            foreign_keys[key].append({
                "column": r["FK_COLUMN_NAME"],
                "references_schema": r["PK_SCHEMA_NAME"],
                "references_table": r["PK_TABLE_NAME"],
                "references_column": r["PK_COLUMN_NAME"],
            })

        # Build clustering key map from SHOW TABLES result
        clustering_keys: dict[str, str] = {}
        for r in cluster_rows:
            # SHOW TABLES returns: name, schema_name, cluster_by, rows, bytes, ...
            schema_name = r.get("schema_name", "")
            table_name = r.get("name", "")
            cluster_by = r.get("cluster_by", "")
            if schema_name and table_name and cluster_by:
                clustering_keys[f"{schema_name}.{table_name}"] = cluster_by

        schema: dict[str, Any] = {}
        for row in rows:
            key = f"{row['TABLE_SCHEMA']}.{row['TABLE_NAME']}"
            if key not in schema:
                table_entry: dict[str, Any] = {
                    "schema": row["TABLE_SCHEMA"],
                    "name": row["TABLE_NAME"],
                    "columns": [],
                    "foreign_keys": foreign_keys.get(key, []),
                    "row_count": row_counts.get(key, 0),
                }
                cluster_key = clustering_keys.get(key, "")
                if cluster_key:
                    table_entry["clustering_key"] = cluster_key
                schema[key] = table_entry
            schema[key]["columns"].append({
                "name": row["COLUMN_NAME"],
                "type": row["DATA_TYPE"],
                "nullable": row["IS_NULLABLE"] == "YES",
                "primary_key": False,
                "comment": row.get("COMMENT", ""),
            })

        # Enrich with primary key info (already fetched in parallel)
        pk_set = {
            (r["TABLE_SCHEMA"], r["TABLE_NAME"], r["COLUMN_NAME"]) for r in pk_rows
        }
        for table_data in schema.values():
            for col in table_data["columns"]:
                if (table_data["schema"], table_data["name"], col["name"]) in pk_set:
                    col["primary_key"] = True

        return schema

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values for schema linking optimization."""
        if self._conn is None:
            return {}
        result: dict[str, list] = {}
        for col in columns[:20]:
            try:
                cursor = self._conn.cursor(snowflake.connector.DictCursor)
                cursor.execute(
                    f'SELECT DISTINCT "{col}" FROM {table} WHERE "{col}" IS NOT NULL LIMIT {limit}'
                )
                rows = cursor.fetchall()
                cursor.close()
                values = [str(r[col]) for r in rows if r.get(col) is not None]
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
