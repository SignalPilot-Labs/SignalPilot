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
    """Transparent wrapper that logs every execute() call to gateway_audit_logs.

    Monkey-patches the underlying connector's execute method so that even
    internal calls (e.g. get_schema → self.execute) are intercepted.
    """

    def __init__(self, connector: BaseConnector, connection_name: str | None = None):
        self._connector = connector
        self._connection_name = connection_name
        # Monkey-patch the connector's execute so internal calls are audited
        self._original_execute = connector.execute
        connector.execute = self._audited_execute  # type: ignore[assignment]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connector, name)

    def _resolve_connection_name(self) -> str | None:
        return self._connection_name or active_connection_name_var.get(None)

    def restore(self) -> None:
        """Restore the original execute method (call on release)."""
        self._connector.execute = self._original_execute  # type: ignore[assignment]

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        return await self._audited_execute(sql, params=params, timeout=timeout)

    async def _audited_execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        t0 = time.monotonic()
        rows = await self._original_execute(sql, params=params, timeout=timeout)
        elapsed_ms = (time.monotonic() - t0) * 1000

        try:
            await self._log_sql_raw(sql, len(rows) if rows else 0, elapsed_ms)
        except Exception:
            logger.warning("Audit log failed", exc_info=True)

        return rows

    async def _log_sql_raw(self, sql: str, rows_returned: int, duration_ms: float) -> None:
        """Log SQL execution using a dedicated session to avoid connection conflicts."""
        try:
            from ..db.engine import get_session_factory
            from ..db.models import GatewayAuditLog
            from ..governance.context import current_org_id_var
            from ..mcp_server import mcp_audit_id_var, mcp_user_id_var

            org_id = current_org_id_var.get("local")
            user_id = mcp_user_id_var.get(None) or "system"
            parent_id = mcp_audit_id_var.get(None)
            conn_name = self._resolve_connection_name()

            factory = get_session_factory()
            async with factory() as session:
                session.add(GatewayAuditLog(
                    id=str(uuid.uuid4()),
                    org_id=org_id,
                    user_id=user_id,
                    timestamp=time.time(),
                    event_type="sql",
                    connection_name=conn_name,
                    sql_text=sql[:10000],
                    rows_returned=rows_returned,
                    duration_ms=duration_ms,
                    parent_id=parent_id,
                    blocked=False,
                ))
                await session.commit()
        except Exception:
            logger.warning("Failed to audit SQL execution", exc_info=True)
