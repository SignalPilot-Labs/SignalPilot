"""Transport breaker for gateway MCP tools, as Agent SDK hooks.

A transport failure is a tool result whose text carries one of the
``TRANSPORT_SIGNATURES`` (a Streamable HTTP error, a lost MCP session, a
502 from a deploy window, or the JSON-RPC ``-32600`` code). The breaker
counts consecutive transport failures per run:

* PostToolUse and PostToolUseFailure record the result; a clean result
  resets the counter.
* PreToolUse denies every ``mcp__signalpilot__*`` and
  ``mcp__standalone-chat__*`` call while the breaker is open, with the
  concrete wait (2, 5, then 15 seconds).
* After ``MAX_CONSECUTIVE_FAILURES`` the breaker is terminal: the hook
  stops the agent and ``transport_unavailable(run_key)`` returns True so
  the execution loop can end the run with
  ``public_error_code="gateway_unavailable"``.

The execution endpoint reads the flag with ``transport_unavailable`` or
``gateway_unavailable_error``; the run key is the agent chat session id
passed to ``_build_agent_options_kwargs``.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any

from signalpilot import _loggers

LOGGER = _loggers.sp_logger()

__all__ = [
    "BACKOFF_SECONDS",
    "GATEWAY_TOOL_PREFIXES",
    "GATEWAY_UNAVAILABLE_CODE",
    "MAX_CONSECUTIVE_FAILURES",
    "TRANSPORT_SIGNATURES",
    "TransportBreaker",
    "breaker_for_run",
    "build_transport_breaker_hooks",
    "clear_breaker",
    "gateway_unavailable_error",
    "is_gateway_tool",
    "is_transport_failure",
    "transport_unavailable",
]

TRANSPORT_SIGNATURES: tuple[str, ...] = (
    "Streamable HTTP error",
    "Session not found",
    "502 Bad Gateway",
    "-32600",
)
GATEWAY_TOOL_PREFIXES: tuple[str, ...] = (
    "mcp__signalpilot__",
    "mcp__standalone-chat__",
)
BACKOFF_SECONDS: tuple[int, ...] = (2, 5, 15)
MAX_CONSECUTIVE_FAILURES = 3
GATEWAY_UNAVAILABLE_CODE = "gateway_unavailable"
GATEWAY_UNAVAILABLE_MESSAGE = (
    "The SignalPilot gateway did not answer three tool calls in a row. "
    "Retry the request in a minute."
)


def is_gateway_tool(tool_name: str) -> bool:
    return str(tool_name or "").startswith(GATEWAY_TOOL_PREFIXES)


def _response_text(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    try:
        return json.dumps(response, default=str)
    except (TypeError, ValueError):
        return str(response)


def is_transport_failure(response: Any) -> bool:
    """True when a tool result text carries a transport signature."""
    text = _response_text(response)
    return any(signature in text for signature in TRANSPORT_SIGNATURES)


@dataclass
class TransportBreaker:
    """Consecutive transport failure state for one run."""

    run_key: str
    consecutive_failures: int = 0
    open_until: float = 0.0
    transport_unavailable: bool = False
    last_failure_text: str = ""
    denied_calls: int = field(default=0)

    def record_failure(self, text: str, *, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.consecutive_failures += 1
        self.last_failure_text = text[:300]
        index = min(self.consecutive_failures, len(BACKOFF_SECONDS)) - 1
        self.open_until = now + BACKOFF_SECONDS[index]
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            self.transport_unavailable = True
        LOGGER.warning(
            "Gateway transport failure run=%s consecutive=%s open_for=%ss terminal=%s",
            self.run_key,
            self.consecutive_failures,
            BACKOFF_SECONDS[index],
            self.transport_unavailable,
        )

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.open_until = 0.0

    def record_result(self, response: Any, *, now: float | None = None) -> bool:
        """Record one gateway tool result. Returns True on a transport failure."""
        if is_transport_failure(response):
            self.record_failure(_response_text(response), now=now)
            return True
        self.record_success()
        return False

    def wait_seconds(self, *, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        return max(0, math.ceil(self.open_until - now))

    def is_open(self, *, now: float | None = None) -> bool:
        return self.transport_unavailable or self.wait_seconds(now=now) > 0

    def deny_reason(self, *, now: float | None = None) -> str | None:
        """The PreToolUse deny reason, or None when calls may proceed."""
        if self.transport_unavailable:
            return (
                "SignalPilot gateway unavailable after "
                f"{self.consecutive_failures} transport failures. "
                "Stop and report that the gateway is unavailable."
            )
        wait = self.wait_seconds(now=now)
        if wait > 0:
            return f"SignalPilot gateway unavailable; wait {wait} s then retry"
        return None


_BREAKERS: dict[str, TransportBreaker] = {}


def breaker_for_run(run_key: str, *, reset: bool = False) -> TransportBreaker:
    """The breaker for ``run_key``; ``reset`` starts a fresh count."""
    breaker = _BREAKERS.get(run_key)
    if breaker is None or reset:
        breaker = TransportBreaker(run_key=run_key)
        _BREAKERS[run_key] = breaker
    return breaker


def clear_breaker(run_key: str) -> None:
    _BREAKERS.pop(run_key, None)


def transport_unavailable(run_key: str) -> bool:
    """True once the run's breaker tripped; read by the execution loop."""
    breaker = _BREAKERS.get(run_key)
    return bool(breaker and breaker.transport_unavailable)


def gateway_unavailable_error(run_key: str) -> dict[str, Any] | None:
    """The public error payload for a tripped run, or None."""
    breaker = _BREAKERS.get(run_key)
    if breaker is None or not breaker.transport_unavailable:
        return None
    return {
        "public_error_code": GATEWAY_UNAVAILABLE_CODE,
        "public_error_message": GATEWAY_UNAVAILABLE_MESSAGE,
        "consecutive_failures": breaker.consecutive_failures,
        "last_failure": breaker.last_failure_text,
    }


def build_transport_breaker_hooks(run_key: str) -> dict[str, list[Any]]:
    """``ClaudeAgentOptions.hooks`` entries for the breaker of ``run_key``."""
    from claude_agent_sdk import HookMatcher

    breaker = breaker_for_run(run_key, reset=True)
    matcher = "|".join(f"{prefix}.*" for prefix in GATEWAY_TOOL_PREFIXES)

    async def pre_tool_use(
        hook_input: dict[str, Any], _tool_use_id: str | None, _context: Any
    ) -> dict[str, Any]:
        tool_name = str(hook_input.get("tool_name") or "")
        if not is_gateway_tool(tool_name):
            return {}
        reason = breaker.deny_reason()
        if reason is None:
            return {}
        breaker.denied_calls += 1
        output: dict[str, Any] = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
        if breaker.transport_unavailable:
            output["continue_"] = False
            output["stopReason"] = reason
        return output

    async def post_tool_use(
        hook_input: dict[str, Any], _tool_use_id: str | None, _context: Any
    ) -> dict[str, Any]:
        tool_name = str(hook_input.get("tool_name") or "")
        if not is_gateway_tool(tool_name):
            return {}
        response = hook_input.get("tool_response")
        if hook_input.get("hook_event_name") == "PostToolUseFailure":
            response = hook_input.get("error")
        breaker.record_result(response)
        return {}

    return {
        "PreToolUse": [HookMatcher(matcher=matcher, hooks=[pre_tool_use])],
        "PostToolUse": [HookMatcher(matcher=matcher, hooks=[post_tool_use])],
        "PostToolUseFailure": [
            HookMatcher(matcher=matcher, hooks=[post_tool_use])
        ],
    }
