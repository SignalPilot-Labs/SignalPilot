"""Share grants, shared read views, and conversation forking."""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayChatArtifact,
    GatewayChatConversation,
    GatewayChatMessage,
    GatewayChatRun,
    GatewayChatShareGrant,
    GatewayChatUserPreference,
    GatewayWorkspaceProject,
)
from gateway.models.standalone_chat import (
    SharedConversationDetail,
    SharedConversationInfo,
    SharedMessageInfo,
)
from gateway.standalone_chat.domain import NONTERMINAL_RUN_STATUSES, TERMINAL_RUN_STATUSES
from gateway.standalone_chat.object_storage import conversation_prefix, runtime_object_key
from gateway.store.standalone_chat.helpers import (
    _now,
    _owned_conversation_row,
    _shared_artifact_info,
)


def _object_storage():
    """Resolve the storage factory through the package namespace at call time.

    Tests patch chat_object_storage on the package module. Read the name late
    so the patch takes effect."""
    from gateway.store import standalone_chat as chat_store

    return chat_store.chat_object_storage()

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


async def get_shared_conversation(
    db: AsyncSession,
    *,
    org_id: str,
    token: str,
) -> SharedConversationDetail | None:
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
    artifacts = list(
        (
            await db.execute(
                select(GatewayChatArtifact)
                .outerjoin(
                    GatewayChatRun,
                    GatewayChatRun.id == GatewayChatArtifact.run_id,
                )
                .where(
                    GatewayChatArtifact.conversation_id == conversation.id,
                    GatewayChatArtifact.org_id == org_id,
                    GatewayChatArtifact.user_id == conversation.user_id,
                    or_(
                        GatewayChatRun.id.is_(None),
                        GatewayChatRun.status.in_(TERMINAL_RUN_STATUSES),
                    ),
                )
                .order_by(GatewayChatArtifact.created_at)
            )
        ).scalars()
    )
    return SharedConversationDetail(
        conversation=SharedConversationInfo(
            title=conversation.title or "New chat",
            project_name=(project.display_name or project.name) if project else None,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        ),
        messages=[
            SharedMessageInfo(
                id=row.id,
                role=row.role,
                content=row.content,
                sequence=row.sequence,
                created_at=row.created_at,
            )
            for row in messages
        ],
        artifacts=[_shared_artifact_info(row) for row in artifacts],
        shared_at=grant.created_at,
    )


async def get_shared_artifact(
    db: AsyncSession,
    *,
    org_id: str,
    token: str,
    artifact_id: str,
) -> GatewayChatArtifact | None:
    shared = await _shared_grant_row(db, org_id=org_id, token=token)
    if shared is None:
        return None
    _, conversation = shared
    return (
        await db.execute(
            select(GatewayChatArtifact)
            .outerjoin(GatewayChatRun, GatewayChatRun.id == GatewayChatArtifact.run_id)
            .where(
                GatewayChatArtifact.id == artifact_id,
                GatewayChatArtifact.conversation_id == conversation.id,
                GatewayChatArtifact.org_id == org_id,
                GatewayChatArtifact.user_id == conversation.user_id,
                or_(
                    GatewayChatRun.id.is_(None),
                    GatewayChatRun.status.in_(TERMINAL_RUN_STATUSES),
                ),
            )
        )
    ).scalar_one_or_none()


