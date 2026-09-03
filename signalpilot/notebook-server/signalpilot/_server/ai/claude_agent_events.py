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

from signalpilot._server.ai.claude_agent_state import (
    AgentEvent,
    clip_tool_result_for_event,
    tool_result_text,
)

if TYPE_CHECKING:
    import queue

    from signalpilot._server.ai.claude_agent_state import _ActiveAgent

__all__ = [
    "_SdkStreamState",
    "_rate_limit_diagnostic",
    "_relay_sdk_messages",
    "_result_message_content",
]


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
            event_queue.put(_result_event(msg, state))
            # A ResultMessage terminates one SDK query, not
            # necessarily this live client. Give the durable
            # gateway queue a brief chance to deliver an
            # interjection that was accepted while the run was
            # still marked running, then consume its next result.
            await asyncio.sleep(1.0)
            if agent_state.pending_steering_turns > 0:
                agent_state.pending_steering_turns -= 1
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
