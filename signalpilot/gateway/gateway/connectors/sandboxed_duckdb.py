"""Sandboxed DuckDB connector — executes queries via the sandbox manager.

Used for local DuckDB files that live on the host filesystem. The sandbox
manager has access to the host FS and can symlink files into the gVisor
sandbox. Queries are wrapped in Python code, sent to the sandbox, and
results are returned as JSON.

This connector implements the same BaseConnector interface as the direct
DuckDB connector, so the rest of the gateway (governance, schema cache,
pool manager) works transparently.
"""

from __future__ import annotations

import json
import logging
import textwrap
from typing import Any

from .base import BaseConnector

logger = logging.getLogger(__name__)

# The sandbox path where the DuckDB file is mounted
_SANDBOX_DB_PATH = "data/db.duckdb"  # Relative to workdir (cwd)


def _build_query_code(sql: str, db_path: str = _SANDBOX_DB_PATH) -> str:
    """Build Python code that executes a SQL query and prints JSON results."""
    escaped_sql = sql.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
    return (
        "import duckdb, json, datetime, decimal\n"
        "def _serialize(obj):\n"
        "    if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)): return obj.isoformat()\n"
        "    if isinstance(obj, datetime.timedelta): return str(obj)\n"
        "    if isinstance(obj, decimal.Decimal): return float(obj)\n"
        "    if isinstance(obj, bytes): return obj.hex()\n"
        "    return str(obj)\n"
        f"conn = duckdb.connect('{db_path}', read_only=True)\n"
        "try:\n"
        f"    result = conn.execute('{escaped_sql}')\n"
        "    columns = [desc[0] for desc in result.description]\n"
        "    rows = [dict(zip(columns, row)) for row in result.fetchall()]\n"
        "    print(json.dumps({'columns': columns, 'rows': rows}, default=_serialize))\n"
        "finally:\n"
        "    conn.close()\n"
    )


def _build_schema_code(db_path: str = _SANDBOX_DB_PATH) -> str:
    """Build Python code that introspects the DuckDB schema and prints JSON."""
    return textwrap.dedent(f"""\
        import duckdb, json
        conn = duckdb.connect('{db_path}', read_only=True)
        try:
            tables = conn.execute(\"\"\"
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY table_schema, table_name
            \"\"\").fetchall()

            schema = {{}}
            for table_schema, table_name in tables:
                key = f"{{table_schema}}.{{table_name}}"
                cols_result = conn.execute(\"\"\"
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = ? AND table_name = ?
                    ORDER BY ordinal_position
                \"\"\", [table_schema, table_name]).fetchall()

                columns = []
                for col_name, col_type, nullable in cols_result:
                    columns.append({{
                        "name": col_name,
                        "type": col_type,
                        "nullable": nullable == "YES",
                    }})

                # Get row count
                try:
                    count = conn.execute(
                        f'SELECT COUNT(*) FROM "{{table_schema}}"."{{table_name}}"'
                    ).fetchone()[0]
                except Exception:
                    count = None

                schema[key] = {{
                    "schema": table_schema,
                    "name": table_name,
                    "columns": columns,
                    "row_count": count,
                }}

            print(json.dumps(schema))
        finally:
            conn.close()
    """)


