"""Session gate: the end_session MCP tool and time-lock logic.

The agent has exactly ONE way to end a run: calling the `end_session` tool.
This tool is time-locked — it will be denied until the run duration expires.
The operator can also unlock it early via a control signal.

When denied, the tool returns a message telling the agent how much time
remains and suggests what to work on next (escalating depth).
"""

import time
from typing import Any

from claude_agent_sdk import tool, create_sdk_mcp_server

from agent import db


# --- Mutable state set per-run by main.py ---
_run_start: float = 0.0
_run_duration_sec: float = 0.0
_force_unlocked: bool = False
_run_id: str | None = None
_session_ended: bool = False


def configure(run_id: str, duration_minutes: float) -> None:
    """Called once at run start to set the time lock."""
    global _run_start, _run_duration_sec, _force_unlocked, _run_id, _session_ended
    _run_start = time.time()
    _run_duration_sec = duration_minutes * 60
    _force_unlocked = False
    _run_id = run_id
    _session_ended = False


def force_unlock() -> None:
    """Called when operator sends an early unlock signal."""
    global _force_unlocked
    _force_unlocked = True


def is_unlocked() -> bool:
    """Check if end_session is currently allowed."""
    if _force_unlocked:
        return True
    if _run_duration_sec <= 0:
        return True  # No time lock configured
    return time.time() >= _run_start + _run_duration_sec


def time_remaining_str() -> str:
    """Human-readable time remaining."""
    remaining = (_run_start + _run_duration_sec) - time.time()
    if remaining <= 0:
        return "0m"
    hours = int(remaining // 3600)
    minutes = int((remaining % 3600) // 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def elapsed_minutes() -> float:
    """Minutes elapsed since run start."""
    return (time.time() - _run_start) / 60


def has_ended() -> bool:
    return _session_ended


# --- Escalating work suggestions based on elapsed time ---

_DEPTH_LEVELS = [
    {
        "threshold_pct": 0.0,
        "label": "Phase 1: Critical fixes",
        "suggestion": (
            "Focus on CRITICAL and HIGH severity issues from SECURITY_AUDIT.md. "
            "Fix authentication gaps, SQL injection vectors, and credential exposure."
        ),
    },
    {
        "threshold_pct": 0.15,
        "label": "Phase 2: Bug fixes & error handling",
        "suggestion": (
            "Look for actual bugs, unhandled error paths, and edge cases. "
            "Check for missing null checks, race conditions, and uncaught exceptions."
        ),
    },
    {
        "threshold_pct": 0.30,
        "label": "Phase 3: Test coverage",
        "suggestion": (
            "Add test coverage for untested critical paths. Write integration tests "
            "for the gateway endpoints, SQL validation engine, and connector logic."
        ),
    },
    {
        "threshold_pct": 0.50,
        "label": "Phase 4: Performance & architecture",
        "suggestion": (
            "Profile hot paths and optimize. Look at connection pooling, query patterns, "
            "caching opportunities, and startup time. Consider architectural improvements."
        ),
    },
    {
        "threshold_pct": 0.70,
        "label": "Phase 5: Deep improvements",
        "suggestion": (
            "Go deeper: improve the SQL governance engine, add new connector types, "
            "harden the sandbox execution model, improve observability and logging. "
            "Run benchmarks and optimize based on results."
        ),
    },
    {
        "threshold_pct": 0.85,
        "label": "Phase 6: Polish & documentation",
        "suggestion": (
            "Final stretch. Clean up any rough edges, add inline documentation for "
            "complex logic, ensure all new code has tests, and verify the full "
            "system works end-to-end. Run the benchmark suite one final time."
        ),
    },
]


def _get_current_phase() -> dict:
    """Get the appropriate work phase based on elapsed time percentage."""
    if _run_duration_sec <= 0:
        return _DEPTH_LEVELS[0]

    pct = elapsed_minutes() / (_run_duration_sec / 60)
    result = _DEPTH_LEVELS[0]
    for level in _DEPTH_LEVELS:
        if pct >= level["threshold_pct"]:
            result = level
    return result


def build_denial_message() -> str:
    """Build the message returned when end_session is denied."""
    remaining = time_remaining_str()
    phase = _get_current_phase()
    return (
        f"SESSION LOCKED — you have {remaining} remaining in this improvement run. "
        f"You are not allowed to end the session yet.\n\n"
        f"Current phase: {phase['label']}\n"
        f"Suggested focus: {phase['suggestion']}\n\n"
        f"Keep working. Commit each improvement separately. "
        f"Call end_session again when you believe your work is complete — "
        f"it will be allowed once the time lock expires."
    )


# --- The MCP tool definition ---

@tool(
    "end_session",
    "End the current improvement session. This is the ONLY way to stop working. "
    "Call this when you have completed your improvements and want to finalize. "
    "The tool may be denied if the session time lock has not expired yet — "
    "in that case, continue working on the suggested focus area.",
    {"summary": str, "changes_made": int},
)
async def end_session_tool(args: dict[str, Any]) -> dict[str, Any]:
    """The agent's only exit. Denied until the time lock expires."""
    global _session_ended

    summary = args.get("summary", "No summary provided")
    changes = args.get("changes_made", 0)

    if is_unlocked():
        _session_ended = True
        # Log the successful end
        if _run_id:
            try:
                await db.log_audit(_run_id, "session_ended", {
                    "summary": summary,
                    "changes_made": changes,
                    "elapsed_minutes": round(elapsed_minutes(), 1),
                    "was_force_unlocked": _force_unlocked,
                })
            except Exception:
                pass

        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Session ended successfully.\n"
                        f"Summary: {summary}\n"
                        f"Changes made: {changes}\n"
                        f"Elapsed: {round(elapsed_minutes(), 1)} minutes\n\n"
                        f"Commit any remaining work now. The framework will push "
                        f"your branch and create a PR."
                    ),
                }
            ]
        }
    else:
        # Denied — tell the agent to keep working
        if _run_id:
            try:
                await db.log_audit(_run_id, "end_session_denied", {
                    "summary": summary,
                    "changes_made": changes,
                    "time_remaining": time_remaining_str(),
                    "elapsed_minutes": round(elapsed_minutes(), 1),
                })
            except Exception:
                pass

        return {
            "content": [
                {
                    "type": "text",
                    "text": build_denial_message(),
                }
            ]
        }


def create_session_mcp_server():
    """Create the MCP server with the end_session tool."""
    return create_sdk_mcp_server(
        name="session_gate",
        version="1.0.0",
        tools=[end_session_tool],
    )
