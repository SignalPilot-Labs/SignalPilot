# Copyright 2026 SignalPilot. All rights reserved.
"""Chat persistence endpoints for the notebook frontend.

Regular chat endpoints proxy the SignalPilot gateway with a local SQLite path
for gateway-less local conversations. Notion trace conversations are loaded
from the gateway-owned trace store.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

import httpx
from starlette.responses import JSONResponse

from signalpilot._server.ai.chat_store import (
    GatewayChatTraceStore,
    get_gateway_chat_trace_store,
    local_chat_db_path_for_app,
)
from signalpilot._server.api.deps import AppState
from signalpilot._server.auth.session_token import load_session_jwt
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

router = APIRouter()

_GATEWAY_URL = os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")
_SESSION_JWT = load_session_jwt()
_API_KEY = os.environ.get("SP_API_KEY", "")
_USE_GATEWAY = "SP_GATEWAY_URL" in os.environ or bool(_SESSION_JWT or _API_KEY)
_TRACE_SOURCES = {"notion", "slack"}


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS local_chat_conversations (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT 'New chat',
            source TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS local_chat_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            metadata_json TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (conversation_id)
                REFERENCES local_chat_conversations(id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_local_chat_conversations_session
            ON local_chat_conversations(session_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_local_chat_messages_conversation
            ON local_chat_messages(conversation_id, created_at ASC);
        """
    )
    try:
        conn.execute(
            "ALTER TABLE local_chat_conversations ADD COLUMN source TEXT NOT NULL DEFAULT ''"
        )
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    return conn


def _db_path(request: Request) -> Path:
    return local_chat_db_path_for_app(AppState(request))


def _current_session_id(request: Request) -> str:
    return request.headers.get("Sp-Session-Id") or "default"


def _is_notion_session(request: Request) -> bool:
    session_id = _current_session_id(request)
    return session_id.startswith(("session-notion-", "session-slack-"))


def _epoch_seconds(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return int(parsed.timestamp())
        except ValueError:
            pass
    return int(time.time())


def _conversation_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _trace_conversation_row(thread: dict[str, Any]) -> dict[str, Any]:
    source = thread.get("source") or "notion"
    return {
        "id": thread["thread_id"],
        "title": thread.get("title")
        or ("Slack analysis" if source == "slack" else "Notion analysis"),
        "source": source,
        "status": thread.get("status") or "",
        "notebook_path": thread.get("notebook_path") or "",
        "created_at": _epoch_seconds(thread.get("created_at")),
        "updated_at": _epoch_seconds(thread.get("updated_at")),
    }


def _message_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "metadata_json": row["metadata_json"],
        "created_at": row["created_at"],
    }


def _assistant_trace_message(
    message_id: str,
    payload: dict[str, Any],
    created_at: int,
) -> dict[str, Any]:
    content = payload.get("content")
    final_json: str | None = None
    if isinstance(content, str):
        final_json = _extract_final_json_content(content)
        if final_json is not None:
            payload = {**payload, "content": final_json}
    if (
        final_json is not None
        and not payload.get("thinking")
        and not payload.get("toolCalls")
    ):
        return {
            "id": message_id,
            "role": "assistant",
            "content": final_json,
            "metadata_json": None,
            "created_at": created_at,
        }
    return {
        "id": message_id,
        "role": "assistant",
        "content": json.dumps(payload),
        "metadata_json": None,
        "created_at": created_at,
    }


def _extract_final_json_content(content: str) -> str | None:
    decoder = json.JSONDecoder()
    candidates: list[Any] = []

    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", content):
        try:
            candidates.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            pass

    for index, char in enumerate(content):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(content[index:])
        except json.JSONDecodeError:
            continue
        candidates.append(parsed)

    for parsed in reversed(candidates):
        if not isinstance(parsed, dict):
            continue
        if (
            "summary" in parsed
            and ("finalAnswer" in parsed or "final_answer" in parsed)
            and ("notionComment" in parsed or "notion_comment" in parsed)
        ):
            return json.dumps(parsed, indent=2, ensure_ascii=False)
    return None