class SandboxedDuckDBConnector(BaseConnector):
    """DuckDB connector that executes queries via the sandbox manager.

    The host_path is the path to the DuckDB file on the host filesystem.
    Queries are sent to the sandbox manager which mounts the file and
    executes DuckDB Python code in gVisor isolation.
    """

    def __init__(self) -> None:
        super().__init__()
        self._host_path: str = ""
        self._sandbox_client = None

    async def connect(self, connection_string: str) -> None:
        """Store the host path. Actual connection happens per-query in the sandbox.

        Handles path translation: Windows paths (C:\\Users\\xxx\\...) are mapped
        to the sandbox's host mount at /host-data/... The sandbox container mounts
        the user's home directory at /host-data.
        """
        self._host_path = self._translate_path(connection_string)
        logger.info("SandboxedDuckDB: translated path → %s", self._host_path)
        # Lazily get sandbox client
        if self._sandbox_client is None:
            try:
                from ..api.deps import get_sandbox_client

                self._sandbox_client = get_sandbox_client()
            except Exception:
                # During test_credentials, sandbox client may not be initialized yet.
                import os

                from ..sandbox_client import SandboxClient

                url = os.environ.get("SP_SANDBOX_MANAGER_URL", "http://localhost:8180")
                self._sandbox_client = SandboxClient(base_url=url)
                logger.info("SandboxedDuckDB: created fallback sandbox client at %s", url)

    @staticmethod
    def _translate_path(path: str) -> str:
        """Translate a host path to the sandbox mount path."""
        import re

        # Windows path: C:\Users\username\... → /host-data/...
        win_match = re.match(r"^[A-Za-z]:[/\\]Users[/\\]([^/\\]+)[/\\]?(.*)", path)
        if win_match:
            remainder = win_match.group(2).replace("\\", "/")
            return f"/host-data/{remainder}" if remainder else "/host-data"
        # Unix path: /home/username/... → /host-data/...
        unix_match = re.match(r"^/home/([^/]+)/?(.*)", path)
        if unix_match:
            remainder = unix_match.group(2)
            return f"/host-data/{remainder}" if remainder else "/host-data"
        # macOS: /Users/username/... → /host-data/...
        mac_match = re.match(r"^/Users/([^/]+)/?(.*)", path)
        if mac_match:
            remainder = mac_match.group(2)
            return f"/host-data/{remainder}" if remainder else "/host-data"
        # Already a sandbox path or other — use as-is
        return path

    def set_sandbox_client(self, client) -> None:
        """Set the sandbox client directly (for use outside FastAPI deps)."""
        self._sandbox_client = client

    def _get_mounts(self) -> list[dict]:
        return [{"host_path": self._host_path, "sandbox_path": _SANDBOX_DB_PATH}]

    async def _run_sandboxed(self, code: str, timeout: int = 30) -> dict:
        """Execute Python code in sandbox with the DuckDB file mounted."""
        if not self._sandbox_client:
            raise RuntimeError("Sandbox client not configured")

        result = await self._sandbox_client.execute_code_with_mounts(
            code=code,
            file_mounts=self._get_mounts(),
            timeout=timeout,
        )

        if not result.success:
            raise RuntimeError(result.error or "Sandbox execution failed")

        try:
            return json.loads(result.output)
        except json.JSONDecodeError:
            raise RuntimeError(f"Invalid JSON from sandbox: {result.output[:200]}")

    async def _execute_impl(
        self, sql: str, params: list | None = None, timeout: int | None = None
    ) -> list[dict[str, Any]]:
        """Execute a query via sandbox and return rows."""
        code = _build_query_code(sql)
        data = await self._run_sandboxed(code, timeout=timeout or self._query_timeout)
        return data.get("rows", [])

    async def _get_schema_impl(self) -> dict[str, Any]:
        """Get schema via sandbox introspection."""
        import time as _time

        code = _build_schema_code()
        t0 = _time.monotonic()
        result = await self._run_sandboxed(code, timeout=30)
        elapsed_ms = (_time.monotonic() - t0) * 1000
        table_count = len(result) if isinstance(result, dict) else 0
        await self._audit_sql(f"SANDBOX: schema introspection ({table_count} tables)", table_count, elapsed_ms)
        return result

    async def health_check(self) -> bool:
        """Check if the DuckDB file is accessible via sandbox."""
        try:
            if not self._sandbox_client:
                logger.warning("SandboxedDuckDB health_check: no sandbox client")
                return False
            code = f"import duckdb; conn = duckdb.connect('{_SANDBOX_DB_PATH}', read_only=True); conn.execute('SELECT 1'); conn.close(); print('ok')"
            result = await self._sandbox_client.execute_code_with_mounts(
                code=code,
                file_mounts=self._get_mounts(),
                timeout=10,
            )
            if not result.success:
                logger.warning("SandboxedDuckDB health_check failed: %s", result.error)
            return result.success
        except Exception as e:
            logger.warning("SandboxedDuckDB health_check exception: %s", e)
            return False

    async def close(self) -> None:
        """Nothing to close — each query is a fresh sandbox execution."""
        pass
