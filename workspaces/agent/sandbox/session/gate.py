"""SessionGate — MCP tools for round/session lifecycle control.

Provides `end_round` and `end_session` tools that the orchestrator
calls to signal round completion or run termination. `end_session`
is denied while the time lock has more than EARLY_EXIT_THRESHOLD_MIN
remaining, unless the session has been explicitly unlocked.
"""

import logging
import time
from typing import Any, Callable

from claude_agent_sdk import tool, create_sdk_mcp_server

from constants import EARLY_EXIT_THRESHOLD_MIN, SECONDS_PER_MINUTE
from session.utils import log_audit

log = logging.getLogger("sandbox.session.gate")


class SessionGate:
    """MCP server with end_round and end_session tools.

    Public API:
        build_mcp(config) -> MCP server for ClaudeAgentOptions
    """

    def __init__(
        self,
        run_id: str,
        emit: Callable[[dict], None],
        mark_ended: Callable[[], None],
        is_unlocked: Callable[[], bool],
    ) -> None:
        self._run_id = run_id
        self._emit = emit
        self._mark_ended = mark_ended
        self._is_unlocked = is_unlocked

    def build_mcp(self, config: dict) -> Any:
        """Build MCP server with end_round + end_session tools."""
        duration_min: float = config["duration_minutes"]
        start: float = config["start_time"]
        run_id = self._run_id
        emit = self._emit
        mark_ended = self._mark_ended
        is_unlocked = self._is_unlocked

        @tool(
            "end_round",
            (
                "End THIS round so the Python loop can commit and start the"
                " next round. Use when the plan → build → review cycle is"
                " done for this round but the overall task is not yet"
                " complete. Does NOT end the whole run — use `end_session`"
                " for that."
            ),
            {"summary": str},
        )
        async def end_round_tool(args: dict[str, Any]) -> dict[str, Any]:
            summary = args["summary"]
            mark_ended()
            emit({"event": "end_round", "data": {"summary": summary}})
            return {"content": [{"type": "text", "text": "Round ended."}]}

        @tool(
            "end_session",
            (
                "End the ENTIRE run. Call only when there is nothing more"
                " to build, fix, or verify across any future round. Denied"
                " while the time lock has time remaining."
            ),
            {"summary": str},
        )
        async def end_session_tool(args: dict[str, Any]) -> dict[str, Any]:
            elapsed_sec = time.time() - start
            elapsed_min = elapsed_sec / SECONDS_PER_MINUTE
            remaining_min = duration_min - elapsed_min
            unlocked = (
                duration_min <= 0
                or remaining_min <= EARLY_EXIT_THRESHOLD_MIN
                or is_unlocked()
            )

            if unlocked:
                await log_audit(
                    run_id,
                    "session_ended",
                    {
                        "summary": args["summary"],
                        "elapsed_minutes": round(elapsed_min, 1),
                    },
                )
                mark_ended()
                emit(
                    {
                        "event": "end_session",
                        "data": {
                            "summary": args["summary"],
                            "elapsed_minutes": round(elapsed_min, 1),
                        },
                    }
                )
                return {"content": [{"type": "text", "text": "Session ended."}]}

            await log_audit(
                run_id,
                "end_session_denied",
                {"remaining_minutes": round(remaining_min, 1)},
            )
            emit(
                {
                    "event": "end_session_denied",
                    "data": {"remaining_minutes": round(remaining_min, 1)},
                }
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"SESSION LOCKED — {round(remaining_min, 1)}m remaining. "
                            "Keep working and start another round. Call `end_round` if "
                            "this round's cycle is complete."
                        ),
                    }
                ]
            }

        self._end_round = end_round_tool
        self._end_session = end_session_tool

        return create_sdk_mcp_server(
            name="session_gate",
            tools=[end_round_tool, end_session_tool],
        )
