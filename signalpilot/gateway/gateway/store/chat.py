"""Chat conversation and message CRUD operations."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayChatConversation, GatewayChatMessage
from ..models.workspace import ChatMessageInfo, ConversationInfo


async def create_conversation(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project_id: str | None = None,
    title: str | None = None,
    model: str | None = None,
) -> ConversationInfo:
    now = time.time()
    chat_session_id = str(uuid.uuid4())
    row = GatewayChatConversation(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=project_id,
        title=title,
        agent_session_id=chat_session_id,
        model=model,
        message_count=0,
        total_tokens=0,
        total_cost_usd=0.0,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    return _conv_info(row)


async def list_conversations(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ConversationInfo], int]:
    base = select(GatewayChatConversation).where(
        GatewayChatConversation.org_id == org_id,
        GatewayChatConversation.user_id == user_id,
    )
    if project_id:
        base = base.where(GatewayChatConversation.project_id == project_id)

    total = (await session.execute(select(sa_func.count()).select_from(base.subquery()))).scalar() or 0
    q = base.order_by(GatewayChatConversation.updated_at.desc()).offset(offset).limit(limit)
    result = await session.execute(q)
    return [_conv_info(r) for r in result.scalars()], total


async def get_conversation(
    session: AsyncSession, *, org_id: str, user_id: str, conversation_id: str
) -> ConversationInfo | None:
    q = select(GatewayChatConversation).where(
        GatewayChatConversation.org_id == org_id,
        GatewayChatConversation.user_id == user_id,
        GatewayChatConversation.id == conversation_id,
    )
    row = (await session.execute(q)).scalar_one_or_none()
    return _conv_info(row) if row else None


async def delete_conversation(
    session: AsyncSession, *, org_id: str, user_id: str, conversation_id: str
) -> bool:
    q = select(GatewayChatConversation).where(
        GatewayChatConversation.org_id == org_id,
        GatewayChatConversation.user_id == user_id,
        GatewayChatConversation.id == conversation_id,
    )
    row = (await session.execute(q)).scalar_one_or_none()
    if not row:
        return False
    await session.execute(
        sa_delete(GatewayChatMessage).where(GatewayChatMessage.conversation_id == conversation_id)
    )
    await session.delete(row)
    await session.commit()
    return True


async def append_message(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    role: str,
    content: str,
    metadata_json: dict | None = None,
) -> ChatMessageInfo:
    if user_id is None:
        raise ValueError("user_id required")
    conv_q = select(GatewayChatConversation).where(
        GatewayChatConversation.org_id == org_id,
        GatewayChatConversation.user_id == user_id,
        GatewayChatConversation.id == conversation_id,
    )
    conv = (await session.execute(conv_q)).scalar_one_or_none()
    if not conv:
        raise ValueError(f"Conversation {conversation_id} not found")

    seq = conv.message_count + 1
    now = time.time()
    msg = GatewayChatMessage(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=conv.project_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        metadata_json=metadata_json,
        sequence=seq,
        created_at=now,
    )
    session.add(msg)
    conv.message_count = seq
    conv.updated_at = now
    await session.commit()
    return _msg_info(msg)


async def list_messages(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ChatMessageInfo], int]:
    if user_id is None:
        raise ValueError("user_id required")
    conv_exists = (
        await session.execute(
            select(GatewayChatConversation).where(
                GatewayChatConversation.id == conversation_id,
                GatewayChatConversation.org_id == org_id,
                GatewayChatConversation.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if conv_exists is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    base = select(GatewayChatMessage).where(
        GatewayChatMessage.org_id == org_id,
        GatewayChatMessage.conversation_id == conversation_id,
    )
    total = (await session.execute(select(sa_func.count()).select_from(base.subquery()))).scalar() or 0
    q = base.order_by(GatewayChatMessage.sequence.asc()).offset(offset).limit(limit)
    result = await session.execute(q)
    return [_msg_info(r) for r in result.scalars()], total


def _conv_info(row: GatewayChatConversation) -> ConversationInfo:
    return ConversationInfo(
        id=row.id,
        org_id=row.org_id,
        user_id=row.user_id,
        project_id=row.project_id,
        title=row.title,
        agent_session_id=row.agent_session_id,
        model=row.model,
        message_count=row.message_count,
        total_tokens=row.total_tokens,
        total_cost_usd=row.total_cost_usd,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _msg_info(row: GatewayChatMessage) -> ChatMessageInfo:
    return ChatMessageInfo(
        id=row.id,
        conversation_id=row.conversation_id,
        role=row.role,
        content=row.content,
        metadata_json=row.metadata_json,
        sequence=row.sequence,
        created_at=row.created_at,
    )
