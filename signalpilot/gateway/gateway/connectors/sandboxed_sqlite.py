"""Sandboxed SQLite connector — executes queries via the sandbox manager.

Mirrors the SandboxedDuckDBConnector pattern: local SQLite files on the host
filesystem are mounted into a gVisor sandbox, and queries are wrapped in
Python code that runs in isolation. This avoids the Docker path-mapping
problem where the gateway container can't directly access host file paths.

The connector generates Python code using the stdlib sqlite3 module (no extra
dependencies needed in the sandbox image).
"""

from __future__ import annotations

import json
import logging
import textwrap
from typing import Any

from .base import BaseConnector
from .sandboxed_duckdb import SandboxedDuckDBConnector  # reuse _translate_path

logger = logging.getLogger(__name__)

# The sandbox path where the SQLite file is mounted
_SANDBOX_DB_PATH = "data/db.sqlite"


def _build_query_code(sql: str, db_path: str = _SANDBOX_DB_PATH) -> str:
    """Build Python code that executes a SQL query and prints JSON results."""
    escaped_sql = sql.replace("\\", "\\\\").replace("'", "\\'")
    return textwrap.dedent(f"""\
        import sqlite3, json, datetime, decimal
        def _serialize(obj):
            if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
                return obj.isoformat()
            if isinstance(obj, datetime.timedelta):
                return str(obj)
            if isinstance(obj, decimal.Decimal):
                return float(obj)
            if isinstance(obj, bytes):
                return obj.hex()
            return str(obj)
        conn = sqlite3.connect('file:{db_path}?mode=ro', uri=True)
        try:
            cursor = conn.execute('{escaped_sql}')
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            print(json.dumps({{"columns": columns, "rows": rows}}, default=_serialize))
        finally:
            conn.close()
    """)


def _build_schema_code(db_path: str = _SANDBOX_DB_PATH) -> str:
    """Build Python code that introspects the SQLite schema and prints JSON."""
    return textwrap.dedent(f"""\
        import sqlite3, json
        conn = sqlite3.connect('file:{db_path}?mode=ro', uri=True)
        try:
            # Discover tables and views
            cursor = conn.execute(
                "SELECT name, type FROM sqlite_master "
                "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
            )
            table_rows = cursor.fetchall()
            tables = [row[0] for row in table_rows]
            table_type_map = {{row[0]: row[1] for row in table_rows}}

            # Batch row counts
            row_counts = {{}}
            if tables:
                parts = []
                for t in tables:
                    safe = t.replace("'", "''")
                    parts.append(f"SELECT '{{safe}}' AS t, COUNT(*) AS c FROM [{{t}}]")
                try:
                    for row in conn.execute(" UNION ALL ".join(parts)).fetchall():
                        row_counts[row[0]] = row[1]
                except Exception:
                    pass

            schema = {{}}
            for table in tables:
                # Column info via PRAGMA
                columns = []
                for row in conn.execute(f"PRAGMA table_info([{{table}}])").fetchall():
                    columns.append({{
                        "name": row[1],
                        "type": row[2],
                        "nullable": not row[3],
                        "primary_key": bool(row[5]),
                        "default": row[4],
                        "comment": "",
                    }})

                # Foreign keys
                foreign_keys = []
                try:
                    for fk in conn.execute(f"PRAGMA foreign_key_list([{{table}}])").fetchall():
                        foreign_keys.append({{
                            "column": fk[3],
                            "references_table": fk[2],
                            "references_column": fk[4],
                        }})
                except Exception:
                    pass

                schema[table] = {{
                    "schema": "main",
                    "name": table,
                    "type": table_type_map.get(table, "table"),
                    "columns": columns,
                    "foreign_keys": foreign_keys,
                    "row_count": row_counts.get(table, 0),
                }}

            print(json.dumps(schema))
        finally:
            conn.close()
    """)


class SandboxedSQLiteConnector(BaseConnector):
    """SQLite connector that executes queries via the sandbox manager.

    Reuses the same path translation and sandbox execution pattern as
    SandboxedDuckDBConnector but generates sqlite3-based Python code.
    """

    def __init__(self) -> None:
        super().__init__()
        self._host_path: str = ""
        self._sandbox_client = None

    @property
    def _identifier_quote(self) -> str:
        return '['

    async def connect(self, connection_string: str) -> None:
        """Store the host path. Actual connection happens per-query in the sandbox."""
        self._host_path = SandboxedDuckDBConnector._translate_path(connection_string)
        logger.info("SandboxedSQLite: translated path -> %s", self._host_path)
        if self._sandbox_client is None:
            try:
                from ..api.deps import get_sandbox_client
                self._sandbox_client = get_sandbox_client()
            except Exception:
                from ..sandbox_client import SandboxClient
                import os
                url = os.environ.get("SP_SANDBOX_MANAGER_URL", "http://localhost:8180")
                self._sandbox_client = SandboxClient(base_url=url)
                logger.info("SandboxedSQLite: created fallback sandbox client at %s", url)

    def set_sandbox_client(self, client) -> None:
        self._sandbox_client = client

    def _get_mounts(self) -> list[dict]:
        return [{"host_path": self._host_path, "sandbox_path": _SANDBOX_DB_PATH}]

    async def _run_sandboxed(self, code: str, timeout: int = 30) -> dict:
        """Execute Python code in sandbox with the SQLite file mounted."""
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

    async def _execute_impl(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
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
        """Check if the SQLite file is accessible via sandbox."""
        try:
            if not self._sandbox_client:
                logger.warning("SandboxedSQLite health_check: no sandbox client")
                return False
            code = (
                f"import sqlite3; "
                f"conn = sqlite3.connect('file:{_SANDBOX_DB_PATH}?mode=ro', uri=True); "
                f"conn.execute('SELECT 1'); conn.close(); print('ok')"
            )
            result = await self._sandbox_client.execute_code_with_mounts(
                code=code, file_mounts=self._get_mounts(), timeout=10,
            )
            if not result.success:
                logger.warning("SandboxedSQLite health_check failed: %s", result.error)
            return result.success
        except Exception as e:
            logger.warning("SandboxedSQLite health_check exception: %s", e)
            return False

    async def close(self) -> None:
        """Nothing to close — each query is a fresh sandbox execution."""
        pass
