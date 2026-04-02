"""Microsoft SQL Server connector — pymssql backed.

Supports SQL Server 2016+, Azure SQL Database, Azure SQL Managed Instance.
Uses pymssql for synchronous operations wrapped in async context.
"""

from __future__ import annotations

from typing import Any

from .base import BaseConnector

try:
    import pymssql

    HAS_PYMSSQL = True
except ImportError:
    HAS_PYMSSQL = False


class MSSQLConnector(BaseConnector):
    def __init__(self):
        self._conn: pymssql.Connection | None = None
        self._connect_params: dict = {}
        self._ssl_config: dict | None = None

    def set_ssl_config(self, ssl_config: dict) -> None:
        self._ssl_config = ssl_config

    def set_credential_extras(self, extras: dict) -> None:
        if extras.get("ssl_config"):
            self.set_ssl_config(extras["ssl_config"])

    async def connect(self, connection_string: str) -> None:
        if not HAS_PYMSSQL:
            raise RuntimeError("pymssql not installed. Run: pip install pymssql")

        params = self._parse_connection_string(connection_string)
        self._connect_params = params

        connect_kwargs: dict = {
            "server": params.get("host", "localhost"),
            "port": str(params.get("port", "1433")),
            "user": params.get("user", ""),
            "password": params.get("password", ""),
            "database": params.get("database", "master"),
            "login_timeout": 15,
            "timeout": 30,
            "as_dict": True,
            "charset": "UTF-8",
        }

        # TLS encryption (Azure SQL requires it)
        if self._ssl_config and self._ssl_config.get("enabled"):
            connect_kwargs["tds_version"] = "7.3"
            connect_kwargs["conn_properties"] = "Encrypt=yes;TrustServerCertificate=yes"

        try:
            self._conn = pymssql.connect(**connect_kwargs)
        except pymssql.OperationalError as e:
            err_str = str(e).lower()
            if "login failed" in err_str:
                raise RuntimeError(f"Authentication failed: Login failed for user '{connect_kwargs.get('user', '')}'") from e
            elif "cannot open database" in err_str:
                raise RuntimeError(f"Database not found: Cannot open database '{connect_kwargs.get('database', '')}'") from e
            elif "connection refused" in err_str or "network" in err_str or "unable to connect" in err_str:
                raise RuntimeError(f"Connection failed: Cannot connect to SQL Server on '{connect_kwargs.get('server', '')}:{connect_kwargs.get('port', '1433')}'") from e
            raise RuntimeError(f"SQL Server connection error: {e}") from e

    def _parse_connection_string(self, conn_str: str) -> dict:
        """Parse mssql://user:pass@host:port/db or mssql+pymssql://... format."""
        from urllib.parse import urlparse, unquote

        s = conn_str
        for prefix in ("mssql+pymssql://", "mssql://", "sqlserver://"):
            if s.startswith(prefix):
                s = "mssql://" + s[len(prefix):]
                break

        parsed = urlparse(s)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 1433,
            "user": unquote(parsed.username or "sa"),
            "password": unquote(parsed.password or ""),
            "database": parsed.path.lstrip("/") if parsed.path else "master",
        }

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            cursor = self._conn.cursor(as_dict=True)
            if timeout:
                cursor.execute(f"SET LOCK_TIMEOUT {timeout * 1000}")
            cursor.execute(sql, tuple(params) if params else None)
            if cursor.description is None:
                return []
            rows = cursor.fetchall()
            cursor.close()
            return list(rows) if rows else []
        except pymssql.Error as e:
            raise RuntimeError(f"SQL Server query error: {e}") from e

    async def get_schema(self) -> dict[str, Any]:
        if self._conn is None:
            raise RuntimeError("Not connected")

        # Columns + primary keys in one query
        col_sql = """
            SELECT
                s.name AS table_schema,
                t.name AS table_name,
                c.name AS column_name,
                tp.name AS data_type,
                c.is_nullable,
                OBJECT_DEFINITION(c.default_object_id) AS column_default,
                CASE WHEN pk.column_id IS NOT NULL THEN 1 ELSE 0 END AS is_primary_key,
                ep.value AS column_comment,
                ep_t.value AS table_comment,
                p.rows AS row_count
            FROM sys.tables t
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            JOIN sys.columns c ON t.object_id = c.object_id
            JOIN sys.types tp ON c.user_type_id = tp.user_type_id
            LEFT JOIN (
                SELECT ic.object_id, ic.column_id
                FROM sys.index_columns ic
                JOIN sys.indexes i ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                WHERE i.is_primary_key = 1
            ) pk ON c.object_id = pk.object_id AND c.column_id = pk.column_id
            LEFT JOIN sys.extended_properties ep
                ON ep.major_id = c.object_id AND ep.minor_id = c.column_id AND ep.name = 'MS_Description'
            LEFT JOIN sys.extended_properties ep_t
                ON ep_t.major_id = t.object_id AND ep_t.minor_id = 0 AND ep_t.name = 'MS_Description'
            LEFT JOIN sys.partitions p ON t.object_id = p.object_id AND p.index_id IN (0, 1)
            WHERE s.name NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')
            ORDER BY s.name, t.name, c.column_id
        """

        # Foreign keys
        fk_sql = """
            SELECT
                OBJECT_SCHEMA_NAME(fk.parent_object_id) AS table_schema,
                OBJECT_NAME(fk.parent_object_id) AS table_name,
                COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS column_name,
                OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS referenced_schema,
                OBJECT_NAME(fk.referenced_object_id) AS referenced_table,
                COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS referenced_column
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
        """

        # Indexes
        idx_sql = """
            SELECT
                OBJECT_SCHEMA_NAME(i.object_id) AS table_schema,
                OBJECT_NAME(i.object_id) AS table_name,
                i.name AS index_name,
                i.is_unique,
                STRING_AGG(c.name, ', ') WITHIN GROUP (ORDER BY ic.key_ordinal) AS columns
            FROM sys.indexes i
            JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
            WHERE i.name IS NOT NULL
                AND OBJECT_SCHEMA_NAME(i.object_id) NOT IN ('sys', 'INFORMATION_SCHEMA')
            GROUP BY i.object_id, i.name, i.is_unique
        """

        def _fetch(query: str) -> list:
            try:
                cursor = self._conn.cursor(as_dict=True)
                cursor.execute(query)
                result = cursor.fetchall()
                cursor.close()
                return result
            except Exception:
                return []

        rows = _fetch(col_sql)
        fk_rows = _fetch(fk_sql)
        idx_rows = _fetch(idx_sql)

        # Build FK map
        foreign_keys: dict[str, list[dict]] = {}
        for r in fk_rows:
            key = f"{r['table_schema']}.{r['table_name']}"
            if key not in foreign_keys:
                foreign_keys[key] = []
            foreign_keys[key].append({
                "column": r["column_name"],
                "references_schema": r["referenced_schema"],
                "references_table": r["referenced_table"],
                "references_column": r["referenced_column"],
            })

        # Build index map
        indexes: dict[str, list[dict]] = {}
        for r in idx_rows:
            key = f"{r['table_schema']}.{r['table_name']}"
            if key not in indexes:
                indexes[key] = []
            indexes[key].append({
                "name": r["index_name"],
                "columns": r["columns"],
                "unique": bool(r["is_unique"]),
            })

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
                    "row_count": row.get("row_count", 0) or 0,
                    "description": str(row.get("table_comment", "") or ""),
                }
            schema[key]["columns"].append({
                "name": row["column_name"],
                "type": row["data_type"],
                "nullable": bool(row["is_nullable"]),
                "primary_key": bool(row["is_primary_key"]),
                "default": row.get("column_default"),
                "comment": str(row.get("column_comment", "") or ""),
            })
        return schema

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        if self._conn is None:
            return {}
        result: dict[str, list] = {}
        for col in columns[:20]:
            try:
                cursor = self._conn.cursor(as_dict=True)
                cursor.execute(
                    f"SELECT DISTINCT TOP {limit} [{col}] FROM {table} WHERE [{col}] IS NOT NULL"
                )
                rows = cursor.fetchall()
                cursor.close()
                values = [str(r[col]) for r in rows if r[col] is not None]
                if values:
                    result[col] = values
            except Exception:
                continue
        return result

    async def health_check(self) -> bool:
        if self._conn is None:
            return False
        try:
            cursor = self._conn.cursor(as_dict=True)
            cursor.execute("SELECT 1 AS ok")
            cursor.fetchall()
            cursor.close()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
