"""Bounded public activity, ordered durably across workers and MCP requests."""

import re
import time
import uuid

from sqlalchemy import select, update

from gateway.db.models import MCPAgentEvent, MCPAgentThread

MAX_EVENTS = 2000
_LABELS = {
    "query_started": "Submitted governed query",
    "query_finished": "Query completed",
    "query_failed": "Query failed",
    "tool_started": "Using data tool",
    "tool_finished": "Data tool finished",
    "tool_failed": "Data tool failed",
}
_STAGES = {
    "starting": "Starting agent",
    "working": "Agent is working",
    "tool": "Agent is working",
    "verifying": "Verifying changes",
    "completed": "Agent completed",
    "preparing": "Preparing workspace",
    "launching": "Launching agent",
    "local_tool": "Working on project",
    "packaging": "Preparing changes",
    "heartbeat": "Agent is running",
}


def sql_preview(sql: str) -> str:
    """Keep query structure, never literals/comments or a failed parse's raw text."""
    import sqlglot
    from sqlglot import exp

    try:
        if not isinstance(sql, str) or len(sql) > 20_000:
            return "SQL preview unavailable"
        # Generic-dialect parsing can reinterpret vendor literals as aliases.
        # Omit such previews rather than serialize any literal fragments.
        if re.search(r"(?i)\b0[xb][0-9a-f]+|\$[A-Za-z_0-9]*\$", sql):
            return "SQL preview unavailable"
        statements = sqlglot.parse(sql)
        if len(statements) != 1 or not isinstance(statements[0], exp.Query):
            return "SQL preview unavailable"
        tree = statements[0]
        for node in list(tree.walk()):
            node.comments = None
            if isinstance(
                node,
                (
                    exp.Literal,
                    exp.National,
                    exp.Boolean,
                    exp.HexString,
                    exp.BitString,
                    exp.ByteString,
                    exp.RawString,
                    exp.UnicodeString,
                ),
            ):
                node.replace(exp.Placeholder())
            elif isinstance(node, exp.Identifier) and (
                not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]{0,63}", node.name)
                or node.name.lower().startswith(("spa_", "sp_", "sk_", "sk-", "eyj", "akia"))
            ):
                node.set("this", "redacted_identifier")
                node.set("quoted", False)
        preview = tree.sql(comments=False)
        if re.search(r"(?i)\b(?:spa_|sp_|sk[-_]|eyj|akia)", preview):
            return "SQL preview unavailable"
        return preview[:1200]
    except Exception:
        return "SQL preview unavailable"


def sanitize_event(raw: dict) -> dict:
    from gateway.mcp.audit import AGENT_ALLOWED_MCP_TOOLS

    kind = raw.get("type")
    if kind in _LABELS:
        tool = raw.get("tool")
        if tool not in AGENT_ALLOWED_MCP_TOOLS:
            raise ValueError("Unsupported activity tool")
        result = {"type": kind, "label": _LABELS[kind], "tool": tool}
        call_id = raw.get("call_id", "")
        if isinstance(call_id, str) and re.fullmatch(r"[a-f0-9-]{36}", call_id):
            result["call_id"] = call_id
        if kind == "query_started":
            result["sql_preview"] = sql_preview(raw.get("sql", ""))
    else:
        stage = raw.get("stage", "working")
        if stage not in _STAGES:
            stage = "working"
        result = {"type": "progress", "stage": stage, "label": _STAGES[stage]}
        if raw.get("status") in {"started", "completed", "failed", "running"}:
            result["status"] = raw["status"]
        if stage == "local_tool" and raw.get("tool") in {"Read", "Edit", "Write", "Bash"}:
            result["tool"] = raw["tool"]
            if raw.get("activity") in {"test", "command"}:
                result["activity"] = raw["activity"]
            path = raw.get("path")
            if isinstance(path, str) and len(path) <= 256 and re.fullmatch(r"[A-Za-z0-9_./-]+", path):
                from .artifacts import EXCLUDED

                parts = path.split("/")
                if (
                    not path.startswith("/")
                    and not ({".."} | EXCLUDED) & set(parts)
                    and not any(p.startswith(".env.") for p in parts)
                ):
                    result["path"] = path
    for key in ("row_count", "duration_ms", "elapsed_seconds"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1_000_000_000:
            result[key] = round(value, 2)
    return result


async def append_event(factory, thread_id, run_id, org_id, payload) -> dict | None:
    safe = sanitize_event(payload)
    async with factory() as db:
        sequence = await db.scalar(
            update(MCPAgentThread)
            .where(
                MCPAgentThread.id == thread_id,
                MCPAgentThread.org_id == org_id,
                MCPAgentThread.run_id == run_id,
                MCPAgentThread.status == "running",
                MCPAgentThread.expires_at > time.time(),
                MCPAgentThread.event_sequence < MAX_EVENTS,
                MCPAgentThread.lease_expires_at > time.time(),
            )
            .values(event_sequence=MCPAgentThread.event_sequence + 1)
            .returning(MCPAgentThread.event_sequence)
        )
        if sequence is None:
            return None
        safe = {**safe, "sequence": sequence}
        db.add(
            MCPAgentEvent(
                id=str(uuid.uuid4()),
                thread_id=thread_id,
                run_id=run_id,
                org_id=org_id,
                sequence=sequence,
                created_at=time.time(),
                payload=safe,
            )
        )
        await db.commit()
        return safe


async def read_events(db, org_id, thread_id, run_id, after_sequence=0, limit=50) -> list[dict]:
    rows = await db.scalars(
        select(MCPAgentEvent)
        .where(
            MCPAgentEvent.org_id == org_id,
            MCPAgentEvent.thread_id == thread_id,
            MCPAgentEvent.run_id == run_id,
            MCPAgentEvent.sequence > max(0, int(after_sequence)),
        )
        .order_by(MCPAgentEvent.sequence)
        .limit(max(1, min(100, int(limit))))
    )
    return [row.payload for row in rows]


async def current_event(payload: dict) -> dict | None:
    """Only publish for the authenticated owner and the still-active pinned run."""
    from gateway.db.engine import get_session_factory
    from gateway.mcp.context import (
        mcp_allowed_connection_var,
        mcp_audit_id_var,
        mcp_execution_identity_var,
        mcp_org_id_var,
        mcp_user_id_var,
    )

    identity = mcp_execution_identity_var.get(None) or ""
    if not identity.startswith("agent:"):
        return None
    org, user = mcp_org_id_var.get(None), mcp_user_id_var.get(None)
    if not org or not user:
        return None
    factory = get_session_factory()
    run_id = identity.removeprefix("agent:")
    async with factory() as db:
        row = await db.scalar(
            select(MCPAgentThread).where(
                MCPAgentThread.org_id == org,
                MCPAgentThread.user_id == user,
                MCPAgentThread.run_id == run_id,
                MCPAgentThread.status == "running",
                MCPAgentThread.expires_at > time.time(),
                MCPAgentThread.lease_expires_at > time.time(),
            )
        )
        if row is None or row.request.get("connection_name") != mcp_allowed_connection_var.get(None):
            return None
        thread_id = row.id
    return await append_event(factory, thread_id, run_id, org, {**payload, "call_id": mcp_audit_id_var.get(None)})
