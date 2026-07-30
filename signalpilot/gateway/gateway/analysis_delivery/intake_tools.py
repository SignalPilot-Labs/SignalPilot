"""Read-only intake tool runner for Slack/Notion routing."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gateway.analysis_delivery.intake_actions import (
    IntakeAnalysisStatus,
    analysis_status_for_source_thread,
    analysis_status_payload,
)
from gateway.mcp.context import mcp_org_id_var, mcp_raw_key_var, mcp_scopes_var, mcp_user_id_var
from gateway.mcp.tools.connections import connection_health, connector_capabilities, list_database_connections
from gateway.mcp.tools.knowledge import get_knowledge, search_knowledge
from gateway.mcp.tools.query import query_history
from gateway.mcp.tools.schema import describe_table, list_tables, schema_link, schema_overview
from gateway.mcp.tools.workspace_projects import list_workspace_projects
from gateway.store import chat_traces
from gateway.string_utils import string_value as _string

LOGGER = logging.getLogger(__name__)
READ_TOOL_RESULT_LIMIT = 6000
TRACE_EVENT_LIMIT = 12


class IntakeToolError(RuntimeError):
    """Raised when an intake read tool cannot be executed."""


class IntakeToolRunner:
    def __init__(
        self,
        *,
        session: Any,
        db: AsyncSession | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        raw_mcp_key: str | None = None,
    ) -> None:
        self.session = session
        self.db = db
        self.session_factory = session_factory
        self.raw_mcp_key = raw_mcp_key

    async def run(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        args = dict(arguments or {})
        if name in _INTERNAL_READ_TOOLS:
            payload = await _INTERNAL_READ_TOOLS[name](self, args)
            return _bounded_json(payload)
        if name not in _MCP_READ_TOOLS:
            raise IntakeToolError(f"Tool is not allowed for intake: {name}")
        return await self._run_mcp_tool(name, args)

    async def _run_mcp_tool(self, name: str, arguments: dict[str, Any]) -> str:
        func = _MCP_READ_TOOLS[name]
        token_org = mcp_org_id_var.set(self.session.org_id)
        token_user = mcp_user_id_var.set(self.session.user_id)
        token_scopes = mcp_scopes_var.set(["read"])
        token_key = mcp_raw_key_var.set(self.raw_mcp_key)
        try:
            result = await func(**arguments)
        finally:
            mcp_raw_key_var.reset(token_key)
            mcp_scopes_var.reset(token_scopes)
            mcp_user_id_var.reset(token_user)
            mcp_org_id_var.reset(token_org)
        return _clip_text(_string(result), READ_TOOL_RESULT_LIMIT)

    @asynccontextmanager
    async def db_session(self):
        if self.db is not None:
            yield self.db
            return
        if self.session_factory is None:
            raise IntakeToolError("No DB session available for intake tool")
        async with self.session_factory() as db:
            yield db

    async def current_analysis_status(self) -> IntakeAnalysisStatus:
        async with self.db_session() as db:
            return await analysis_status_for_source_thread(
                db,
                org_id=self.session.org_id,
                source=self.session.source,
                source_thread_id=self.session.source_thread_id,
                active_stale_seconds=self.session.active_stale_seconds,
            )


async def _get_current_conversation(runner: IntakeToolRunner, _args: dict[str, Any]) -> dict[str, Any]:
    session = runner.session
    return {
        "source": session.source,
        "surface": session.surface,
        "prompt": session.prompt,
        "sourceThreadId": session.source_thread_id,
        "sourceUrl": session.source_url,
        "previousMessages": session.previous_messages[-8:],
        "continuationState": session.continuation_state,
        "availableTerminalActions": session.available_terminal_actions,
        "analysisHint": session.analysis_hint,
        "deliverableHint": session.deliverable_context,
    }


async def _get_analysis_status(runner: IntakeToolRunner, _args: dict[str, Any]) -> dict[str, Any]:
    return analysis_status_payload(await runner.current_analysis_status())


async def _get_analysis_trace_summary(runner: IntakeToolRunner, _args: dict[str, Any]) -> dict[str, Any]:
    status = await runner.current_analysis_status()
    thread_id = _string(getattr(status.trail, "thread_id", "")) if status.trail is not None else ""
    if not thread_id:
        return {"status": "not_found", "events": []}
    async with runner.db_session() as db:
        events = await chat_traces.get_events(
            db,
            org_id=runner.session.org_id,
            user_id=runner.session.user_id or _string(getattr(status.trail, "analysis_user_id", "")),
            thread_id=thread_id,
            require_thread=False,
        )
    recent = events[-TRACE_EVENT_LIMIT:]
    return {
        "status": status.status,
        "threadId": thread_id,
        "events": [
            {
                "idx": getattr(event, "idx", None),
                "type": _string(getattr(event, "type", "")),
                "role": _string(getattr(event, "role", "")),
                "toolName": _string(getattr(event, "tool_name", "")),
                "isError": bool(getattr(event, "is_error", False)),
                "safeText": _clip_text(_string(getattr(event, "content", "")), 500),
            }
            for event in recent
        ],
    }


async def _get_deliverable_context(runner: IntakeToolRunner, _args: dict[str, Any]) -> dict[str, Any]:
    context = runner.session.deliverable_context
    if not context:
        return {"status": "not_found"}
    return {"status": "found", **context}


def _bounded_json(payload: Any) -> str:
    try:
        if hasattr(payload, "__dataclass_fields__"):
            payload = asdict(payload)
        text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    except Exception:
        LOGGER.debug("Could not JSON encode intake tool payload", exc_info=True)
        text = _string(payload)
    return _clip_text(text, READ_TOOL_RESULT_LIMIT)


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 40].rstrip() + "\n[output truncated]"


_MCP_READ_TOOLS: dict[str, Callable[..., Awaitable[str]]] = {
    "list_database_connections": list_database_connections,
    "connection_health": connection_health,
    "connector_capabilities": connector_capabilities,
    "list_workspace_projects": list_workspace_projects,
    "schema_overview": schema_overview,
    "schema_link": schema_link,
    "list_tables": list_tables,
    "describe_table": describe_table,
    "get_knowledge": get_knowledge,
    "search_knowledge": search_knowledge,
    "query_history": query_history,
}

_INTERNAL_READ_TOOLS: dict[str, Callable[[IntakeToolRunner, dict[str, Any]], Awaitable[dict[str, Any]]]] = {
    "get_current_conversation": _get_current_conversation,
    "get_analysis_status": _get_analysis_status,
    "get_analysis_trace_summary": _get_analysis_trace_summary,
    "get_deliverable_context": _get_deliverable_context,
}

INTAKE_READ_TOOL_NAMES: tuple[str, ...] = tuple(_MCP_READ_TOOLS) + tuple(_INTERNAL_READ_TOOLS)
