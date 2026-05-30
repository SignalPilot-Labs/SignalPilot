"""Chat conversation and message endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..models.workspace import ChatMessageCreate, ConversationCreate, ConversationInfo
from ..security.scope_guard import RequireScope
from .deps import StoreD

router = APIRouter(prefix="/api/chat")


@router.post("/conversations", status_code=201, response_model=ConversationInfo, dependencies=[RequireScope("write")])
async def create_conversation(body: ConversationCreate, store: StoreD):
    return await store.create_conversation(project_id=body.project_id, title=body.title, model=body.model)


@router.get("/conversations", dependencies=[RequireScope("read")])
async def list_conversations(
    store: StoreD,
    project_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    convs, total = await store.list_conversations(project_id=project_id, limit=limit, offset=offset)
    return {"conversations": convs, "total": total}


@router.get("/conversations/{conversation_id}", dependencies=[RequireScope("read")])
async def get_conversation(conversation_id: str, store: StoreD):
    conv = await store.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    try:
        messages, _ = await store.list_messages(conversation_id, limit=200)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"conversation": conv, "messages": messages}


@router.delete("/conversations/{conversation_id}", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_conversation(conversation_id: str, store: StoreD):
    if not await store.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.post("/conversations/{conversation_id}/messages", status_code=201, dependencies=[RequireScope("write")])
async def append_message(conversation_id: str, body: ChatMessageCreate, store: StoreD):
    try:
        return await store.append_message(
            conversation_id, role=body.role, content=body.content, metadata_json=body.metadata_json
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/conversations/{conversation_id}/messages", dependencies=[RequireScope("read")])
async def list_messages(
    conversation_id: str,
    store: StoreD,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    try:
        messages, total = await store.list_messages(conversation_id, limit=limit, offset=offset)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"messages": messages, "total": total}
