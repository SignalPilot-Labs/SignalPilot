"""Hook callbacks that log every tool interaction to the audit database.

These hooks provide the real-time feed that powers the monitoring UI.
Every PreToolUse and PostToolUse event is logged to the tool_calls table,
which triggers a pg_notify that the monitor's SSE endpoint picks up.
"""

import time
from typing import Any

from agent import db

# Track pre-tool timestamps for duration calculation
_pre_tool_times: dict[str, float] = {}

# Current run_id and agent role, set by main.py
_run_id: str | None = None
_agent_role: str = "worker"  # "worker" or "ceo"


def set_run_id(run_id: str) -> None:
    global _run_id
    _run_id = run_id


def set_agent_role(role: str) -> None:
    """Set the current agent role ('worker' or 'ceo')."""
    global _agent_role
    _agent_role = role


async def pre_tool_use_hook(
    hook_input: dict[str, Any],
    tool_use_id: str | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Called before every tool execution. Logs the call to the database."""
    if not _run_id:
        return {}

    tool_name = hook_input.get("tool_name", "unknown")
    input_data = hook_input.get("tool_input", {})

    # Record timestamp for duration calculation
    if tool_use_id:
        _pre_tool_times[tool_use_id] = time.time()

    try:
        await db.log_tool_call(
            run_id=_run_id,
            phase="pre",
            tool_name=tool_name,
            input_data=_safe_serialize(input_data),
            agent_role=_agent_role,
            tool_use_id=tool_use_id,
        )
    except Exception as e:
        print(f"[hook] Failed to log pre-tool call: {e}")

    return {}


async def post_tool_use_hook(
    hook_input: dict[str, Any],
    tool_use_id: str | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Called after every tool execution. Logs the result to the database."""
    if not _run_id:
        return {}

    tool_name = hook_input.get("tool_name", "unknown")
    tool_response = hook_input.get("tool_response", None)

    # Calculate duration
    duration_ms = None
    if tool_use_id and tool_use_id in _pre_tool_times:
        duration_ms = int((time.time() - _pre_tool_times.pop(tool_use_id)) * 1000)

    try:
        await db.log_tool_call(
            run_id=_run_id,
            phase="post",
            tool_name=tool_name,
            output_data=_safe_serialize(tool_response) if tool_response is not None else None,
            duration_ms=duration_ms,
            agent_role=_agent_role,
            tool_use_id=tool_use_id,
        )
    except Exception as e:
        print(f"[hook] Failed to log post-tool call: {e}")

    return {}


async def stop_hook(
    hook_input: dict[str, Any],
    tool_use_id: str | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Called when the agent stops. Logs the stop event."""
    if not _run_id:
        return {}

    try:
        await db.log_audit(
            _run_id,
            "agent_stop",
            {
                "reason": hook_input.get("stop_reason", "unknown"),
                "hook_input": _safe_serialize(hook_input),
            },
        )
    except Exception as e:
        print(f"[hook] Failed to log stop event: {e}")

    return {}


def _safe_serialize(data: Any, max_str_len: int = 2000) -> Any:
    """Truncate large strings in data for safe storage."""
    if isinstance(data, str):
        return data[:max_str_len] + "...[truncated]" if len(data) > max_str_len else data
    if isinstance(data, dict):
        return {k: _safe_serialize(v, max_str_len) for k, v in data.items()}
    if isinstance(data, list):
        return [_safe_serialize(item, max_str_len) for item in data[:50]]
    return data
