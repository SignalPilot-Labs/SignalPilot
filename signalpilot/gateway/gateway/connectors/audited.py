"""Audited connector wrapper — logs every SQL execution to the audit trail.

Wraps any BaseConnector and intercepts execute() calls to write audit entries.
Used by pool_manager.connection() so all SQL — MCP tools, REST API, schema
introspection — gets logged automatically.
"""

from __future__ import annotations

import time
import uuid
import logging
from typing import Any

from .base import BaseConnector

logger = logging.getLogger(__name__)


class AuditedConnector:
    """Transparent wrapper that logs every execute() call to gateway_audit_logs."""

    def __init__(self, connector: BaseConnector, connection_name: str | None = None):
        self._connector = connector
        self._connection_name = connection_name

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connector, name)

    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        t0 = time.monotonic()
        rows = await self._connector.execute(sql, params=params, timeout=timeout)
        elapsed_ms = (time.monotonic() - t0) * 1000

        # Fire-and-forget audit
        try:
            import asyncio
            asyncio.create_task(self._log_sql(sql, len(rows) if rows else 0, elapsed_ms))
        except Exception:
            pass

        return rows

    async def _log_sql(self, sql: str, rows_returned: int, duration_ms: float) -> None:
        try:
            from ..db.engine import get_session_factory
            from ..db.models import GatewayAuditLog
            from ..governance.context import current_org_id_var
            from ..mcp_server import mcp_audit_id_var

            org_id = current_org_id_var.get("local")
            parent_id = mcp_audit_id_var.get(None)

            factory = get_session_factory()
            async with factory() as session:
                session.add(GatewayAuditLog(
                    id=str(uuid.uuid4()),
                    org_id=org_id,
                    timestamp=time.time(),
                    event_type="sql",
                    connection_name=self._connection_name,
                    sql_text=sql[:10000],
                    rows_returned=rows_returned,
                    duration_ms=duration_ms,
                    parent_id=parent_id,
                ))
                await session.commit()
        except Exception:
            logger.debug("Failed to audit SQL execution", exc_info=True)
