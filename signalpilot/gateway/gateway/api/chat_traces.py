"""Internal notebook chat trace endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..models.workspace import ChatTraceEventCreate, ChatTraceThreadUpsert
from ..security.scope_guard import RequireScope
from .deps import StoreD

router = APIRouter(prefix="/api/chat/traces")


@router.post("/threads", dependencies=[RequireScope("write")])
async def upsert_thread(body: ChatTraceThreadUpsert, store: StoreD):
    return await store.upsert_chat_trace_thread(body)


@router.get("/threads", dependencies=[RequireScope("read")])
async def list_threads(
    store: StoreD,
    session_id: str | None = Query(None),
    source: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    threads = await store.list_chat_trace_threads(
        session_id=session_id, source=source, limit=limit
    )
    return {"threads": threads}


@router.get("/threads/{thread_id}", dependencies=[RequireScope("read")])
async def get_thread(thread_id: str, store: StoreD):
    thread = await store.get_chat_trace_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Trace thread not found")
    return thread


@router.delete("/threads/{thread_id}/events", dependencies=[RequireScope("write")])
async def clear_events(thread_id: str, store: StoreD):
    if not await store.clear_chat_trace_events(thread_id):
        raise HTTPException(status_code=404, detail="Trace thread not found")
    return {"ok": True}


@router.post("/threads/{thread_id}/events", dependencies=[RequireScope("write")])
async def append_event(thread_id: str, body: ChatTraceEventCreate, store: StoreD):
    try:
        idx = await store.append_chat_trace_event(thread_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"idx": idx}


@router.get("/threads/{thread_id}/events", dependencies=[RequireScope("read")])
async def get_events(
    thread_id: str,
    store: StoreD,
    after_index: int = Query(-1),
):
    try:
        events = await store.get_chat_trace_events(
            thread_id, after_index=after_index
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"events": events}
