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
        self._connect_kwargs: dict = {}
        self._connect_params: dict = {}
        self._ssl_config: dict | None = None
        self._temp_files: list[str] = []

    def set_ssl_config(self, ssl_config: dict) -> None:
        """Set SSL configuration for the connection."""
        self._ssl_config = ssl_config

    def set_credential_extras(self, extras: dict) -> None:
        """Extract SSL config from credential extras."""
        if extras.get("ssl_config"):
            self.set_ssl_config(extras["ssl_config"])

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
                self._temp_files.append(ca_file.name)
            if self._ssl_config.get("client_cert"):
                cert_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
                cert_file.write(self._ssl_config["client_cert"].encode())
                cert_file.close()
                ssl_dict["cert"] = cert_file.name
                self._temp_files.append(cert_file.name)
            if self._ssl_config.get("client_key"):
                key_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
                key_file.write(self._ssl_config["client_key"].encode())
                key_file.close()
                ssl_dict["key"] = key_file.name
                self._temp_files.append(key_file.name)

            if ssl_dict:
                connect_kwargs["ssl"] = ssl_dict
            else:
                # SSL enabled but no certs — enforce SSL with no cert verification
                connect_kwargs["ssl"] = {"check_hostname": False}

        # Store kwargs for reconnection
        self._connect_kwargs = connect_kwargs

        try:
            self._conn = pymysql.connect(**connect_kwargs)
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

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            self._ensure_connected()
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
        # PyMySQL is not thread-safe for concurrent queries on the same connection,
        # but we can batch queries to reduce round trips
        import asyncio

        def _fetch(query: str) -> list:
            try:
                self._ensure_connected()
                with self._conn.cursor() as cursor:
                    cursor.execute(query)
                    return cursor.fetchall()
            except Exception:
                return []

        # Run queries sequentially (PyMySQL isn't thread-safe for a single connection)
        rows = _fetch(sql)
        fk_rows = _fetch(fk_sql)
        idx_rows = _fetch(idx_sql)
        card_rows = _fetch(cardinality_sql)

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
        """Get sample distinct values via single UNION ALL query (1 round trip)."""
        if self._conn is None or not columns:
            return {}
        self._ensure_connected()
        try:
            sql = self._build_sample_union_sql(table, columns, limit, quote='`')
            with self._conn.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()
            return self._parse_sample_union_result(rows)
        except Exception:
            # Fallback to per-column queries
            result: dict[str, list] = {}
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
            self._ensure_connected()
            with self._conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except Exception:
            return False

    def _ensure_connected(self) -> None:
        """Ensure connection is alive, reconnect if needed."""
        if self._conn is None:
            if self._connect_kwargs:
                self._conn = pymysql.connect(**self._connect_kwargs)
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
            else:
                raise RuntimeError("Connection lost and cannot reconnect")

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
        # Cleanup temp SSL cert files
        import os
        for f in self._temp_files:
            try:
                os.unlink(f)
            except OSError:
                pass
        self._temp_files.clear()
