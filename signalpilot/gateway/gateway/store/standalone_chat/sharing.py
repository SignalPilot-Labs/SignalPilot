"""Share grants and the read-only shared views of one standalone chat.

Forking lives in ``forking.py``. This module owns the grant lifecycle and
every read that a share token unlocks: the transcript snapshot, files, the
SQL trace, and query result pages.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayChatConversation,
    GatewayChatFile,
    GatewayChatMessage,
    GatewayChatRun,
    GatewayChatRunEvent,
    GatewayChatShareGrant,
    GatewayStructuredQueryResult,
    GatewayWorkspaceProject,
)
from gateway.models.standalone_chat import (
    SharedConversationDetail,
    SharedConversationInfo,
)
from gateway.standalone_chat import config as chat_config
from gateway.standalone_chat.domain import NONTERMINAL_RUN_STATUSES
from gateway.standalone_chat.sql_trace import list_sql_trace
from gateway.store.standalone_chat.files import (
    file_manifest_entry,
    get_shared_conversation_file,
    list_shared_conversation_files,
)
from gateway.store.standalone_chat.helpers import (
    _event_info,
    _message_info,
    _now,
    _owned_conversation_row,
    _token_usage,
)


def _share_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_share_grant(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
) -> tuple[GatewayChatShareGrant, str] | None:
    """Rotate the active grant and return the only copy of the raw token."""
    conversation = await _owned_conversation_row(
        db,
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation_id,
        lock=True,
    )
    if conversation is None:
        return None
    revoked_at = _now()
    await db.execute(
        update(GatewayChatShareGrant)
        .where(
            GatewayChatShareGrant.conversation_id == conversation_id,
            GatewayChatShareGrant.org_id == org_id,
            GatewayChatShareGrant.owner_user_id == user_id,
            GatewayChatShareGrant.state == "active",
        )
        .values(state="revoked", revoked_at=revoked_at)
    )
    token = secrets.token_urlsafe(32)
    grant = GatewayChatShareGrant(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        org_id=org_id,
        owner_user_id=user_id,
        token_hash=_share_token_hash(token),
        state="active",
    )
    db.add(grant)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(grant)
    return grant, token


async def revoke_share_grants(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
) -> bool:
    conversation = await _owned_conversation_row(
        db,
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        return False
    await db.execute(
        update(GatewayChatShareGrant)
        .where(
            GatewayChatShareGrant.conversation_id == conversation_id,
            GatewayChatShareGrant.org_id == org_id,
            GatewayChatShareGrant.owner_user_id == user_id,
            GatewayChatShareGrant.state == "active",
        )
        .values(state="revoked", revoked_at=_now())
    )
    await db.commit()
    return True


async def _shared_grant_row(
    db: AsyncSession,
    *,
    org_id: str,
    token: str,
    lock: bool = False,
) -> tuple[GatewayChatShareGrant, GatewayChatConversation] | None:
    if len(token) < 32 or len(token) > 128:
        return None
    query = (
        select(GatewayChatShareGrant, GatewayChatConversation)
        .join(
            GatewayChatConversation,
            GatewayChatConversation.id == GatewayChatShareGrant.conversation_id,
        )
        .where(
            GatewayChatShareGrant.org_id == org_id,
            GatewayChatShareGrant.token_hash == _share_token_hash(token),
            GatewayChatShareGrant.state == "active",
            GatewayChatConversation.org_id == org_id,
            GatewayChatConversation.user_id == GatewayChatShareGrant.owner_user_id,
            GatewayChatConversation.surface == "standalone",
            GatewayChatConversation.status == "active",
        )
    )
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).one_or_none()


async def _nonterminal_runs(
    db: AsyncSession,
    *,
    conversation_id: str,
) -> list[GatewayChatRun]:
    """Runs still in flight. Their messages, events, and queries stay private."""
    return list(
        (
            await db.execute(
                select(GatewayChatRun).where(
                    GatewayChatRun.conversation_id == conversation_id,
                    GatewayChatRun.status.in_(NONTERMINAL_RUN_STATUSES),
                )
            )
        ).scalars()
    )


def _belongs_to_run(message: GatewayChatMessage, run_ids: set[str], user_message_ids: set[str]) -> bool:
    metadata = message.metadata_json or {}
    if message.id in user_message_ids:
        return True
    for key in ("run_id", "clarification_for_run_id", "steering_for_run_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value in run_ids:
            return True
    return False


async def get_shared_conversation(
    db: AsyncSession,
    *,
    org_id: str,
    token: str,
) -> SharedConversationDetail | None:
    """Full read-only snapshot of the finished part of a shared chat.

    Everything that belongs to an in-flight run is left out: its user
    message, its events, and any file it is still writing.
    """
    shared = await _shared_grant_row(db, org_id=org_id, token=token)
    if shared is None:
        return None
    grant, conversation = shared
    project = (
        await db.execute(
            select(GatewayWorkspaceProject).where(
                GatewayWorkspaceProject.id == conversation.project_id,
                GatewayWorkspaceProject.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    runs = list(
        (
            await db.execute(
                select(GatewayChatRun)
                .where(GatewayChatRun.conversation_id == conversation.id)
                .order_by(GatewayChatRun.created_at)
            )
        ).scalars()
    )
    hidden_run_ids = {run.id for run in runs if run.status in NONTERMINAL_RUN_STATUSES}
    hidden_message_ids = {run.user_message_id for run in runs if run.id in hidden_run_ids}
    run_usage = {
        run.id: usage
        for run in runs
        if run.id not in hidden_run_ids and (usage := _token_usage(run.usage_json)) is not None
    }
    messages = list(
        (
            await db.execute(
                select(GatewayChatMessage)
                .where(
                    GatewayChatMessage.conversation_id == conversation.id,
                    GatewayChatMessage.org_id == org_id,
                    GatewayChatMessage.user_id == conversation.user_id,
                    GatewayChatMessage.role.in_(("user", "assistant")),
                )
                .order_by(GatewayChatMessage.sequence)
            )
        ).scalars()
    )
    events = list(
        (
            await db.execute(
                select(GatewayChatRunEvent)
                .where(
                    GatewayChatRunEvent.conversation_id == conversation.id,
                    GatewayChatRunEvent.org_id == org_id,
                )
                .order_by(GatewayChatRunEvent.created_at, GatewayChatRunEvent.sequence)
            )
        ).scalars()
    )
    files = await list_shared_conversation_files(
        db,
        org_id=org_id,
        owner_user_id=conversation.user_id,
        conversation_id=conversation.id,
    )
    return SharedConversationDetail(
        conversation=SharedConversationInfo(
            title=conversation.title or "New chat",
            project_name=(project.display_name or project.name) if project else None,
            origin=conversation.origin,
            model=conversation.model or chat_config.default_chat_model(),
            effort=conversation.effort or chat_config.default_chat_effort(),
            commit_sha=conversation.commit_sha,
            branch=conversation.branch or "main",
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        ),
        messages=[
            _message_info(row, run_usage=run_usage)
            for row in messages
            if not _belongs_to_run(row, hidden_run_ids, hidden_message_ids)
        ],
        run_events=[_event_info(row) for row in events if row.run_id not in hidden_run_ids],
        files=[file_manifest_entry(row) for row in files],
        shared_at=grant.created_at,
    )


async def list_shared_files(
    db: AsyncSession,
    *,
    org_id: str,
    token: str,
) -> list[GatewayChatFile] | None:
    """Return share-safe files for the grant. None when the grant is not active."""
    shared = await _shared_grant_row(db, org_id=org_id, token=token)
    if shared is None:
        return None
    _, conversation = shared
    return await list_shared_conversation_files(
        db,
        org_id=org_id,
        owner_user_id=conversation.user_id,
        conversation_id=conversation.id,
    )


async def get_shared_file(
    db: AsyncSession,
    *,
    org_id: str,
    token: str,
    file_id: str,
) -> GatewayChatFile | None:
    shared = await _shared_grant_row(db, org_id=org_id, token=token)
    if shared is None:
        return None
    _, conversation = shared
    return await get_shared_conversation_file(
        db,
        org_id=org_id,
        owner_user_id=conversation.user_id,
        conversation_id=conversation.id,
        file_id=file_id,
    )


async def list_shared_sql_trace(
    db: AsyncSession,
    *,
    org_id: str,
    token: str,
) -> list[dict] | None:
    """The owner's SQL trace for finished runs. None when the grant is not active."""
    shared = await _shared_grant_row(db, org_id=org_id, token=token)
    if shared is None:
        return None
    _, conversation = shared
    hidden_run_ids = {run.id for run in await _nonterminal_runs(db, conversation_id=conversation.id)}
    executions = await list_sql_trace(
        db,
        org_id=org_id,
        user_id=conversation.user_id,
        conversation_id=conversation.id,
    )
    return [entry for entry in executions if entry["run_id"] not in hidden_run_ids]


async def get_shared_query_result(
    db: AsyncSession,
    *,
    org_id: str,
    token: str,
    result_id: str,
) -> GatewayStructuredQueryResult | None:
    """One stored result of the shared chat, scoped to the owner and conversation."""
    shared = await _shared_grant_row(db, org_id=org_id, token=token)
    if shared is None:
        return None
    _, conversation = shared
    stored = (
        await db.execute(
            select(GatewayStructuredQueryResult).where(
                GatewayStructuredQueryResult.id == result_id,
                GatewayStructuredQueryResult.org_id == org_id,
                GatewayStructuredQueryResult.conversation_id == conversation.id,
                GatewayStructuredQueryResult.owner_user_id == conversation.user_id,
            )
        )
    ).scalar_one_or_none()
    if stored is None:
        return None
    if stored.run_id and any(
        run.id == stored.run_id for run in await _nonterminal_runs(db, conversation_id=conversation.id)
    ):
        return None
    return stored
