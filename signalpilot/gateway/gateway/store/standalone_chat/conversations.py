"""Conversation CRUD: create, list, detail, rename, and archive."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayChatArtifact,
    GatewayChatConversation,
    GatewayChatMessage,
    GatewayChatObjectDeletion,
    GatewayChatRun,
    GatewayChatRunEvent,
    GatewayChatShareGrant,
    GatewayReportRefresh,
    GatewaySavedReport,
    GatewaySavedReportVersion,
    GatewayWorkspaceProject,
)
from gateway.models.standalone_chat import (
    ChatArtifactInfo,
    StandaloneConversationDetail,
    StandaloneConversationInfo,
)
from gateway.standalone_chat import config as chat_config
from gateway.standalone_chat.domain import RunStatus
from gateway.standalone_chat.object_storage import conversation_prefix
from gateway.store.standalone_chat.helpers import (
    _artifact_info,
    _event_info,
    _message_info,
    _now,
    _owned_conversation_row,
    _run_info,
)


async def create_conversation_with_run(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project: GatewayWorkspaceProject,
    branch: str,
    message: str,
    commit_sha: str | None = None,
    per_query_budget_usd: float = 0.25,
    chat_budget_usd: float = 1.0,
    message_metadata: dict[str, Any] | None = None,
    commit: bool = True,
    origin: str = "user",
) -> tuple[GatewayChatConversation, GatewayChatRun]:
    """Atomically create the first conversation, message, and queued run."""
    now = time.time()
    conversation = GatewayChatConversation(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=project.id,
        surface="standalone",
        origin=origin,
        branch=branch,
        commit_sha=commit_sha,
        per_query_budget_usd=per_query_budget_usd,
        chat_budget_usd=chat_budget_usd,
        status="active",
        title="New chat",
        message_count=1,
        total_tokens=0,
        total_cost_usd=0.0,
        created_at=now,
        updated_at=now,
    )
    user_message = GatewayChatMessage(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=project.id,
        conversation_id=conversation.id,
        role="user",
        content=message.strip(),
        metadata_json={"surface": "standalone", **(message_metadata or {})},
        sequence=1,
        created_at=now,
    )
    run = GatewayChatRun(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation.id,
        project_id=project.id,
        user_message_id=user_message.id,
        status=RunStatus.queued.value,
        runtime_env=chat_config.runtime_env(),
    )
    db.add_all([conversation, user_message, run])
    if not commit:
        await db.flush()
        return conversation, run
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(run)
    return conversation, run


async def create_empty_conversation(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project: GatewayWorkspaceProject,
    branch: str,
    commit_sha: str,
    title: str,
) -> GatewayChatConversation:
    """Create a Data Chat thread without inventing a user prompt or starting a run."""
    now = time.time()
    conversation = GatewayChatConversation(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=project.id,
        surface="standalone",
        origin="user",
        branch=branch,
        commit_sha=commit_sha,
        status="active",
        title=title[:200],
        message_count=0,
        total_tokens=0,
        total_cost_usd=0.0,
        created_at=now,
        updated_at=now,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def list_conversations(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    limit: int = 100,
    offset: int = 0,
) -> list[StandaloneConversationInfo]:
    """List the caller's active conversations, newest first.

    One round trip. The latest run status per conversation comes from a
    window-function subquery instead of one query per conversation. The
    database is remote, so query count is the latency budget.
    """
    latest_runs = (
        select(
            GatewayChatRun.conversation_id,
            GatewayChatRun.status,
            func.row_number()
            .over(
                partition_by=GatewayChatRun.conversation_id,
                order_by=GatewayChatRun.created_at.desc(),
            )
            .label("recency"),
        )
        .where(
            GatewayChatRun.org_id == org_id,
            GatewayChatRun.user_id == user_id,
        )
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                GatewayChatConversation,
                GatewayWorkspaceProject,
                latest_runs.c.status,
            )
            .join(
                GatewayWorkspaceProject,
                and_(
                    GatewayWorkspaceProject.id == GatewayChatConversation.project_id,
                    GatewayWorkspaceProject.org_id == GatewayChatConversation.org_id,
                ),
                isouter=True,
            )
            .join(
                latest_runs,
                and_(
                    latest_runs.c.conversation_id == GatewayChatConversation.id,
                    latest_runs.c.recency == 1,
                ),
                isouter=True,
            )
            .where(
                GatewayChatConversation.org_id == org_id,
                GatewayChatConversation.user_id == user_id,
                GatewayChatConversation.surface == "standalone",
                GatewayChatConversation.status == "active",
            )
            .order_by(GatewayChatConversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [
        StandaloneConversationInfo(
            id=conversation.id,
            project_id=conversation.project_id or "",
            project_name=(project.display_name or project.name) if project else None,
            branch=conversation.branch or "main",
            title=conversation.title or "New chat",
            status=conversation.status,
            origin=conversation.origin,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            run_status=run_status,
            commit_sha=conversation.commit_sha,
            per_query_budget_usd=conversation.per_query_budget_usd,
            chat_budget_usd=conversation.chat_budget_usd,
            estimated_spend_usd=conversation.estimated_spend_usd,
            actual_spend_usd=conversation.actual_spend_usd,
            reserved_spend_usd=conversation.reserved_spend_usd,
        )
        for conversation, project, run_status in rows
    ]


async def get_conversation_detail(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
) -> StandaloneConversationDetail | None:
    # One round trip for the conversation and its project together. The
    # database is remote, so every merged query saves a full RTT.
    conversation_row = (
        await db.execute(
            select(GatewayChatConversation, GatewayWorkspaceProject)
            .join(
                GatewayWorkspaceProject,
                and_(
                    GatewayWorkspaceProject.id == GatewayChatConversation.project_id,
                    GatewayWorkspaceProject.org_id == GatewayChatConversation.org_id,
                ),
                isouter=True,
            )
            .where(
                GatewayChatConversation.id == conversation_id,
                GatewayChatConversation.org_id == org_id,
                GatewayChatConversation.user_id == user_id,
                GatewayChatConversation.surface == "standalone",
                GatewayChatConversation.status == "active",
            )
        )
    ).first()
    if conversation_row is None:
        return None
    conversation, project = conversation_row
    messages = (
        (
            await db.execute(
                select(GatewayChatMessage)
                .where(
                    GatewayChatMessage.conversation_id == conversation_id,
                    GatewayChatMessage.org_id == org_id,
                    GatewayChatMessage.user_id == user_id,
                )
                .order_by(GatewayChatMessage.sequence)
            )
        )
        .scalars()
        .all()
    )
    artifacts = (
        (
            await db.execute(
                select(GatewayChatArtifact)
                .where(
                    GatewayChatArtifact.conversation_id == conversation_id,
                    GatewayChatArtifact.org_id == org_id,
                    GatewayChatArtifact.user_id == user_id,
                )
                .order_by(GatewayChatArtifact.created_at)
            )
        )
        .scalars()
        .all()
    )
    artifact_ids = [artifact.id for artifact in artifacts]
    saved_by_artifact: dict[str, tuple[str, str, str]] = {}
    if artifact_ids:
        saved_rows = (
            await db.execute(
                select(GatewaySavedReportVersion, GatewaySavedReport)
                .join(GatewaySavedReport, GatewaySavedReport.id == GatewaySavedReportVersion.report_id)
                .where(
                    GatewaySavedReportVersion.source_artifact_id.in_(artifact_ids),
                    GatewaySavedReport.org_id == org_id,
                    GatewaySavedReport.owner_user_id == user_id,
                )
            )
        ).all()
        saved_by_artifact = {
            version.source_artifact_id: (report.id, version.id, report.title) for version, report in saved_rows
        }
    refresh_by_artifact: dict[str, tuple[str, str, str]] = {}
    run_ids = {artifact.run_id for artifact in artifacts}
    if run_ids:
        refreshes = (
            await db.execute(
                select(GatewayReportRefresh, GatewaySavedReport)
                .join(GatewaySavedReport, GatewaySavedReport.id == GatewayReportRefresh.report_id)
                .where(
                    GatewayReportRefresh.run_id.in_(run_ids),
                    GatewayReportRefresh.org_id == org_id,
                    GatewayReportRefresh.owner_user_id == user_id,
                    GatewayReportRefresh.status == "update_available",
                )
            )
        ).all()
        for refresh, report in refreshes:
            for artifact_id in refresh.candidate_artifact_ids_json or []:
                refresh_by_artifact[str(artifact_id)] = (
                    refresh.report_id,
                    refresh.base_version_id,
                    report.title,
                )
    title_by_artifact: dict[str, tuple[str, str, str]] = {}
    default_titles = {artifact.filename.rsplit(".", 1)[0].lower() for artifact in artifacts}
    if default_titles:
        title_rows = (
            await db.execute(
                select(GatewaySavedReport)
                .where(
                    GatewaySavedReport.org_id == org_id,
                    GatewaySavedReport.owner_user_id == user_id,
                    func.lower(GatewaySavedReport.title).in_(default_titles),
                )
                .order_by(GatewaySavedReport.updated_at, GatewaySavedReport.id)
            )
        ).scalars()
        reports_by_title = {report.title.lower(): report for report in title_rows if report.current_version_id}
        for artifact in artifacts:
            report = reports_by_title.get(artifact.filename.rsplit(".", 1)[0].lower())
            if report and report.kind == artifact.kind:
                title_by_artifact[artifact.id] = (report.id, report.current_version_id or "", report.title)
    artifact_infos: list[ChatArtifactInfo] = []
    for artifact in artifacts:
        refresh_target = refresh_by_artifact.get(artifact.id)
        saved_target = saved_by_artifact.get(artifact.id)
        title_target = title_by_artifact.get(artifact.id)
        target = refresh_target or saved_target or title_target or (None, None, None)
        artifact_infos.append(
            _artifact_info(
                artifact,
                saved_report_id=target[0],
                saved_report_version_id=target[1],
                saved_report_title=target[2],
                report_action=(
                    "update" if refresh_target else "open" if saved_target else "update" if title_target else "create"
                ),
            )
        )
    current_run = (
        await db.execute(
            select(GatewayChatRun)
            .where(GatewayChatRun.conversation_id == conversation_id)
            .order_by(GatewayChatRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    events = list(
        (
            await db.execute(
                select(GatewayChatRunEvent)
                .where(GatewayChatRunEvent.conversation_id == conversation_id)
                .order_by(GatewayChatRunEvent.created_at, GatewayChatRunEvent.sequence)
            )
        ).scalars()
    )
    return StandaloneConversationDetail(
        conversation=StandaloneConversationInfo(
            id=conversation.id,
            project_id=conversation.project_id or "",
            project_name=(project.display_name or project.name) if project else None,
            branch=conversation.branch or "main",
            title=conversation.title or "New chat",
            status=conversation.status,
            origin=conversation.origin,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            run_status=current_run.status if current_run else None,
            commit_sha=conversation.commit_sha,
            per_query_budget_usd=conversation.per_query_budget_usd,
            chat_budget_usd=conversation.chat_budget_usd,
            estimated_spend_usd=conversation.estimated_spend_usd,
            actual_spend_usd=conversation.actual_spend_usd,
            reserved_spend_usd=conversation.reserved_spend_usd,
        ),
        messages=[_message_info(row) for row in messages],
        artifacts=artifact_infos,
        current_run=_run_info(current_run) if current_run else None,
        run_events=[_event_info(row) for row in events],
    )


async def rename_conversation(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    title: str,
) -> bool:
    conversation = await _owned_conversation_row(
        db,
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        return False
    conversation.title = title
    conversation.updated_at = time.time()
    await db.commit()
    return True


async def archive_conversation(
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
        active_only=False,
        lock=True,
    )
    if conversation is None:
        return False
    if conversation.status != "archived":
        conversation.status = "archived"
        conversation.archived_at = _now()
        conversation.updated_at = time.time()
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
    existing_deletion = await db.scalar(
        select(GatewayChatObjectDeletion.id).where(
            GatewayChatObjectDeletion.conversation_id == conversation_id,
            GatewayChatObjectDeletion.org_id == org_id,
        )
    )
    if existing_deletion is None:
        db.add(
            GatewayChatObjectDeletion(
                id=str(uuid.uuid4()),
                org_id=org_id,
                conversation_id=conversation_id,
                object_prefix=conversation_prefix(org_id, conversation_id),
                status="pending",
            )
        )
    await db.commit()
    return True


async def update_internal_summary(
    db: AsyncSession,
    *,
    conversation_id: str,
    summary: str,
) -> None:
    conversation = (
        await db.execute(select(GatewayChatConversation).where(GatewayChatConversation.id == conversation_id))
    ).scalar_one_or_none()
    if conversation is None:
        return
    conversation.internal_summary = summary[:100_000]
    await db.commit()
