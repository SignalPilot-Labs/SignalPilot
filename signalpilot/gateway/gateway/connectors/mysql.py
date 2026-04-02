"""MySQL connector — PyMySQL/aiomysql-backed.

Supports MySQL 5.7+, MariaDB 10.2+, and cloud-managed instances (RDS, Cloud SQL, PlanetScale).
Uses PyMySQL for synchronous operations wrapped in async context.
"""

from __future__ import annotations

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
        self._conn: pymysql.Connection | None = None
        self._connect_params: dict = {}
        self._ssl_config: dict | None = None

    def set_ssl_config(self, ssl_config: dict) -> None:
        """Set SSL configuration for the connection."""
        self._ssl_config = ssl_config

    async def connect(self, connection_string: str) -> None:
        if not HAS_PYMYSQL:
            raise RuntimeError("pymysql not installed. Run: pip install pymysql")

        params = self._parse_connection_string(connection_string)
        self._connect_params = params

        connect_kwargs: dict = {
            "host": params.get("host", "localhost"),
            "port": int(params.get("port", 3306)),
            "user": params.get("user", "root"),
            "password": params.get("password", ""),
            "database": params.get("database", ""),
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,
            "connect_timeout": 10,
            "read_timeout": 30,
            "autocommit": True,
        }

        # SSL support — pymysql uses ssl dict with ca/cert/key paths or content
        if self._ssl_config and self._ssl_config.get("enabled"):
            import ssl as ssl_module
            import tempfile
            import os

            ssl_ctx = ssl_module.create_default_context()

            # Write PEM content to temp files if provided as strings
            ssl_dict: dict = {}
            if self._ssl_config.get("ca_cert"):
                ca_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
                ca_file.write(self._ssl_config["ca_cert"].encode())
                ca_file.close()
                ssl_dict["ca"] = ca_file.name
            if self._ssl_config.get("client_cert"):
                cert_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
                cert_file.write(self._ssl_config["client_cert"].encode())
                cert_file.close()
                ssl_dict["cert"] = cert_file.name
            if self._ssl_config.get("client_key"):
                key_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
                key_file.write(self._ssl_config["client_key"].encode())
                key_file.close()
                ssl_dict["key"] = key_file.name

            if ssl_dict:
                connect_kwargs["ssl"] = ssl_dict
            else:
                # SSL enabled but no certs — use basic SSL
                connect_kwargs["ssl"] = {"ssl": True}

        self._conn = pymysql.connect(**connect_kwargs)

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

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            self._conn.ping(reconnect=True)
            with self._conn.cursor() as cursor:
                if timeout:
                    cursor.execute(f"SET SESSION max_execution_time = {timeout * 1000}")
                cursor.execute(sql, params or ())
                rows = cursor.fetchall()
                return list(rows) if rows else []
        except pymysql.Error as e:
            raise RuntimeError(f"MySQL query error: {e}") from e

    async def get_schema(self) -> dict[str, Any]:
        if self._conn is None:
            raise RuntimeError("Not connected")

        # Columns + primary keys + comments
        sql = """
            SELECT
                t.TABLE_SCHEMA,
                t.TABLE_NAME,
                t.TABLE_COMMENT,
                t.TABLE_ROWS,
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
                AND t.TABLE_TYPE = 'BASE TABLE'
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
        # Index metadata — helps Spider2.0 agent plan optimal queries
        idx_sql = """
            SELECT
                TABLE_SCHEMA, TABLE_NAME, INDEX_NAME, NON_UNIQUE,
                GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS columns
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
            GROUP BY TABLE_SCHEMA, TABLE_NAME, INDEX_NAME, NON_UNIQUE
        """
        # Column cardinality from index statistics
        cardinality_sql = """
            SELECT
                TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, CARDINALITY
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
                AND SEQ_IN_INDEX = 1
        """
        with self._conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
            cursor.execute(fk_sql)
            fk_rows = cursor.fetchall()
            cursor.execute(idx_sql)
            idx_rows = cursor.fetchall()
            cursor.execute(cardinality_sql)
            card_rows = cursor.fetchall()

        # Build cardinality map
        cardinality: dict[str, int] = {}
        for r in card_rows:
            card_key = f"{r['TABLE_SCHEMA']}.{r['TABLE_NAME']}.{r['COLUMN_NAME']}"
            # Keep the highest cardinality for a column (most selective index)
            existing = cardinality.get(card_key, 0)
            if r.get("CARDINALITY") and (r["CARDINALITY"] or 0) > existing:
                cardinality[card_key] = r["CARDINALITY"]

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
                schema[key] = {
                    "schema": row["TABLE_SCHEMA"],
                    "name": row["TABLE_NAME"],
                    "columns": [],
                    "foreign_keys": foreign_keys.get(key, []),
                    "indexes": indexes.get(key, []),
                    "row_count": row.get("TABLE_ROWS", 0),
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

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Get sample distinct values for schema linking optimization."""
        if self._conn is None:
            return {}
        result: dict[str, list] = {}
        self._conn.ping(reconnect=True)
        for col in columns[:20]:
            try:
                with self._conn.cursor() as cursor:
                    cursor.execute(
                        f"SELECT DISTINCT `{col}` FROM {table} WHERE `{col}` IS NOT NULL LIMIT {limit}"
                    )
                    rows = cursor.fetchall()
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
            self._conn.ping(reconnect=True)
            with self._conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
