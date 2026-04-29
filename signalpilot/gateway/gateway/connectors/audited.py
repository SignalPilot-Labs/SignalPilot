"""Audited connector wrapper — logs every SQL execution to the audit trail.

Wraps any BaseConnector and intercepts execute() calls to write audit entries.
Used by pool_manager.connection() so all SQL — MCP tools, REST API, schema
introspection — gets logged automatically.
"""

from __future__ import annotations

import contextvars
import time
import uuid
import logging
from typing import Any

from .base import BaseConnector

logger = logging.getLogger(__name__)

# Context var for the active connection name — set by REST API deps or MCP tools
active_connection_name_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "active_connection_name", default=None
)


class AuditedConnector:
    """Transparent wrapper that logs every execute() call to gateway_audit_logs."""

    def __init__(self, connector: BaseConnector, connection_name: str | None = None):
        self._connector = connector
        self._connection_name = connection_name

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connector, name)

    def _resolve_connection_name(self) -> str | None:
        """Get connection name from constructor arg or context variable."""
        return self._connection_name or active_connection_name_var.get(None)

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        t0 = time.monotonic()
        rows = await self._connector.execute(sql, params=params, timeout=timeout)
        elapsed_ms = (time.monotonic() - t0) * 1000

        try:
            await self._log_sql_raw(sql, len(rows) if rows else 0, elapsed_ms)
        except Exception:
            logger.debug("Audit log failed", exc_info=True)

        return rows

    async def _log_sql_raw(self, sql: str, rows_returned: int, duration_ms: float) -> None:
        """Log SQL execution using raw SQL INSERT to avoid ORM session conflicts."""
        try:
            from ..db.engine import get_engine
            from ..governance.context import current_org_id_var
            from ..mcp_server import mcp_audit_id_var
            from sqlalchemy import text

            org_id = current_org_id_var.get("local")
            parent_id = mcp_audit_id_var.get(None)
            conn_name = self._resolve_connection_name()

            engine = get_engine()
            async with engine.begin() as conn:
                await conn.execute(text(
                    "INSERT INTO gateway_audit_logs "
                    "(id, org_id, timestamp, event_type, connection_name, sql_text, rows_returned, duration_ms, parent_id, blocked) "
                    "VALUES (:id, :org_id, :ts, 'sql', :conn_name, :sql_text, :rows, :dur, :parent_id, false)"
                ), {
                    "id": str(uuid.uuid4()),
                    "org_id": org_id,
                    "ts": time.time(),
                    "conn_name": conn_name,
                    "sql_text": sql[:10000],
                    "rows": rows_returned,
                    "dur": duration_ms,
                    "parent_id": parent_id,
                })
        except Exception:
            logger.debug("Failed to audit SQL execution", exc_info=True)