async def fork_shared_conversation(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    token: str,
    per_query_budget_usd: float,
    chat_budget_usd: float,
) -> GatewayChatConversation | None:
    """Copy the share-safe snapshot into a new private conversation."""
    shared = await _shared_grant_row(db, org_id=org_id, token=token, lock=True)
    if shared is None:
        return None
    _, source = shared
    active_run = (
        await db.execute(
            select(GatewayChatRun.id).where(
                GatewayChatRun.conversation_id == source.id,
                GatewayChatRun.status.in_(NONTERMINAL_RUN_STATUSES),
            )
        )
    ).scalar_one_or_none()
    if active_run is not None:
        raise RuntimeError("Wait for the current answer to finish before forking this chat")

    messages = list(
        (
            await db.execute(
                select(GatewayChatMessage)
                .where(
                    GatewayChatMessage.conversation_id == source.id,
                    GatewayChatMessage.org_id == org_id,
                    GatewayChatMessage.user_id == source.user_id,
                    GatewayChatMessage.role.in_(("user", "assistant")),
                )
                .order_by(GatewayChatMessage.sequence)
            )
        ).scalars()
    )
    artifacts = list(
        (
            await db.execute(
                select(GatewayChatArtifact)
                .where(
                    GatewayChatArtifact.conversation_id == source.id,
                    GatewayChatArtifact.org_id == org_id,
                    GatewayChatArtifact.user_id == source.user_id,
                )
                .order_by(GatewayChatArtifact.created_at)
            )
        ).scalars()
    )

    now = time.time()
    fork = GatewayChatConversation(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=source.project_id,
        surface="standalone",
        origin=source.origin,
        branch=source.branch,
        commit_sha=source.commit_sha,
        per_query_budget_usd=per_query_budget_usd,
        chat_budget_usd=chat_budget_usd,
        forked_from_conversation_id=source.id,
        status="active",
        title=(source.title or "New chat")[:200],
        internal_summary=None,
        message_count=len(messages),
        total_tokens=0,
        total_cost_usd=0.0,
        created_at=now,
        updated_at=now,
    )
    db.add(fork)

    message_ids = {row.id: str(uuid.uuid4()) for row in messages}
    for sequence, row in enumerate(messages, start=1):
        db.add(
            GatewayChatMessage(
                id=message_ids[row.id],
                org_id=org_id,
                user_id=user_id,
                project_id=source.project_id,
                conversation_id=fork.id,
                role=row.role,
                content=row.content,
                metadata_json={"surface": "standalone", "forked": True},
                sequence=sequence,
                created_at=row.created_at,
            )
        )

    artifact_ids = {row.id: str(uuid.uuid4()) for row in artifacts}
    copied_run_ids: dict[str, str] = {}
    storage = _object_storage()
    try:
        for row in artifacts:
            copied_run_id = copied_run_ids.setdefault(row.run_id, str(uuid.uuid4()))
            copied_artifact_id = artifact_ids[row.id]
            object_key = None
            source_object_key = None
            byte_size = row.byte_size
            content_hash = row.content_hash
            if row.storage_kind == "object":
                if not row.object_key:
                    raise RuntimeError("Shared artifact object is unavailable")
                object_key = runtime_object_key(
                    org_id=org_id,
                    conversation_id=fork.id,
                    run_id=copied_run_id,
                    category="forked-artifacts",
                    object_id=copied_artifact_id,
                    filename=row.filename,
                )
                copied = await storage.copy(
                    source_key=row.object_key,
                    destination_key=object_key,
                )
                byte_size = copied.byte_size
                content_hash = copied.content_hash or row.content_hash
                if row.source_object_key:
                    source_filename = f"{row.filename.rsplit('.', 1)[0]}.csv"
                    source_object_key = runtime_object_key(
                        org_id=org_id,
                        conversation_id=fork.id,
                        run_id=copied_run_id,
                        category="forked-artifact-sources",
                        object_id=copied_artifact_id,
                        filename=source_filename,
                    )
                    await storage.copy(
                        source_key=row.source_object_key,
                        destination_key=source_object_key,
                    )
            db.add(
                GatewayChatArtifact(
                    id=copied_artifact_id,
                    org_id=org_id,
                    user_id=user_id,
                    conversation_id=fork.id,
                    run_id=copied_run_id,
                    assistant_message_id=message_ids.get(row.assistant_message_id or ""),
                    kind=row.kind,
                    filename=row.filename,
                    mime_type=row.mime_type,
                    snapshot_json=row.snapshot_json,
                    binary_data=row.binary_data,
                    storage_kind=row.storage_kind,
                    object_key=object_key,
                    source_object_key=source_object_key,
                    byte_size=byte_size,
                    content_hash=content_hash,
                    provenance_json={
                        **dict(row.provenance_json or {}),
                        "forked_from_artifact_id": row.id,
                        "forked_from_conversation_id": source.id,
                    },
                    freshness_at=row.freshness_at,
                    assumptions=list(row.assumptions or []),
                    exclusions=list(row.exclusions or []),
                    caveats=list(row.caveats or []),
                    parent_artifact_id=artifact_ids.get(row.parent_artifact_id or ""),
                    created_at=row.created_at,
                )
            )
        await db.commit()
    except Exception:
        await db.rollback()
        if any(row.storage_kind == "object" for row in artifacts):
            try:
                await storage.delete_prefix(conversation_prefix(org_id, fork.id))
            except Exception:
                pass
        raise
    await db.refresh(fork)
    return fork


async def get_fork_preview(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    token: str,
) -> dict[str, Any] | None:
    shared = await _shared_grant_row(db, org_id=org_id, token=token)
    if shared is None:
        return None
    _, source = shared
    project = await db.get(GatewayWorkspaceProject, source.project_id)
    if project is None or project.org_id != org_id or not source.commit_sha:
        return None
    preference = (
        await db.execute(
            select(GatewayChatUserPreference).where(
                GatewayChatUserPreference.org_id == org_id,
                GatewayChatUserPreference.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    return {
        "project_id": project.id,
        "project_name": project.display_name or project.name,
        "commit_sha": source.commit_sha,
        "per_query_budget_usd": preference.default_per_query_budget_usd if preference else 0.25,
        "chat_budget_usd": preference.default_chat_budget_usd if preference else 1.0,
        "warehouse_cost_notice": (
            "New questions run against live warehouse data and may incur warehouse cost. "
            "The dbt project remains frozen at the displayed commit."
        ),
    }
