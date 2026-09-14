"""Closes tool calls orphaned when a run is re-claimed after a worker restart.

A restarted worker resumes the agent session as a fresh turn, so tool calls
that were in flight in the previous attempt (subagent spawns included) can
never report back. Their ``tool_started`` events would otherwise stay open
forever in every consumer of the event stream.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayChatRunEvent

INTERRUPTED_SUMMARY = "Interrupted by runtime recovery"


def interrupted_tool_completions(events: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """``tool_completed`` payloads for every started call without a completion.

    ``events`` are ``(event_type, payload)`` pairs in sequence order. Children
    of a subagent close before their spawn so consumers fold them in order.
    """
    open_calls: dict[str, dict[str, Any]] = {}
    for event_type, payload in events:
        call_id = payload.get("tool_call_id")
        if not isinstance(call_id, str) or not call_id:
            continue
        if event_type == "tool_started":
            open_calls[call_id] = payload
        elif event_type == "tool_completed":
            open_calls.pop(call_id, None)
    children = [p for p in open_calls.values() if p.get("parent_tool_call_id")]
    spawns = [p for p in open_calls.values() if not p.get("parent_tool_call_id")]
    completions = []
    for started in children + spawns:
        payload: dict[str, Any] = {
            "tool_call_id": started["tool_call_id"],
            "tool": started.get("tool"),
            "error": False,
            "summary": INTERRUPTED_SUMMARY,
            "result": {"kind": "text", "summary": INTERRUPTED_SUMMARY},
            "interrupted": True,
            "v": 1,
        }
        if started.get("parent_tool_call_id"):
            payload["parent_tool_call_id"] = started["parent_tool_call_id"]
        completions.append(payload)
    return completions


async def load_interrupted_tool_completions(db: AsyncSession, run_id: str) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(GatewayChatRunEvent)
            .where(
                GatewayChatRunEvent.run_id == run_id,
                GatewayChatRunEvent.event_type.in_(("tool_started", "tool_completed")),
            )
            .order_by(GatewayChatRunEvent.sequence)
        )
    ).all()
    return interrupted_tool_completions([(row.event_type, row.payload_json or {}) for row in rows])
