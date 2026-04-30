"""Audit entry model."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AuditEntry(BaseModel):
    id: str
    timestamp: float
    event_type: str  # query | execute | connect | block | mcp_tool | mcp_sql
    connection_name: str | None = None
    sandbox_id: str | None = None
    sql: str | None = None
    tables: list[str] = []
    rows_returned: int | None = None
    cost_usd: float | None = None
    blocked: bool = False
    block_reason: str | None = None
    duration_ms: float | None = None
    agent_id: str | None = None
    parent_id: str | None = None  # links child SQL queries to parent mcp_tool call
    metadata: dict[str, Any] = {}
    client_ip: str | None = None
    user_agent: str | None = None
