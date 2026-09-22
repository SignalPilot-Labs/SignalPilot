"""
SDK message -> AgentEvent translation for the notebook AI chat.

This module owns the loop that drains ``ClaudeSDKClient.receive_messages()``
and turns each SDK message into the ``AgentEvent`` records consumed by the
SSE layer. It is pure translation: no option building, no thread or event
loop management. See ``claude_agent.py`` for the orchestration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from signalpilot import _loggers
from signalpilot._server.ai.claude_agent_state import (
    AgentEvent,
    clip_tool_result_for_event,
    tool_result_text,
)

if TYPE_CHECKING:
    import queue

    from signalpilot._server.ai.claude_agent_state import _ActiveAgent

__all__ = [
    "MAX_PLAN_CONTINUATIONS",
    "PLAN_CONTINUATION_PROMPT",
    "STEERING_GRACE_SECONDS",
    "_SdkStreamState",
    "_rate_limit_diagnostic",
    "_relay_sdk_messages",
    "_result_message_content",
    "open_todo_count",
]

LOGGER = _loggers.sp_logger()

# Run completion guard: when the model ends its turn with TodoWrite items
# still open and no error, it is asked to continue at most this many times
# per run before the result is accepted as final.
MAX_PLAN_CONTINUATIONS = 2
PLAN_CONTINUATION_PROMPT = (
    "Continue with the remaining plan items. "
    "If they cannot be completed, say why."
)
# After a ResultMessage the durable gateway queue gets this long to deliver
# an interjection accepted while the run was still marked running. The
# steering lock, not this window, is what makes acceptance race-free.
STEERING_GRACE_SECONDS = 1.0


def open_todo_count(todo_input: dict[str, Any] | None) -> int:
    """Count TodoWrite items whose status is not ``completed``."""
    if not isinstance(todo_input, dict):
        return 0
    todos = todo_input.get("todos")
    if not isinstance(todos, list):
        return 0
    return sum(
        1
        for item in todos
        if isinstance(item, dict)
        and str(item.get("status") or "").strip().lower() != "completed"
    )


def _result_message_content(message: Any) -> str:
    """Return the SDK's error text without replacing or paraphrasing it."""
    result = getattr(message, "result", None)
    if result is not None and str(result):
        return str(result)

    errors = getattr(message, "errors", None)
    if isinstance(errors, (list, tuple)):
        details = [str(error) for error in errors if error is not None]
        if details:
            return "\n".join(details)
    elif errors:
        return str(errors)

    # An SDK result with no textual error still has an exact structured
    # representation. Surface it instead of inventing a human-friendly cause.
    return repr(message)


def _rate_limit_diagnostic(info: Any) -> dict[str, Any]:
    """Copy the SDK rate-limit payload without interpreting its meaning."""
    return {
        "status": getattr(info, "status", None),
        "resets_at": getattr(info, "resets_at", None),
        "rate_limit_type": getattr(info, "rate_limit_type", None),
        "utilization": getattr(info, "utilization", None),
        "overage_status": getattr(info, "overage_status", None),
        "overage_resets_at": getattr(info, "overage_resets_at", None),
        "overage_disabled_reason": getattr(
            info, "overage_disabled_reason", None
        ),
        "raw": getattr(info, "raw", None),
    }


@dataclass
class _SdkStreamState:
    """Mutable counters shared between the relay loop and its caller.

    ``turn_count`` is read by the caller's error handlers after the relay
    raises, so it lives here rather than in a local variable.
    """

    turn_count: int = 0
    latest_rate_limit_info: dict[str, Any] | None = None
    # The most recent TodoWrite tool input: the run's live plan.
    last_todo_input: dict[str, Any] | None = None
    plan_continuations: int = 0


def _result_event(
    msg: Any, state: _SdkStreamState
) -> AgentEvent:
    """Build the terminal ``done``/``error`` event for an SDK ResultMessage."""
    cost = getattr(msg, "total_cost_usd", None)
    usage = getattr(msg, "usage", None)
    subtype = str(getattr(msg, "subtype", "") or "")
    result_is_error = bool(getattr(msg, "is_error", False))
    return AgentEvent(
        type="error" if result_is_error else "done",
        content=(
            _result_message_content(msg)
            if result_is_error
            else ""
        ),
        is_error=result_is_error,
        cost_usd=cost,
        usage=usage if isinstance(usage, dict) else None,
        turn=state.turn_count,
        result_subtype=subtype,
        stop_reason=str(
            getattr(msg, "stop_reason", "") or ""
        ),
        num_turns=int(
            getattr(msg, "num_turns", state.turn_count) or 0
        ),
        diagnostic_context={
            "result_subtype": subtype,
            "stop_reason": str(
                getattr(msg, "stop_reason", "") or ""
            ),
            "api_error_status": getattr(
                msg, "api_error_status", None
            ),
            "duration_ms": getattr(msg, "duration_ms", None),
            "duration_api_ms": getattr(
                msg, "duration_api_ms", None
            ),
            "sdk_session_id": str(
                getattr(msg, "session_id", "") or ""
            ),
            **(
                {"rate_limit": state.latest_rate_limit_info}
                if state.latest_rate_limit_info
                else {}
            ),
        },
    )


