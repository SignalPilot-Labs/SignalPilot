"""MCP tool call auditing and the audited_tool decorator factory."""

from __future__ import annotations

import functools
import logging as _logging
import time
import uuid

from gateway.mcp.context import (
    _store_session,
    mcp_allowed_connection_var,
    mcp_audit_id_var,
    mcp_client_ip_var,
    mcp_execution_identity_var,
    mcp_org_id_var,
    mcp_user_agent_var,
)
from gateway.models import AuditEntry

_mcp_logger = _logging.getLogger("gateway.mcp_audit")

STANDALONE_CHAT_TOOL_ALLOWLIST = frozenset(
    {
        "check_budget",
        "connector_capabilities",
        "debug_cte_query",
        "describe_table",
        "estimate_query_cost",
        "explain_query",
        "explore_column",
        "explore_columns",
        "explore_table",
        "find_join_path",
        "get_date_boundaries",
        "get_relationships",
        "list_database_connections",
        "list_semantic_metrics",
        "list_tables",
        "query_database",
        "schema_ddl",
        "schema_link",
        "schema_overview",
        "schema_statistics",
        "validate_sql",
        "verify_metric_conformance",
    }
)


def standalone_chat_tool_denial(tool_name: str, connection_name: str | None) -> str | None:
    """Return a public denial for capabilities unavailable to standalone chat."""
    execution_identity = mcp_execution_identity_var.get(None)
    if not execution_identity or not execution_identity.startswith("chat:"):
        return None
    if tool_name not in STANDALONE_CHAT_TOOL_ALLOWLIST:
        return "Error: this tool is unavailable in standalone data chat"
    allowed_connection = mcp_allowed_connection_var.get(None)
    if connection_name and allowed_connection and connection_name != allowed_connection:
        return "Error: connection is outside this chat's allowed scope"
    return None


async def _audit_tool_call(
    tool_name: str,
    args: dict,
    result: str | None,
    duration_ms: float,
    error: str | None = None,
    connection_name: str | None = None,
    sql: str | None = None,
    audit_id: str | None = None,
):
    """Log an MCP tool call to the gateway audit log and increment usage counter."""
    from gateway.governance.plan_limits import daily_query_counter

    org_id = mcp_org_id_var.get(None)

    # Increment daily usage counter for every tool call
    if org_id:
        daily_query_counter.increment(org_id)

    client_ip = mcp_client_ip_var.get(None)
    user_agent = mcp_user_agent_var.get(None)

    try:
        async with _store_session() as store:
            await store.append_audit(
                AuditEntry(
                    id=audit_id or str(uuid.uuid4()),
                    timestamp=time.time(),
                    event_type="mcp_tool",
                    connection_name=connection_name,
                    sql=sql,  # Present for query_database, None for other tools
                    rows_returned=None,
                    cost_usd=None,
                    blocked=error is not None,
                    block_reason=error,
                    duration_ms=duration_ms,
                    agent_id=tool_name,
                    metadata={"args": {k: str(v)[:200] for k, v in args.items()} if args else {}},
                    client_ip=client_ip,
                    user_agent=user_agent,
                )
            )
    except Exception:
        _mcp_logger.debug("Failed to audit MCP tool call %s", tool_name, exc_info=True)


def _audited_tool(fn):
    """Decorator that wraps an MCP tool function with audit logging."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        t0 = time.time()
        tool_name = fn.__name__
        # Generate a unique ID for this tool call so child SQL can link back
        audit_id = str(uuid.uuid4())
        token = mcp_audit_id_var.set(audit_id)
        # Extract connection_name and sql from kwargs if present
        conn = kwargs.get("connection_name") or (args[0] if args and isinstance(args[0], str) else None)
        sql_arg = kwargs.get("sql")
        try:
            denial = standalone_chat_tool_denial(tool_name, conn)
            if denial:
                duration_ms = (time.time() - t0) * 1000
                await _audit_tool_call(
                    tool_name=tool_name,
                    args=kwargs,
                    result=denial,
                    duration_ms=duration_ms,
                    connection_name=conn,
                    sql=sql_arg,
                    audit_id=audit_id,
                    error=denial,
                )
                return denial
            result = await fn(*args, **kwargs)
            duration_ms = (time.time() - t0) * 1000
            # Detect blocked queries from return value
            result_str = str(result) if result else ""
            is_blocked = result_str.startswith("Query blocked:")
            import asyncio

            asyncio.create_task(
                _audit_tool_call(
                    tool_name=tool_name,
                    args=kwargs,
                    result=result_str[:200],
                    duration_ms=duration_ms,
                    connection_name=conn,
                    sql=sql_arg,
                    audit_id=audit_id,
                    error=result_str[:200] if is_blocked else None,
                )
            )
            return result
        except Exception as exc:
            duration_ms = (time.time() - t0) * 1000
            import asyncio

            asyncio.create_task(
                _audit_tool_call(
                    tool_name=tool_name,
                    args=kwargs,
                    result=None,
                    duration_ms=duration_ms,
                    error=str(exc)[:200],
                    connection_name=conn,
                    sql=sql_arg,
                    audit_id=audit_id,
                )
            )
            raise
        finally:
            mcp_audit_id_var.reset(token)

    return wrapper


def audited_tool(mcp_instance, *tool_args, **tool_kwargs):
    """
    Decorator factory: replaces @mcp.tool(...) at every call site.

    Usage:
        from gateway.mcp.server import mcp
        from gateway.mcp.audit import audited_tool

        @audited_tool(mcp)
        async def query_database(...): ...

        @audited_tool(mcp, name="custom")   # tool kwargs forwarded to mcp.tool()
        async def explain_query(...): ...
    """
    fastmcp_decorator = mcp_instance.tool(*tool_args, **tool_kwargs)

    def apply(fn):
        return fastmcp_decorator(_audited_tool(fn))

    return apply