def _final_json_key(message: dict[str, Any]) -> str | None:
    if message.get("role") != "assistant":
        return None
    content = str(message.get("content") or "")
    final_json = _extract_final_json_content(content)
    if final_json is None:
        return None
    try:
        parsed = json.loads(final_json)
    except json.JSONDecodeError:
        return final_json
    if not isinstance(parsed, dict):
        return final_json
    key_fields = {
        "summary": parsed.get("summary"),
        "finalAnswer": parsed.get("finalAnswer") or parsed.get("final_answer"),
        "notionComment": parsed.get("notionComment")
        or parsed.get("notion_comment"),
    }
    return json.dumps(key_fields, sort_keys=True, ensure_ascii=False)


def _dedupe_final_json_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    last_index_by_key = {
        key: index
        for index, message in enumerate(messages)
        if (key := _final_json_key(message)) is not None
    }
    deduped: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        key = _final_json_key(message)
        if key is not None and last_index_by_key.get(key) != index:
            continue
        deduped.append(message)
    return deduped


def _merge_tool_only_trace_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") != "assistant":
            merged.append(message)
            continue
        try:
            payload = json.loads(str(message.get("content") or "{}"))
        except json.JSONDecodeError:
            merged.append(message)
            continue
        tool_calls = payload.get("toolCalls")
        is_tool_only = (
            isinstance(tool_calls, list)
            and bool(tool_calls)
            and not str(payload.get("content") or "").strip()
            and not str(payload.get("thinking") or "").strip()
        )
        if not is_tool_only or not merged or merged[-1].get("role") != "assistant":
            merged.append(message)
            continue
        try:
            previous_payload = json.loads(str(merged[-1].get("content") or "{}"))
        except json.JSONDecodeError:
            merged.append(message)
            continue
        if not any(
            key in previous_payload for key in ("content", "thinking", "toolCalls")
        ):
            merged.append(message)
            continue
        previous_tool_calls = previous_payload.get("toolCalls")
        if not isinstance(previous_tool_calls, list):
            previous_tool_calls = []
        previous_payload["toolCalls"] = [*previous_tool_calls, *tool_calls]
        merged[-1] = {
            **merged[-1],
            "content": json.dumps(previous_payload),
            "created_at": message.get("created_at", merged[-1].get("created_at")),
        }
    return merged


def _tool_call_from_event(event: dict[str, Any]) -> dict[str, Any]:
    idx = int(event.get("idx") or 0)
    return {
        "id": event.get("tool_call_id") or f"tool-{idx}",
        "name": event.get("tool_name") or "tool",
        "input": event.get("tool_input") or {},
    }


def _attach_tool_result(
    tool_calls: list[dict[str, Any]], event: dict[str, Any]
) -> None:
    content = str(event.get("content") or "")
    tool_call_id = str(event.get("tool_call_id") or "")
    target: dict[str, Any] | None = None
    if tool_call_id:
        target = next(
            (
                tool_call
                for tool_call in tool_calls
                if tool_call.get("id") == tool_call_id
                and "result" not in tool_call
            ),
            None,
        )
    if target is None:
        target = next(
            (
                tool_call
                for tool_call in reversed(tool_calls)
                if "result" not in tool_call
            ),
            None,
        )
    if target is None:
        target = _tool_call_from_event(event)
        tool_calls.append(target)
    target["result"] = content
    target["isError"] = bool(event.get("is_error"))


def _tool_progress_text(event: dict[str, Any]) -> str:
    tool_name = str(event.get("tool_name") or "")
    if "ToolSearch" in tool_name or "tool_search" in tool_name:
        return "Looking up the available tools for this analysis."
    if "get_lightweight_cell_map" in tool_name:
        return "Inspecting the current notebook state before editing."
    if "list_database_connections" in tool_name:
        return "Checking available governed data connections."
    if "schema_overview" in tool_name:
        return (
            "Scouting the database schema to find the relevant source tables."
        )
    if "list_tables" in tool_name:
        return "Listing available tables for the selected connection."
    if "query_database" in tool_name:
        return "Running a quick scouting query to understand the source data."
    if "edit_notebook" in tool_name:
        return "Writing the analysis trail into notebook cells."
    if "run_stale_cells" in tool_name or "run_cells" in tool_name:
        return "Running notebook cells to validate the analysis."
    if "get_notebook_errors" in tool_name:
        return "Checking the notebook for remaining errors."
    return "Running the next analysis step."