async def _continue_open_plan(
    client: Any, msg: Any, state: _SdkStreamState
) -> bool:
    """Run completion guard for a non-error ResultMessage.

    When the run's last TodoWrite plan still has open items, send one
    bounded continuation query instead of finishing. Returns True when a
    continuation was sent (the caller keeps draining the client).
    """
    if bool(getattr(msg, "is_error", False)):
        return False
    open_items = open_todo_count(state.last_todo_input)
    if open_items == 0:
        return False
    if state.plan_continuations >= MAX_PLAN_CONTINUATIONS:
        LOGGER.warning(
            "Run ended with %s open plan items after %s continuations; "
            "accepting the result",
            open_items,
            state.plan_continuations,
        )
        return False
    state.plan_continuations += 1
    LOGGER.info(
        "Run ended with %s open plan items; sending continuation %s of %s",
        open_items,
        state.plan_continuations,
        MAX_PLAN_CONTINUATIONS,
    )
    await client.query(PLAN_CONTINUATION_PROMPT)
    return True


async def _relay_sdk_messages(
    client: Any,
    agent_state: _ActiveAgent,
    event_queue: queue.Queue[Any],
    state: _SdkStreamState,
) -> None:
    """Drain ``client.receive_messages()`` into ``event_queue`` as AgentEvents.

    Returns when the SDK emits a ResultMessage and no steering turn is
    pending. Exceptions (including CancelledError) propagate to the caller.
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ResultMessage,
        StreamEvent,
        TextBlock,
        ThinkingBlock,
        ToolResultBlock,
        ToolUseBlock,
        UserMessage,
    )
    from claude_agent_sdk.types import RateLimitEvent

    async for msg in client.receive_messages():
        if isinstance(msg, AssistantMessage):
            state.turn_count += 1
            # Set when this message was produced inside a subagent
            # (an Agent tool spawn) — used to group its work.
            parent_id = getattr(msg, "parent_tool_use_id", None) or ""
            for block in msg.content:
                if isinstance(block, ThinkingBlock):
                    # Final authoritative thinking — replaces accumulated deltas
                    event_queue.put(
                        AgentEvent(
                            type="thinking",
                            content=block.thinking,
                            parent_tool_call_id=parent_id,
                            turn=state.turn_count,
                        )
                    )
                elif isinstance(block, TextBlock):
                    # Final authoritative text — replaces accumulated deltas
                    event_queue.put(
                        AgentEvent(
                            type="text",
                            content=block.text,
                            parent_tool_call_id=parent_id,
                            turn=state.turn_count,
                        )
                    )
                elif isinstance(block, ToolUseBlock):
                    if block.name == "TodoWrite" and not parent_id:
                        state.last_todo_input = (
                            dict(block.input)
                            if isinstance(block.input, dict)
                            else None
                        )
                    event_queue.put(
                        AgentEvent(
                            type="tool_use",
                            tool_name=block.name,
                            tool_input=block.input,
                            tool_call_id=getattr(block, "id", ""),
                            parent_tool_call_id=parent_id,
                            turn=state.turn_count,
                        )
                    )

        elif isinstance(msg, UserMessage):
            content = msg.content
            parent_id = getattr(msg, "parent_tool_use_id", None) or ""
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, ToolResultBlock):
                        result_str = (
                            tool_result_text(block.content)
                            if hasattr(block, "content")
                            else str(block)
                        )
                        event_queue.put(
                            AgentEvent(
                                type="tool_result",
                                content=clip_tool_result_for_event(
                                    result_str
                                ),
                                result_chars=len(result_str),
                                tool_call_id=getattr(
                                    block, "tool_use_id", ""
                                ),
                                is_error=getattr(
                                    block, "is_error", False
                                ),
                                parent_tool_call_id=parent_id,
                                turn=state.turn_count,
                            )
                        )

        elif isinstance(msg, ResultMessage):
            if await _continue_open_plan(client, msg, state):
                continue
            event_queue.put(_result_event(msg, state))
            # A ResultMessage terminates one SDK query, not
            # necessarily this live client. Give the durable
            # gateway queue a brief chance to deliver an
            # interjection that was accepted while the run was
            # still marked running, then consume its next result.
            await asyncio.sleep(STEERING_GRACE_SECONDS)
            # Decide under the steering lock: steer_agent increments the
            # counter under the same lock before it sends its query, and
            # refuses once ``closing`` is set, so no accepted message can
            # be lost between this check and the client's exit.
            with agent_state.steering_lock:
                if agent_state.pending_steering_turns > 0:
                    agent_state.pending_steering_turns -= 1
                    keep_alive = True
                else:
                    agent_state.closing = True
                    keep_alive = False
            if keep_alive:
                continue
            break  # Session complete for this query

        elif isinstance(msg, RateLimitEvent):
            # This is state, not an error message. A rejected event
            # is followed by the SDK ResultMessage containing the
            # provider's actual text. Retain the raw state for the
            # diagnostic panel and do not pre-empt that result.
            state.latest_rate_limit_info = _rate_limit_diagnostic(
                msg.rate_limit_info
            )

        elif isinstance(msg, StreamEvent):
            event = msg.event
            event_type = event.get("type", "")
            delta = event.get("delta", {})
            text = delta.get("text", "")
            thinking = delta.get("thinking", "")
            parent_id = getattr(msg, "parent_tool_use_id", None) or ""

            if text:
                event_queue.put(
                    AgentEvent(
                        type="text_delta",
                        content=text,
                        parent_tool_call_id=parent_id,
                        turn=state.turn_count,
                    )
                )
            elif thinking:
                event_queue.put(
                    AgentEvent(
                        type="thinking_delta",
                        content=thinking,
                        parent_tool_call_id=parent_id,
                        turn=state.turn_count,
                    )
                )
            elif event_type == "content_block_start":
                block = event.get("content_block", {})
                event_queue.put(
                    AgentEvent(
                        type="block_start",
                        content=block.get("type", ""),
                        turn=state.turn_count,
                    )
                )
