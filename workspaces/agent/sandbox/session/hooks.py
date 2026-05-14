"""SessionHooks — SDK hook implementations for tool logging and subagent tracking.

All six SDK hooks (PreToolUse, PostToolUse, PostToolUseFailure,
SubagentStart, SubagentStop, Stop) live here. The Session class
delegates hook registration to this module via build_hooks().
"""

import logging
import time
from collections import deque
from typing import Callable

from claude_agent_sdk.types import (
    HookContext,
    HookInput,
    HookMatcher,
    SyncHookJSONOutput,
)

from constants import TASK_TOOL_NAME
from models import ToolContext
from session.utils import log_audit, log_tool_call, summarize

log = logging.getLogger("sandbox.session.hooks")


class SessionHooks:
    """SDK hook implementations for a single session.

    Public API:
        build_hooks() -> dict   (hook registration for ClaudeAgentOptions)
    """

    def __init__(self, run_id: str, emit: Callable[[dict], None]) -> None:
        self._run_id = run_id
        self._emit = emit
        self._pre_tool_times: dict[str, float] = {}
        self._subagent_start_times: dict[str, float] = {}
        self._subagent_last_tool: dict[str, float] = {}
        self._subagent_types: dict[str, str] = {}
        self._pending_task_tool_use_ids: deque[str] = deque()
        self._subagent_parent_tuids: dict[str, str] = {}

    def build_hooks(self) -> dict:
        """Build SDK hook registrations."""
        return {
            "PreToolUse": [HookMatcher(hooks=[self._hook_pre_tool])],
            "PostToolUse": [HookMatcher(hooks=[self._hook_post_tool])],
            "PostToolUseFailure": [HookMatcher(hooks=[self._hook_post_tool_failure])],
            "SubagentStart": [HookMatcher(hooks=[self._hook_subagent_start])],
            "SubagentStop": [HookMatcher(hooks=[self._hook_subagent_stop])],
            "Stop": [HookMatcher(hooks=[self._hook_stop])],
        }

    # ── Tool hooks ────────────────────────────────────────────────────

    async def _hook_pre_tool(
        self,
        hook_input: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        """Log pre-tool to DB. Emit tool_use event for agent stuck tracking."""
        tool_context = self._resolve_tool_context(hook_input, tool_use_id, False)

        if tool_context.agent_id:
            self._subagent_last_tool[tool_context.agent_id] = time.time()

        self._pre_tool_times[tool_context.tool_use_id] = time.time()
        tool_input = hook_input.get("tool_input", {})
        await log_tool_call(
            self._run_id,
            "pre",
            tool_context,
            summarize(tool_input),
            None,
        )
        # Queue parent Task tool_use_id for the SubagentStart that will
        # fire next. The SDK has no direct payload link between Agent
        # PreToolUse and SubagentStart, but it serializes them 1:1 even
        # for parallel Task calls (verified empirically).
        if tool_context.tool_name == TASK_TOOL_NAME:
            if tool_use_id is None:
                raise RuntimeError(
                    f"PreToolUse for {TASK_TOOL_NAME} fired without tool_use_id"
                )
            self._pending_task_tool_use_ids.append(tool_use_id)
        self._emit({"event": "tool_use", "data": {"agent_id": tool_context.agent_id}})
        return SyncHookJSONOutput()

    async def _hook_post_tool(
        self,
        hook_input: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        """Log post-tool to DB with duration."""
        tool_context = self._resolve_tool_context(hook_input, tool_use_id, True)
        response = hook_input.get("tool_response")
        out = summarize(response) if response is not None else None
        await log_tool_call(self._run_id, "post", tool_context, None, out)
        self._emit({"event": "tool_done", "data": {"agent_id": tool_context.agent_id}})
        return SyncHookJSONOutput()

    async def _hook_post_tool_failure(
        self,
        hook_input: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        """Log failed tool to DB with error. Fires instead of PostToolUse on failure."""
        tool_context = self._resolve_tool_context(hook_input, tool_use_id, True)
        error = hook_input.get("error", "unknown error")
        await log_tool_call(self._run_id, "post", tool_context, None, {"error": error})
        self._emit({"event": "tool_done", "data": {"agent_id": tool_context.agent_id}})
        return SyncHookJSONOutput()

    def _resolve_tool_context(
        self,
        hook_input: HookInput,
        tool_use_id: str | None,
        compute_duration: bool,
    ) -> ToolContext:
        """Extract shared fields from hook_input into a ToolContext."""
        tool_name = hook_input.get("tool_name", "unknown")
        agent_id = hook_input.get("agent_id")
        tid = tool_use_id or ""
        sid = hook_input.get("session_id")
        duration_ms = None
        if compute_duration and tid in self._pre_tool_times:
            duration_ms = int((time.time() - self._pre_tool_times.pop(tid)) * 1000)
        role = self._subagent_types.get(agent_id, "worker") if agent_id else "worker"
        return ToolContext(
            tool_name=tool_name,
            tool_use_id=tid,
            agent_id=agent_id,
            session_id=sid,
            role=role,
            duration_ms=duration_ms,
        )

    # ── Subagent hooks ────────────────────────────────────────────────

    async def _hook_subagent_start(
        self,
        hook_input: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        """Track subagent, log to DB, emit event for agent stuck detection."""
        agent_id = hook_input.get("agent_id", "")
        agent_type = hook_input.get("agent_type", "")
        if not agent_id or not agent_type:
            raise RuntimeError(
                f"SubagentStart missing agent_id/agent_type: "
                f"agent_id={agent_id!r} agent_type={agent_type!r}"
            )
        if not self._pending_task_tool_use_ids:
            raise RuntimeError(
                f"SubagentStart for {agent_id} with no pending Agent "
                f"PreToolUse — parent link lost"
            )
        parent_tuid = self._pending_task_tool_use_ids.popleft()
        self._subagent_parent_tuids[agent_id] = parent_tuid
        self._subagent_start_times[agent_id] = time.time()
        self._subagent_types[agent_id] = agent_type
        await log_audit(
            self._run_id,
            "subagent_start",
            {
                "agent_id": agent_id,
                "agent_type": agent_type,
                "parent_tool_use_id": parent_tuid,
            },
        )
        self._emit(
            {
                "event": "subagent_start",
                "data": {
                    "agent_id": agent_id,
                    "agent_type": agent_type,
                    "parent_tool_use_id": parent_tuid,
                },
            }
        )
        return SyncHookJSONOutput()

    async def _hook_subagent_stop(
        self,
        hook_input: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        """Clean up tracking, log final text + parent link to DB, emit event."""
        agent_id = hook_input.get("agent_id", "")
        if not agent_id:
            raise RuntimeError("SubagentStop missing agent_id")
        parent_tuid = self._subagent_parent_tuids.pop(agent_id, None)
        if parent_tuid is None:
            raise RuntimeError(
                f"SubagentStop for {agent_id} with no recorded parent "
                f"tool_use_id — subagent_start never fired for it"
            )
        final_text = hook_input.get("last_assistant_message", "")
        self._subagent_start_times.pop(agent_id, None)
        self._subagent_last_tool.pop(agent_id, None)
        self._subagent_types.pop(agent_id, None)
        await log_audit(
            self._run_id,
            "subagent_complete",
            {
                "agent_id": agent_id,
                "parent_tool_use_id": parent_tuid,
                "final_text": final_text,
            },
        )
        self._emit(
            {
                "event": "subagent_stop",
                "data": {
                    "agent_id": agent_id,
                    "parent_tool_use_id": parent_tuid,
                },
            }
        )
        return SyncHookJSONOutput()

    # ── Stop hook ─────────────────────────────────────────────────────

    async def _hook_stop(
        self,
        hook_input: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        """Log agent stop to DB."""
        await log_audit(
            self._run_id,
            "agent_stop",
            {"reason": hook_input.get("stop_reason", "unknown")},
        )
        return SyncHookJSONOutput()