def _trace_event_messages(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    active_payload: dict[str, Any] | None = None
    active_kind: str | None = None
    active_idx = 0
    active_created_at = int(time.time())
    last_text_progress = ""

    def flush_active() -> None:
        nonlocal active_payload, active_kind, active_idx, active_created_at
        if active_payload is None:
            return
        payload: dict[str, Any] = {}
        content = str(active_payload.get("content") or "")
        thinking = str(active_payload.get("thinking") or "")
        tool_calls = active_payload.get("toolCalls")
        if content:
            payload["content"] = content
        else:
            payload["content"] = ""
        if thinking:
            payload["thinking"] = thinking
        if isinstance(tool_calls, list) and tool_calls:
            payload["toolCalls"] = tool_calls
        if (
            payload["content"]
            or payload.get("thinking")
            or payload.get("toolCalls")
        ):
            messages.append(
                _assistant_trace_message(
                    f"trace-{active_idx}",
                    payload,
                    active_created_at,
                )
            )
        active_payload = None
        active_kind = None

    def start_active(kind: str, event: dict[str, Any]) -> None:
        nonlocal active_payload, active_kind, active_idx, active_created_at
        active_payload = {"content": ""}
        if kind == "tool":
            active_payload["toolCalls"] = []
        active_kind = kind
        active_idx = int(event.get("idx") or 0)
        active_created_at = _epoch_seconds(event.get("created_at"))

    def add_progress_message(event: dict[str, Any]) -> None:
        nonlocal last_text_progress
        progress_text = _tool_progress_text(event)
        if last_text_progress == progress_text:
            return
        idx = int(event.get("idx") or 0)
        created_at = _epoch_seconds(event.get("created_at"))
        messages.append(
            _assistant_trace_message(
                f"trace-{idx}-progress",
                {"content": progress_text},
                created_at,
            )
        )
        last_text_progress = progress_text

    for event in events:
        event_type = str(event.get("type") or "")
        idx = int(event.get("idx") or 0)
        created_at = _epoch_seconds(event.get("created_at"))
        content = str(event.get("content") or "")

        if event_type == "user" or event.get("role") == "user":
            flush_active()
            messages.append(
                {
                    "id": f"trace-{idx}",
                    "role": "user",
                    "content": content,
                    "metadata_json": None,
                    "created_at": created_at,
                }
            )
            last_text_progress = ""
            continue

        if event_type in {"done", "block_start"}:
            continue

        if event_type in {"thinking", "thinking_delta"}:
            if active_kind == "tool":
                flush_active()
            if active_payload is None:
                start_active("text", event)
            existing = str(active_payload.get("thinking") or "")
            if event_type == "thinking":
                active_payload["thinking"] = content
            else:
                active_payload["thinking"] = existing + content
            continue

        if event_type == "text_delta":
            if active_kind == "tool":
                flush_active()
            if active_payload is None:
                start_active("text", event)
            active_payload["content"] = (
                str(active_payload.get("content") or "") + content
            )
            last_text_progress = str(active_payload["content"])
            continue

        if event_type == "text":
            if active_kind == "tool":
                flush_active()
            if active_payload is None:
                start_active("text", event)
            existing = str(active_payload.get("content") or "")
            if (
                existing
                and content
                and not (
                    content.startswith(existing)
                    or existing.startswith(content)
                )
            ):
                flush_active()
                start_active("text", event)
            active_payload["content"] = content
            last_text_progress = content
            continue

        if event_type == "error":
            flush_active()
            start_active("text", event)
            active_payload["content"] = content or "Agent run failed."
            last_text_progress = str(active_payload["content"])
            flush_active()
            continue

        if event_type == "tool_use":
            if active_kind == "text":
                flush_active()
            if active_payload is None:
                if not (
                    messages
                    and messages[-1]["role"] == "assistant"
                    and json.loads(messages[-1]["content"]).get("content")
                ):
                    add_progress_message(event)
                start_active("tool", event)
            tool_calls = active_payload.setdefault("toolCalls", [])
            if isinstance(tool_calls, list):
                tool_calls.append(_tool_call_from_event(event))
            continue

        if event_type == "tool_result":
            if active_kind == "text":
                flush_active()
            if active_payload is None:
                add_progress_message(event)
                start_active("tool", event)
            tool_calls = active_payload.setdefault("toolCalls", [])
            if isinstance(tool_calls, list):
                _attach_tool_result(tool_calls, event)
            continue

    flush_active()
    return _dedupe_final_json_messages(_merge_tool_only_trace_messages(messages))


def _trace_store(_request: Request) -> GatewayChatTraceStore:
    return get_gateway_chat_trace_store()


async def _trace_list_conversations(request: Request) -> dict[str, Any]:
    threads = await _trace_store(request).list_threads(_current_session_id(request))
    return {"conversations": [_trace_conversation_row(row) for row in threads]}


async def _trace_list_recent_notion_conversations(request: Request) -> dict[str, Any]:
    return await _trace_list_recent_source_conversations(request, "notion")


async def _trace_list_recent_source_conversations(
    request: Request, source: str
) -> dict[str, Any]:
    threads = await _trace_store(request).list_threads_by_source(source)
    return {"conversations": [_trace_conversation_row(row) for row in threads]}


async def _trace_get_conversation(
    request: Request, conversation_id: str
) -> dict[str, Any] | None:
    store = _trace_store(request)
    thread = await store.get_thread(conversation_id)
    if thread is None:
        return None
    messages = _trace_event_messages(
        await store.get_events(conversation_id, after_index=-1)
    )
    return {
        "conversation": _trace_conversation_row(thread),
        "messages": messages,
    }


def _local_create_conversation(
    request: Request, body: dict[str, Any]
) -> dict[str, Any]:
    now = int(time.time())
    conversation_id = str(body.get("id") or f"local-{uuid.uuid4().hex}")
    title = str(body.get("title") or "New chat")
    with _connect(_db_path(request)) as conn:
        conn.execute(
            """
            INSERT INTO local_chat_conversations (
                id, session_id, title, source, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                updated_at = excluded.updated_at
            """,
            (
                conversation_id,
                _current_session_id(request),
                title,
                "",
                now,
                now,
            ),
        )
    return {
        "id": conversation_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
    }


def _local_list_conversations(request: Request) -> dict[str, Any]:
    with _connect(_db_path(request)) as conn:
        rows = conn.execute(
            """
            SELECT id, title, source, created_at, updated_at
            FROM local_chat_conversations
            WHERE session_id = ?
            ORDER BY updated_at DESC
            LIMIT 100
            """,
            (_current_session_id(request),),
        ).fetchall()
    return {"conversations": [_conversation_row(row) for row in rows]}


def _local_get_conversation(
    request: Request, conversation_id: str
) -> dict[str, Any]:
    with _connect(_db_path(request)) as conn:
        conversation = conn.execute(
            """
            SELECT id, title, source, created_at, updated_at
            FROM local_chat_conversations
            WHERE id = ?
            """,
            (conversation_id,),
        ).fetchone()
        messages = conn.execute(
            """
            SELECT id, role, content, metadata_json, created_at
            FROM local_chat_messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        ).fetchall()
    return {
        "conversation": _conversation_row(conversation)
        if conversation is not None
        else None,
        "messages": [_message_row(row) for row in messages],
    }


def _local_delete_conversation(
    request: Request, conversation_id: str
) -> dict[str, Any]:
    with _connect(_db_path(request)) as conn:
        conn.execute(
            "DELETE FROM local_chat_conversations WHERE id = ?",
            (conversation_id,),
        )
    return {"ok": True}


def _local_append_message(
    request: Request, conversation_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    now = int(time.time())
    message_id = str(body.get("id") or f"msg-{uuid.uuid4().hex}")
    role = str(body.get("role") or "user")
    content = str(body.get("content") or "")
    metadata = body.get("metadata_json")
    if metadata is not None and not isinstance(metadata, str):
        metadata = json.dumps(metadata, sort_keys=True, default=str)
    with _connect(_db_path(request)) as conn:
        conn.execute(
            """
            INSERT INTO local_chat_messages (
                id, conversation_id, role, content, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (message_id, conversation_id, role, content, metadata, now),
        )
        conn.execute(
            """
            UPDATE local_chat_conversations
            SET updated_at = ?
            WHERE id = ?
            """,
            (now, conversation_id),
        )
    return {
        "id": message_id,
        "role": role,
        "content": content,
        "metadata_json": metadata,
        "created_at": now,
    }


def _local_list_messages(
    request: Request, conversation_id: str
) -> dict[str, Any]:
    with _connect(_db_path(request)) as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, metadata_json, created_at
            FROM local_chat_messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        ).fetchall()
    return {"messages": [_message_row(row) for row in rows]}


async def _gw(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    if not _USE_GATEWAY:
        return {
            "_error": True,
            "status": 503,
            "detail": "Gateway chat API is not configured.",
        }

    url = f"{_GATEWAY_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if _SESSION_JWT:
        headers["Authorization"] = f"Bearer {_SESSION_JWT}"
    elif _API_KEY:
        headers["Authorization"] = f"Bearer {_API_KEY}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(method, url, json=body if body else None, headers=headers)
    except httpx.TimeoutException as exc:
        return {"_error": True, "status": 504, "detail": str(exc)}
    except httpx.HTTPError as exc:
        return {"_error": True, "status": 502, "detail": str(exc)}

    if response.status_code >= 400:
        return {"_error": True, "status": response.status_code, "detail": response.text[:500]}
    if not response.content:
        return None
    try:
        return response.json()
    except json.JSONDecodeError:
        return response.text


def _respond(result: Any) -> JSONResponse:
    if isinstance(result, dict) and result.get("_error"):
        return JSONResponse(
            {"detail": result.get("detail", "Gateway error")},
            status_code=result.get("status", 502),
        )
    return JSONResponse(result)


# ── Conversations ────────────────────────────────────────────────


@router.post("/conversations")
async def create_conversation(request: Request) -> JSONResponse:
    body = await request.json()
    result = await _gw("POST", "/api/chat/conversations", body)
    if isinstance(result, dict) and result.get("_error"):
        return JSONResponse(_local_create_conversation(request, body))
    return _respond(result)


@router.get("/conversations")
async def list_conversations(request: Request) -> JSONResponse:
    source = request.query_params.get("source")
    if source in _TRACE_SOURCES:
        return JSONResponse(await _trace_list_recent_source_conversations(request, source))

    traced = await _trace_list_conversations(request)
    if traced["conversations"]:
        return JSONResponse(traced)

    qs = ""
    params = dict(request.query_params)
    if params:
        from urllib.parse import urlencode

        qs = "?" + urlencode(params)
    result = await _gw("GET", f"/api/chat/conversations{qs}")
    if isinstance(result, dict) and result.get("_error"):
        local = _local_list_conversations(request)
        if local.get("conversations"):
            return JSONResponse(local)
        return JSONResponse(await _trace_list_recent_notion_conversations(request))
    if (
        isinstance(result, dict)
        and isinstance(result.get("conversations"), list)
        and len(result["conversations"]) == 0
    ):
        fallback = await _trace_list_recent_notion_conversations(request)
        if fallback["conversations"]:
            return JSONResponse(fallback)
    return _respond(result)


@router.get("/conversations/{conversation_id}")
async def get_conversation(request: Request) -> JSONResponse:
    cid = request.path_params["conversation_id"]
    traced = await _trace_get_conversation(request, cid)
    if traced is not None:
        return JSONResponse(traced)

    result = await _gw("GET", f"/api/chat/conversations/{cid}")
    if isinstance(result, dict) and result.get("_error"):
        return JSONResponse(_local_get_conversation(request, cid))
    return _respond(result)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(request: Request) -> JSONResponse:
    cid = request.path_params["conversation_id"]
    result = await _gw("DELETE", f"/api/chat/conversations/{cid}")
    if isinstance(result, dict) and result.get("_error"):
        return JSONResponse(_local_delete_conversation(request, cid))
    return _respond(result)


# ── Messages ─────────────────────────────────────────────────────


@router.post("/conversations/{conversation_id}/messages")
async def append_message(request: Request) -> JSONResponse:
    cid = request.path_params["conversation_id"]
    body = await request.json()
    result = await _gw("POST", f"/api/chat/conversations/{cid}/messages", body)
    if isinstance(result, dict) and result.get("_error"):
        return JSONResponse(_local_append_message(request, cid, body))
    return _respond(result)


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(request: Request) -> JSONResponse:
    cid = request.path_params["conversation_id"]
    qs = ""
    params = dict(request.query_params)
    if params:
        from urllib.parse import urlencode

        qs = "?" + urlencode(params)
    result = await _gw("GET", f"/api/chat/conversations/{cid}/messages{qs}")
    if isinstance(result, dict) and result.get("_error"):
        return JSONResponse(_local_list_messages(request, cid))
    return _respond(result)
