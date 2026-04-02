"""Base connector interface — every DB connector implements this.

Provides shared infrastructure that was previously duplicated across 11 connectors:
- SSL temp file management
- asyncio.to_thread wrapper with timeout
- health_check / _ensure_connected defaults
- Identifier quoting for SQL injection prevention
- IAM token generation (AWS RDS)
- close() with temp file cleanup
- set_credential_extras() with common timeout/SSL parsing
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    """Abstract base class for all database connectors.

    Subclasses MUST implement: connect(), execute(), get_schema().
    Subclasses MAY override: health_check(), close(), _ping(),
        _set_connector_specific_extras(), _identifier_quote.
    """

    def __init__(self) -> None:
        self._conn: Any = None
        self._ssl_config: dict | None = None
        self._temp_files: list[str] = []
        self._connection_timeout: int = 15
        self._query_timeout: int = 30

    # ─── Abstract methods (must implement) ────────────────────────────

    @abstractmethod
    async def connect(self, connection_string: str) -> None:
        """Open connection pool."""

    @abstractmethod
    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        """Execute query and return rows as list of dicts."""

    @abstractmethod
    async def get_schema(self) -> dict[str, Any]:
        """Return schema info: tables with columns."""

    # ─── Identifier quoting (SQL injection prevention) ────────────────

    @property
    def _identifier_quote(self) -> str:
        """Character used to quote identifiers. Override per connector.

        '"' for postgres, redshift, trino, duckdb, snowflake, bigquery
        '`' for mysql, clickhouse, databricks
        '[' for mssql, sqlite
        """
        return '"'

    def _quote_identifier(self, name: str) -> str:
        """Quote a single identifier to prevent SQL injection."""
        q = self._identifier_quote
        if q == "[":
            return "[" + name.replace("]", "]]") + "]"
        return q + name.replace(q, q + q) + q

    def _quote_table(self, table: str) -> str:
        """Quote a possibly schema-qualified table name (e.g., 'schema.table')."""
        parts = table.split(".")
        return ".".join(self._quote_identifier(p) for p in parts)

    # ─── SSL temp file management ─────────────────────────────────────

    def _write_ssl_temp_file(self, content: str, suffix: str = ".pem", chmod: int | None = None) -> str:
        """Write PEM content to a temp file, track for cleanup. Returns file path."""
        f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        f.write(content.encode())
        f.close()
        if chmod is not None:
            os.chmod(f.name, chmod)
        self._temp_files.append(f.name)
        return f.name

    def _write_ssl_files(self) -> dict[str, str]:
        """Write all SSL config PEM strings to temp files. Returns {role: path} dict.

        Handles ca_cert, client_cert, client_key from self._ssl_config.
        """
        paths: dict[str, str] = {}
        if not self._ssl_config:
            return paths
        if self._ssl_config.get("ca_cert"):
            paths["ca"] = self._write_ssl_temp_file(self._ssl_config["ca_cert"])
        if self._ssl_config.get("client_cert"):
            paths["cert"] = self._write_ssl_temp_file(self._ssl_config["client_cert"])
        if self._ssl_config.get("client_key"):
            paths["key"] = self._write_ssl_temp_file(self._ssl_config["client_key"], chmod=0o600)
        return paths

    def _cleanup_temp_files(self) -> None:
        """Remove all tracked temporary files."""
        for f in self._temp_files:
            try:
                os.unlink(f)
            except OSError:
                pass
        self._temp_files.clear()

    # ─── Async thread wrapper ─────────────────────────────────────────

    async def _run_in_thread(self, fn, timeout: int | None = None, label: str = "Query") -> Any:
        """Run a blocking function in a thread with timeout.

        Used by sync connectors (pymysql, pymssql, psycopg2, etc.) to avoid
        blocking the FastAPI event loop.

        Args:
            fn: Callable to run in thread.
            timeout: Timeout in seconds. Uses self._query_timeout if None.
            label: Label for error messages (e.g., "MySQL", "Redshift").
        """
        effective = timeout or self._query_timeout
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn),
                timeout=effective + 5 if effective else None,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(f"{label} query timed out after {effective}s")

    # ─── Health check (default implementation) ────────────────────────

    async def health_check(self) -> bool:
        """Return True if connection is healthy. Default: try _ping()."""
        if self._conn is None:
            return False
        try:
            await self._do_ping()
            return True
        except Exception:
            return False

    async def _do_ping(self) -> None:
        """Execute a trivial query to verify connection. Override for async connectors."""
        self._ping()

    def _ping(self) -> None:
        """Synchronous ping. Override in subclasses. Default: SELECT 1 via cursor."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchall()
        cursor.close()

    # ─── Ensure connected (default implementation) ────────────────────

    def _ensure_connected(self) -> None:
        """Verify connection is alive; raise RuntimeError if lost.

        Default: try _ping(), on failure close and raise.
        Override for reconnect logic (e.g., MySQL).
        """
        if self._conn is None:
            raise RuntimeError("Not connected")
        try:
            self._ping()
        except Exception:
            self._safe_close_sync()
            raise RuntimeError("Connection lost — please reconnect")

    def _safe_close_sync(self) -> None:
        """Safely close connection without raising."""
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    # ─── Close (default implementation) ───────────────────────────────

    async def close(self) -> None:
        """Close connection and clean up temp files."""
        if self._conn:
            self._conn.close()
            self._conn = None
        self._cleanup_temp_files()

    # ─── Credential extras (common parsing + hook) ────────────────────

    def set_credential_extras(self, extras: dict) -> None:
        """Set structured credential data for the connection.

        Handles common fields (SSL, timeouts), then delegates to
        _set_connector_specific_extras() for DB-specific fields.
        """
        if extras.get("ssl_config"):
            self._ssl_config = extras["ssl_config"]
        if extras.get("connection_timeout"):
            self._connection_timeout = extras["connection_timeout"]
        if extras.get("query_timeout"):
            self._query_timeout = extras["query_timeout"]
        self._set_connector_specific_extras(extras)

    def _set_connector_specific_extras(self, extras: dict) -> None:
        """Override in subclasses for connector-specific extras."""
        pass

    # ─── IAM auth (shared by postgres, mysql, redshift) ───────────────

    @staticmethod
    def _generate_rds_iam_token(
        region: str, host: str, port: int, username: str,
        access_key: str | None = None, secret_key: str | None = None,
    ) -> str:
        """Generate a short-lived RDS IAM auth token (valid 15 minutes)."""
        try:
            import boto3
        except ImportError:
            raise RuntimeError("boto3 not installed. Run: pip install boto3")

        kwargs: dict[str, Any] = {"region_name": region}
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key

        client = boto3.client("rds", **kwargs)
        return client.generate_db_auth_token(
            DBHostname=host, Port=port, DBUsername=username, Region=region
        )

    # ─── Sample values (shared UNION ALL + fallback) ──────────────────

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Return sample distinct values for specified columns.

        Default implementation: no-op. Override in subclasses.
        """
        return {}

    @staticmethod
    def _build_sample_union_sql(
        table: str, columns: list[str], limit: int = 5, quote: str = '"'
    ) -> str:
        """Build a UNION ALL query to fetch sample values in one round trip.

        The table name is quoted using the same quote character for injection safety.
        """
        parts = []
        if quote == "[":
            q_open, q_close = "[", "]"
        else:
            q_open, q_close = quote, quote

        # Quote the table name parts for injection safety
        safe_table_parts = []
        for tp in table.split("."):
            if q_open == "[":
                safe_table_parts.append("[" + tp.replace("]", "]]") + "]")
            else:
                safe_table_parts.append(q_open + tp.replace(q_close, q_close + q_close) + q_close)
        safe_table = ".".join(safe_table_parts)

        for i, col in enumerate(columns[:20]):
            safe_name = col.replace("'", "''")
            safe_id = col.replace(q_close, q_close + q_close) if q_close else col
            parts.append(
                f"SELECT '{safe_name}' AS _col, CAST({q_open}{safe_id}{q_close} AS VARCHAR) AS _val "
                f"FROM (SELECT DISTINCT {q_open}{safe_id}{q_close} FROM {safe_table} WHERE {q_open}{safe_id}{q_close} IS NOT NULL LIMIT {limit}) t{i}"
            )
        return "\n UNION ALL \n".join(parts)

    @staticmethod
    def _parse_sample_union_result(rows: list[dict] | list[tuple]) -> dict[str, list]:
        """Parse UNION ALL sample query result into {column: [values]} dict."""
        result: dict[str, list] = {}
        for row in rows:
            if isinstance(row, dict):
                col, val = row.get("_col", ""), row.get("_val", "")
            else:
                col, val = row[0], row[1]
            if col and val is not None:
                if col not in result:
                    result[col] = []
                result[col].append(str(val))
        return result

    # ─── URL parsing helper ───────────────────────────────────────────

    @staticmethod
    def _parse_url(conn_str: str, default_port: int = 5432,
                   default_user: str = "", default_db: str = "") -> dict:
        """Parse a standard database URL into components."""
        from urllib.parse import urlparse, unquote
        parsed = urlparse(conn_str)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or default_port,
            "user": unquote(parsed.username or default_user),
            "password": unquote(parsed.password or ""),
            "database": parsed.path.lstrip("/") if parsed.path else default_db,
        }
