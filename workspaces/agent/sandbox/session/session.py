"""Session — a single Claude SDK session running in the sandbox.

Thin lifecycle wrapper. Hooks live in session.hooks, MCP gate tools
in session.gate, permission gating in session.security.
"""

import asyncio
import logging
from typing import Callable

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from constants import SESSION_EVENT_QUEUE_SIZE
from db.constants import resolve_sdk_model
from session.gate import SessionGate
from session.hooks import SessionHooks
from session.security import SecurityGate
from session.utils import log_audit, parse_agents, serialize_message

log = logging.getLogger("sandbox.session")


class Session:
    """A single Claude SDK session running in the sandbox.

    Public API (used by SessionManager):
        run()           — start the SDK loop
        events          — asyncio.Queue of SSE events
        client          — ClaudeSDKClient (set after run starts)
        task            — asyncio.Task wrapping run()
        unlocked        — force-unlock flag for time gate
    """

    def __init__(self, session_id: str, options_dict: dict) -> None:
        self.session_id = session_id
        self.options_dict = options_dict
        self.events: asyncio.Queue = asyncio.Queue(maxsize=SESSION_EVENT_QUEUE_SIZE)
        self.client: ClaudeSDKClient | None = None
        self.task: asyncio.Task | None = None
        self._ended = False
        self.unlocked = False
        self._hooks = SessionHooks(self._run_id, self._emit)
        self._gate = SessionGate(
            self._run_id,
            self._emit,
            self._mark_ended,
            lambda: self.unlocked,
        )

    @property
    def _run_id(self) -> str:
        """Run ID from options."""
        return self.options_dict.get("run_id", "")

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def run(self) -> None:
        """Run the SDK session, pushing events to the queue."""
        try:
            options = self._build_options()
            async with ClaudeSDKClient(options=options) as client:
                self.client = client
                await client.query(self.options_dict["initial_prompt"])
                async for message in client.receive_messages():
                    event = serialize_message(message)
                    if event:
                        self._emit(event)
                    if self._ended:
                        break
            self._emit({"event": "session_end", "data": {}})
        except asyncio.CancelledError:
            self._emit({"event": "session_end", "data": {"reason": "cancelled"}})
        except Exception as e:
            log.error("Session %s error: %s", self.session_id, e, exc_info=True)
            self._emit({"event": "session_error", "data": {"error": str(e)}})

    def _mark_ended(self) -> None:
        """Called by SessionGate when end_round/end_session fires."""
        self._ended = True

    def _emit(self, event: dict) -> None:
        """Put event on queue. Drops oldest if full."""
        try:
            self.events.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("Session %s queue full, dropping oldest", self.session_id)
            try:
                self.events.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self.events.put_nowait(event)
            except asyncio.QueueFull:
                pass

    # ── Options building ──────────────────────────────────────────────

    def _build_options(self) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions from the options dict."""
        opts = self.options_dict
        gate = SecurityGate(opts["github_repo"], opts["branch_name"])
        mcp = dict(opts.get("mcp_servers") or {})
        gate_cfg = opts.get("session_gate")
        if gate_cfg:
            mcp["session_gate"] = self._gate.build_mcp(gate_cfg)

        agents_raw = opts.get("agents")
        agents = parse_agents(agents_raw) if agents_raw else None

        return ClaudeAgentOptions(
            model=resolve_sdk_model(opts["model"]),
            fallback_model=(
                resolve_sdk_model(opts["fallback_model"])
                if opts.get("fallback_model")
                else None
            ),
            effort=opts["effort"],
            system_prompt=opts["system_prompt"],
            permission_mode="bypassPermissions",
            can_use_tool=self._permission_callback(gate),
            cwd=opts["cwd"],
            add_dirs=opts["add_dirs"],
            setting_sources=opts["setting_sources"],
            max_budget_usd=opts["max_budget_usd"],
            include_partial_messages=True,
            resume=opts.get("resume"),
            mcp_servers=mcp,
            agents=agents,
            hooks=self._hooks.build_hooks(),
        )

    def _permission_callback(self, gate: SecurityGate) -> Callable:
        """Create permission callback bound to a SecurityGate."""

        async def _check(
            tool_name: str,
            input_data: dict,
            context: ToolPermissionContext,
        ) -> PermissionResultAllow | PermissionResultDeny:
            deny = gate.check_permission(tool_name, input_data)
            if deny:
                await log_audit(
                    self._run_id,
                    "permission_denied",
                    {"tool_name": tool_name, "reason": deny},
                )
                return PermissionResultDeny(message=deny)
            return PermissionResultAllow(updated_input=input_data)

        return _check
