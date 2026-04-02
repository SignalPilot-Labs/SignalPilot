"""Hook callbacks that log every tool interaction to the audit database.

These hooks provide the real-time feed that powers the monitoring UI.
Every PreToolUse and PostToolUse event is logged to the tool_calls table,
which the monitor's SSE endpoint picks up via polling.
"""

import json
import time
from pathlib import Path
from typing import Any

from agent import db

# Track pre-tool timestamps for duration calculation
_pre_tool_times: dict[str, float] = {}

# Track subagent lifecycle for timeout enforcement
_subagent_start_times: dict[str, float] = {}    # agent_id → start time
_subagent_last_tool: dict[str, float] = {}       # agent_id → last tool call time
SUBAGENT_TIMEOUT_SEC = 45 * 60      # 45 min — absolute timeout (block tool calls)
SUBAGENT_IDLE_KILL_SEC = 10 * 60    # 10 min idle — trigger interrupt+recovery

# Current run_id and agent role, set by main.py
_run_id: str | None = None
_agent_role: str = "worker"  # "worker" or "ceo"


def get_stuck_subagents() -> list[dict]:
    """Return subagents that have been idle longer than IDLE_KILL threshold.
    Called by the main loop's background pulse checker.
    Also cleans up stale entries from subagents that exceeded the absolute timeout
    without the stop hook firing (e.g., crashed subagents)."""
    now = time.time()
    stuck = []
    stale_ids = []
    for agent_id, start_t in _subagent_start_times.items():
        last_tool_t = _subagent_last_tool.get(agent_id, start_t)
        idle_sec = now - last_tool_t
        total_sec = now - start_t
        if total_sec > SUBAGENT_TIMEOUT_SEC * 2:
            # Far past absolute timeout — stop hook never fired, clean up
            stale_ids.append(agent_id)
        elif idle_sec > SUBAGENT_IDLE_KILL_SEC:
            stuck.append({
                "agent_id": agent_id,
                "idle_seconds": int(idle_sec),
                "total_seconds": int(total_sec),
            })
    for agent_id in stale_ids:
        _subagent_start_times.pop(agent_id, None)
        _subagent_last_tool.pop(agent_id, None)
    return stuck


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
    session_id = hook_input.get("session_id")
    agent_id = hook_input.get("agent_id")  # only populated for subagent calls

    # Track last tool call time per subagent
    if agent_id:
        _subagent_last_tool[agent_id] = time.time()

    # Check subagent absolute timeout (45 min)
    if agent_id and agent_id in _subagent_start_times:
        elapsed = time.time() - _subagent_start_times[agent_id]
        if elapsed > SUBAGENT_TIMEOUT_SEC:
            print(f"[hook] SUBAGENT TIMEOUT: agent_id={agent_id} elapsed={elapsed:.0f}s (limit={SUBAGENT_TIMEOUT_SEC}s)")
            try:
                await db.log_audit(
                    _run_id,
                    "subagent_timeout",
                    {
                        "agent_id": agent_id,
                        "elapsed_seconds": int(elapsed),
                        "limit_seconds": SUBAGENT_TIMEOUT_SEC,
                        "tool_name": tool_name,
                    },
                )
            except Exception as e:
                print(f"[hooks] Failed to log subagent timeout: {e}")
            return {"decision": "block", "reason": f"Subagent timed out after {int(elapsed)}s (limit: {SUBAGENT_TIMEOUT_SEC}s). You must stop now and return your results."}

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
            session_id=session_id,
            agent_id=agent_id,
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
    session_id = hook_input.get("session_id")
    agent_id = hook_input.get("agent_id")

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
            session_id=session_id,
            agent_id=agent_id,
        )
    except Exception as e:
        print(f"[hook] Failed to log post-tool call: {e}")

    return {}


async def subagent_start_hook(
    hook_input: dict[str, Any],
    tool_use_id: str | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Called when a subagent starts. Logs start event and tracks start time."""
    if not _run_id:
        return {}

    agent_id = hook_input.get("agent_id", "")
    if agent_id:
        _subagent_start_times[agent_id] = time.time()

    try:
        await db.log_audit(
            _run_id,
            "subagent_start",
            {
                "agent_id": agent_id,
                "tool_use_id": tool_use_id,
            },
        )
    except Exception as e:
        print(f"[hook] Failed to log subagent start: {e}")

    return {}


async def subagent_stop_hook(
    hook_input: dict[str, Any],
    tool_use_id: str | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Called when a subagent finishes. Reads transcript for final output."""
    if not _run_id:
        return {}

    agent_id = hook_input.get("agent_id", "")
    transcript_path = hook_input.get("agent_transcript_path", "")

    # Clean up tracking
    _subagent_start_times.pop(agent_id, None)
    _subagent_last_tool.pop(agent_id, None)

    # Try to read the transcript and extract the final assistant message
    final_text = ""
    if transcript_path:
        try:
            raw = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
            # Transcript is JSONL — parse last few lines looking for assistant text
            lines = raw.strip().split("\n")
            for line in reversed(lines[-20:]):
                try:
                    entry = json.loads(line)
                    # Look for assistant message with text content
                    if entry.get("role") == "assistant":
                        content = entry.get("content", [])
                        if isinstance(content, list):
                            texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                            if texts:
                                final_text = "\n".join(texts)[:3000]
                                break
                        elif isinstance(content, str):
                            final_text = content[:3000]
                            break
                except (json.JSONDecodeError, KeyError):
                    continue
        except Exception as e:
            print(f"[hook] Failed to read subagent transcript: {e}")

    try:
        await db.log_audit(
            _run_id,
            "subagent_complete",
            {
                "agent_id": agent_id,
                "tool_use_id": tool_use_id,
                "final_text": final_text[:2000] if final_text else "",
                "has_transcript": bool(transcript_path),
            },
        )
    except Exception as e:
        print(f"[hook] Failed to log subagent complete: {e}")

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


def _safe_serialize(data: Any) -> Any:
    """Make data JSON-serializable without truncation."""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        return {k: _safe_serialize(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_safe_serialize(item) for item in data]
    try:
        import json as _json
        _json.dumps(data)
        return data
    except (TypeError, ValueError):
        return str(data)
