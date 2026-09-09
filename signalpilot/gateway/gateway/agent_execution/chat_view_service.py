"""Read-only UI projection of the existing chat messages and run events."""

import json

from sqlalchemy import select

from gateway.db.models import GatewayChatMessage, GatewayChatRun, GatewayChatRunEvent
from gateway.mcp.context import mcp_allowed_connection_var
from gateway.store import Store
from gateway.store.standalone_chat.helpers import _event_info

from .service import AgentService

EVENT_FIELDS = {
    "text_delta": {"delta", "parent_tool_call_id"},
    "thinking_delta": {"delta", "parent_tool_call_id"},
    "tool_started": {"tool", "tool_call_id", "parent_tool_call_id", "label", "plan"},
    "tool_completed": {"tool", "tool_call_id", "parent_tool_call_id", "error", "summary"},
    "status": {"status", "reset_text", "chat_url"},
    "runtime_boot": {"phase", "label", "status"},
    "progress": {"label"},
    "error": {
        "error", "message", "code", "error_code", "error_type", "error_stage",
        "raw_error", "stderr", "full_trace", "diagnostic_context",
        "raw_error_truncated", "stderr_truncated",
    },
    "clarification_requested": {"question", "message"},
    "query_approval_requested": {"message", "question"},
}

PAGE_BYTES = 1024 * 1024
LABEL_CHARS = 140
PLAN_ITEMS = 12
PLAN_STATUSES = {"pending", "in_progress", "completed"}


def _plan_items(todos):
    """The agent's own plan steps, text only, capped in count and length."""
    if not isinstance(todos, list):
        return []
    items = []
    for todo in todos[:PLAN_ITEMS]:
        if not isinstance(todo, dict) or not isinstance(todo.get("content"), str) or not todo["content"].strip():
            continue
        item = {
            "content": " ".join(todo["content"].split())[:LABEL_CHARS],
            "status": todo.get("status") if todo.get("status") in PLAN_STATUSES else "pending",
        }
        active = todo.get("activeForm")
        if isinstance(active, str) and active.strip():
            item["active"] = " ".join(active.split())[:LABEL_CHARS]
        items.append(item)
    return items


def project_event(event_type, payload):
    """Keep only display-safe fields; derive the query description as ``label``."""
    projected = {key: value for key, value in payload.items() if key in EVENT_FIELDS[event_type]}
    tool = str(payload.get("tool", ""))
    tool_input = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    if event_type == "tool_started" and tool.endswith("query_database"):
        description = tool_input.get("description")
        if isinstance(description, str) and description.strip():
            projected["label"] = " ".join(description.split())[:LABEL_CHARS]
    if event_type == "tool_started" and tool.endswith("TodoWrite"):
        plan = _plan_items(tool_input.get("todos"))
        if plan:
            projected["plan"] = plan
    if event_type == "tool_completed" and not isinstance(projected.get("summary"), str):
        projected.pop("summary", None)
    return projected


def _page(items):
    page, size = [], 0
    for item in items:
        item_size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        if item_size > PAGE_BYTES:
            raise ValueError("Chat content exceeds the inline display limit. Open this chat in SignalPilot for the complete content.")
        if size + item_size > PAGE_BYTES:
            break
        page.append(item)
        size += item_size
    return page


async def read_chat_view(
    org_id, user_id, thread_id, run_id=None, after_sequence=0, after_message_sequence=0,
):
    if after_message_sequence < 0:
        raise ValueError("Message cursor must be nonnegative")
    service = AgentService()
    state = await service.get(org_id, user_id, thread_id, after_sequence, run_id)
    data = state.model_dump(mode="json", exclude_none=True)
    async with service.factory() as db:
        run = await db.scalar(select(GatewayChatRun).where(
            GatewayChatRun.id == state.run_id,
            GatewayChatRun.conversation_id == thread_id,
            GatewayChatRun.org_id == org_id,
            GatewayChatRun.user_id == user_id,
        ))
        if run is None:
            raise ValueError("Agent chat run not found")
        allowed = mcp_allowed_connection_var.get(None)
        if allowed:
            project = await Store(db, org_id=org_id, user_id=user_id).get_workspace_project(run.project_id)
            if project is None or project.connection_name != allowed:
                raise ValueError("Chat is outside this credential's connection scope")
        high_water = run.last_event_sequence
        rows = (await db.scalars(
            select(GatewayChatRunEvent).where(
                GatewayChatRunEvent.run_id == state.run_id,
                GatewayChatRunEvent.org_id == org_id,
                GatewayChatRunEvent.user_id == user_id,
                GatewayChatRunEvent.sequence > after_sequence,
                GatewayChatRunEvent.sequence <= high_water,
                GatewayChatRunEvent.event_type.in_(EVENT_FIELDS),
            ).order_by(GatewayChatRunEvent.sequence).limit(101)
        )).all()
        messages = (await db.scalars(
            select(GatewayChatMessage).where(
                GatewayChatMessage.conversation_id == thread_id,
                GatewayChatMessage.org_id == org_id,
                GatewayChatMessage.user_id == user_id,
                GatewayChatMessage.role.in_(["user", "assistant"]),
                GatewayChatMessage.sequence > after_message_sequence,
            ).order_by(GatewayChatMessage.sequence).limit(51)
        )).all()
    events = []
    for row in rows[:100]:
        event = _event_info(row).model_dump(mode="json")
        event["payload"] = project_event(row.event_type, event["payload"])
        events.append(event)
    event_page = _page(events)
    page = _page([{
        "id": row.id, "role": row.role, "content": row.content,
        "sequence": row.sequence, "created_at": row.created_at,
        "run_id": (row.metadata_json or {}).get("run_id"),
    } for row in messages[:50]])
    more_events = len(rows) > len(event_page)
    data.update(
        events=event_page,
        next_sequence=event_page[-1]["sequence"] if more_events else high_water,
        has_more=more_events,
        messages=page,
        next_message_sequence=page[-1]["sequence"] if page else after_message_sequence,
        has_more_messages=len(messages) > len(page),
    )
    data.pop("next_action", None)
    data.pop("summary", None)
    if data.get("question"):
        if len(data["question"].encode("utf-8")) > PAGE_BYTES:
            raise ValueError("Chat question exceeds the inline display limit. Open this chat in SignalPilot.")
    return data
