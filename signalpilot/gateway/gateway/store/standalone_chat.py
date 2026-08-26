"""Persistence authority for standalone data chat and authenticated sharing."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.connectors.schema_cache import _schema_fingerprint, schema_cache
from gateway.db.models import (
    GatewayChatArtifact,
    GatewayChatConversation,
    GatewayChatMessage,
    GatewayChatObjectDeletion,
    GatewayChatRun,
    GatewayChatRunEvent,
    GatewayChatShareGrant,
    GatewayChatUserPreference,
    GatewayGovernedQueryExecution,
    GatewayQueryApproval,
    GatewayQueryProposal,
    GatewayReportRefresh,
    GatewayRuntimeDataset,
    GatewaySavedReport,
    GatewaySavedReportVersion,
    GatewayStructuredQueryResult,
    GatewayWorkspaceProject,
)
from gateway.models.standalone_chat import (
    ChatArtifactInfo,
    ChatRunEventInfo,
    ChatRunInfo,
    SharedChatArtifactInfo,
    SharedConversationDetail,
    SharedConversationInfo,
    SharedMessageInfo,
    StandaloneConversationDetail,
    StandaloneConversationInfo,
    StandaloneMessageInfo,
)
from gateway.standalone_chat.artifacts import (
    normalize_table_snapshot,
    safe_filename,
    sanitize_chart_snapshot,
    sanitize_report_html,
    table_to_csv,
    validate_artifact_size,
)
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.standalone_chat.domain import (
    NONTERMINAL_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    RunStatus,
    assert_run_transition,
    fallback_conversation_title,
    redact_public_payload,
)
from gateway.standalone_chat.object_storage import chat_object_storage, conversation_prefix, runtime_object_key


def _now() -> datetime:
    return datetime.now(UTC)


async def _retain_runtime_datasets_after_terminal_run(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
) -> None:
    if run.terminal_at is None:
        return
    await db.execute(
        update(GatewayRuntimeDataset)
        .where(GatewayRuntimeDataset.run_id == run.id)
        .values(expires_at=run.terminal_at + timedelta(hours=24))
    )


async def _owned_conversation_row(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    active_only: bool = True,
    lock: bool = False,
) -> GatewayChatConversation | None:
    query = select(GatewayChatConversation).where(
        GatewayChatConversation.id == conversation_id,
        GatewayChatConversation.org_id == org_id,
        GatewayChatConversation.user_id == user_id,
        GatewayChatConversation.surface == "standalone",
    )
    if active_only:
        query = query.where(GatewayChatConversation.status == "active")
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def _owned_run_row(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    run_id: str,
    lock: bool = False,
) -> GatewayChatRun | None:
    query = (
        select(GatewayChatRun)
        .join(
            GatewayChatConversation,
            GatewayChatConversation.id == GatewayChatRun.conversation_id,
        )
        .where(
            GatewayChatRun.id == run_id,
            GatewayChatRun.org_id == org_id,
            GatewayChatRun.user_id == user_id,
            GatewayChatConversation.surface == "standalone",
            GatewayChatConversation.status == "active",
        )
    )
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


def _run_info(row: GatewayChatRun) -> ChatRunInfo:
    return ChatRunInfo(
        id=row.id,
        conversation_id=row.conversation_id,
        status=row.status,
        retry_of_run_id=row.retry_of_run_id,
        public_error_code=row.public_error_code,
        public_error_message=row.public_error_message,
        cancellation_requested_at=row.cancellation_requested_at,
        created_at=row.created_at,
        started_at=row.started_at,
        terminal_at=row.terminal_at,
        last_event_sequence=row.last_event_sequence,
        runtime_archive_available=bool(row.runtime_archive_id),
    )


def _message_info(row: GatewayChatMessage) -> StandaloneMessageInfo:
    metadata = dict(row.metadata_json or {})
    metadata.pop("internal", None)
    return StandaloneMessageInfo(
        id=row.id,
        role=row.role,
        content=row.content,
        sequence=row.sequence,
        created_at=row.created_at,
        metadata=metadata,
    )


def _event_info(row: GatewayChatRunEvent) -> ChatRunEventInfo:
    return ChatRunEventInfo(
        run_id=row.run_id,
        sequence=row.sequence,
        type=row.event_type,
        payload=row.payload_json,
        created_at=row.created_at,
    )


def _artifact_info(
    row: GatewayChatArtifact,
    *,
    saved_report_id: str | None = None,
    saved_report_version_id: str | None = None,
    saved_report_title: str | None = None,
    report_action: Literal["create", "update", "open"] = "create",
) -> ChatArtifactInfo:
    formats = {
        "table": ["csv"],
        "chart": ["png", "csv"],
        "report": ["html"],
    }[row.kind]
    return ChatArtifactInfo(
        id=row.id,
        run_id=row.run_id,
        assistant_message_id=row.assistant_message_id,
        kind=row.kind,
        filename=row.filename,
        mime_type=row.mime_type,
        snapshot=row.snapshot_json,
        provenance=row.provenance_json,
        freshness_at=row.freshness_at,
        assumptions=[str(value) for value in row.assumptions or []],
        exclusions=[str(value) for value in row.exclusions or []],
        caveats=[str(value) for value in row.caveats or []],
        parent_artifact_id=row.parent_artifact_id,
        saved_report_id=saved_report_id,
        saved_report_version_id=saved_report_version_id,
        saved_report_title=saved_report_title,
        report_action=report_action,
        created_at=row.created_at,
        download_formats=formats,
    )


def _shared_artifact_info(row: GatewayChatArtifact) -> SharedChatArtifactInfo:
    formats = {
        "table": ["csv"],
        "chart": ["png", "csv"],
        "report": ["html"],
    }[row.kind]
    return SharedChatArtifactInfo(
        id=row.id,
        assistant_message_id=row.assistant_message_id,
        kind=row.kind,
        filename=row.filename,
        mime_type=row.mime_type,
        snapshot=row.snapshot_json,
        freshness_at=row.freshness_at,
        assumptions=[str(value) for value in row.assumptions or []],
        exclusions=[str(value) for value in row.exclusions or []],
        caveats=[str(value) for value in row.caveats or []],
        created_at=row.created_at,
        download_formats=formats,
    )


def _bounded_artifact_notes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:500] for item in value[:100]]


async def _append_status_message(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
    status: str,
    content: str,
) -> GatewayChatMessage:
    idempotency_key = f"chat-run:{run.id}:{status}"
    existing = (
        await db.execute(select(GatewayChatMessage).where(GatewayChatMessage.idempotency_key == idempotency_key))
    ).scalar_one_or_none()
    if existing:
        return existing
    conversation = (
        await db.execute(
            select(GatewayChatConversation).where(GatewayChatConversation.id == run.conversation_id).with_for_update()
        )
    ).scalar_one()
    sequence = conversation.message_count + 1
    message = GatewayChatMessage(
        id=str(uuid.uuid4()),
        org_id=run.org_id,
        user_id=run.user_id,
        project_id=run.project_id,
        conversation_id=run.conversation_id,
        role="assistant",
        content=content.strip(),
        metadata_json={
            "surface": "standalone",
            "run_id": run.id,
            "status": status,
        },
        idempotency_key=idempotency_key,
        sequence=sequence,
        created_at=time.time(),
    )
    db.add(message)
    conversation.message_count = sequence
    conversation.updated_at = time.time()
    return message


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


async def list_conversations(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
) -> list[StandaloneConversationInfo]:
    rows = (
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
                GatewayChatConversation.org_id == org_id,
                GatewayChatConversation.user_id == user_id,
                GatewayChatConversation.surface == "standalone",
                GatewayChatConversation.status == "active",
            )
            .order_by(GatewayChatConversation.updated_at.desc())
        )
    ).all()
    result: list[StandaloneConversationInfo] = []
    for conversation, project in rows:
        latest_run = (
            await db.execute(
                select(GatewayChatRun)
                .where(GatewayChatRun.conversation_id == conversation.id)
                .order_by(GatewayChatRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        result.append(
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
                run_status=latest_run.status if latest_run else None,
                commit_sha=conversation.commit_sha,
                per_query_budget_usd=conversation.per_query_budget_usd,
                chat_budget_usd=conversation.chat_budget_usd,
                estimated_spend_usd=conversation.estimated_spend_usd,
                actual_spend_usd=conversation.actual_spend_usd,
                reserved_spend_usd=conversation.reserved_spend_usd,
            )
        )
    return result


async def get_conversation_detail(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
) -> StandaloneConversationDetail | None:
    conversation = await _owned_conversation_row(
        db,
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        return None
    project = (
        await db.execute(
            select(GatewayWorkspaceProject).where(
                GatewayWorkspaceProject.id == conversation.project_id,
                GatewayWorkspaceProject.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
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
    storage = chat_object_storage()
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


async def create_run(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    message_metadata: dict[str, Any] | None = None,
) -> GatewayChatRun:
    conversation = await _owned_conversation_row(
        db,
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation_id,
        lock=True,
    )
    if conversation is None:
        raise LookupError("Conversation not found")
    existing = (
        await db.execute(
            select(GatewayChatRun.id).where(
                GatewayChatRun.conversation_id == conversation_id,
                GatewayChatRun.status.in_(NONTERMINAL_RUN_STATUSES),
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise RuntimeError("A run is already active for this conversation")

    sequence = conversation.message_count + 1
    now = time.time()
    user_message = GatewayChatMessage(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        role="user",
        content=message.strip(),
        metadata_json={"surface": "standalone", **(message_metadata or {})},
        sequence=sequence,
        created_at=now,
    )
    run = GatewayChatRun(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation.id,
        project_id=conversation.project_id or "",
        user_message_id=user_message.id,
        status=RunStatus.queued.value,
    )
    db.add_all([user_message, run])
    conversation.message_count = sequence
    conversation.updated_at = now
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise RuntimeError("A run is already active for this conversation") from exc
    await db.refresh(run)
    return run


async def request_cancellation(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    run_id: str,
) -> GatewayChatRun | None:
    run = await _owned_run_row(db, org_id=org_id, user_id=user_id, run_id=run_id, lock=True)
    if run is None:
        return None
    if run.status in {
        RunStatus.completed.value,
        RunStatus.failed.value,
        RunStatus.cancelled.value,
    }:
        return run
    run.cancellation_requested_at = run.cancellation_requested_at or _now()
    if run.status in {
        RunStatus.queued.value,
        RunStatus.waiting_for_user.value,
        RunStatus.waiting_for_query_approval.value,
    }:
        assert_run_transition(run.status, RunStatus.cancelled.value)
        run.status = RunStatus.cancelled.value
        run.terminal_at = _now()
        run.lease_owner = None
        run.lease_expires_at = None
        await _append_status_message(
            db,
            run=run,
            status=RunStatus.cancelled.value,
            content="This run was stopped.",
        )
        _stage_run_event(
            db,
            run=run,
            event_type="status",
            payload={"status": RunStatus.cancelled.value},
        )
        await _retain_runtime_datasets_after_terminal_run(db, run=run)
        from gateway.store.chat_reports import finalize_refresh_for_run

        await finalize_refresh_for_run(db, run=run, succeeded=False)
    await db.commit()
    return run


async def submit_clarification(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    run_id: str,
    message: str,
) -> GatewayChatRun | None:
    run = await _owned_run_row(db, org_id=org_id, user_id=user_id, run_id=run_id, lock=True)
    if run is None:
        return None
    if run.status != RunStatus.waiting_for_user.value:
        raise RuntimeError("This run is not waiting for clarification")
    conversation = await _owned_conversation_row(
        db,
        org_id=org_id,
        user_id=user_id,
        conversation_id=run.conversation_id,
        lock=True,
    )
    if conversation is None:
        return None
    sequence = conversation.message_count + 1
    now = time.time()
    db.add(
        GatewayChatMessage(
            id=str(uuid.uuid4()),
            org_id=org_id,
            user_id=user_id,
            project_id=conversation.project_id,
            conversation_id=conversation.id,
            role="user",
            content=message.strip(),
            metadata_json={"surface": "standalone", "clarification_for_run_id": run.id},
            sequence=sequence,
            created_at=now,
        )
    )
    conversation.message_count = sequence
    conversation.updated_at = now
    assert_run_transition(run.status, RunStatus.queued.value)
    run.status = RunStatus.queued.value
    run.lease_owner = None
    run.lease_expires_at = None
    run.public_error_code = None
    run.public_error_message = None
    await db.commit()
    return run


async def retry_run(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    run_id: str,
) -> GatewayChatRun | None:
    failed = await _owned_run_row(db, org_id=org_id, user_id=user_id, run_id=run_id, lock=True)
    if failed is None:
        return None
    if failed.status != RunStatus.failed.value:
        raise RuntimeError("Only failed runs can be retried")
    conversation = await _owned_conversation_row(
        db,
        org_id=org_id,
        user_id=user_id,
        conversation_id=failed.conversation_id,
        lock=True,
    )
    if conversation is None:
        return None
    existing = (
        await db.execute(
            select(GatewayChatRun.id).where(
                GatewayChatRun.conversation_id == failed.conversation_id,
                GatewayChatRun.status.in_(NONTERMINAL_RUN_STATUSES),
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise RuntimeError("A run is already active for this conversation")
    retry = GatewayChatRun(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        conversation_id=failed.conversation_id,
        project_id=failed.project_id,
        user_message_id=failed.user_message_id,
        status=RunStatus.queued.value,
        retry_of_run_id=failed.id,
    )
    db.add(retry)
    from gateway.store.chat_reports import rebind_refresh_retry

    await rebind_refresh_retry(db, failed_run_id=failed.id, retry_run_id=retry.id)
    conversation.updated_at = time.time()
    await db.commit()
    await db.refresh(retry)
    return retry


async def append_event(
    db: AsyncSession,
    *,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> GatewayChatRunEvent:
    run = (
        await db.execute(
            select(GatewayChatRun)
            .where(GatewayChatRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    event = _stage_run_event(
        db,
        run=run,
        event_type=event_type,
        payload=payload,
    )
    await db.execute(
        update(GatewayChatConversation)
        .where(GatewayChatConversation.id == run.conversation_id)
        .values(updated_at=time.time())
    )
    await db.commit()
    await db.refresh(event)
    return event


def _stage_run_event(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
    event_type: str,
    payload: dict[str, Any],
) -> GatewayChatRunEvent:
    """Add an event to the run's current transaction without committing it."""
    sequence = run.last_event_sequence + 1
    event = GatewayChatRunEvent(
        id=str(uuid.uuid4()),
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        sequence=sequence,
        event_type=event_type,
        payload_json=redact_public_payload(payload),
    )
    db.add(event)
    run.last_event_sequence = sequence
    return event


async def list_run_events(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    run_id: str,
    after: int = 0,
) -> list[ChatRunEventInfo] | None:
    run = await _owned_run_row(db, org_id=org_id, user_id=user_id, run_id=run_id)
    if run is None:
        return None
    events = (
        (
            await db.execute(
                select(GatewayChatRunEvent)
                .where(
                    GatewayChatRunEvent.run_id == run_id,
                    GatewayChatRunEvent.sequence > after,
                )
                .order_by(GatewayChatRunEvent.sequence)
            )
        )
        .scalars()
        .all()
    )
    return [_event_info(row) for row in events]


async def claim_runs(
    db: AsyncSession,
    *,
    worker_id: str,
    limit: int,
    lease_seconds: int,
) -> list[str]:
    now = _now()
    candidates = (
        (
            await db.execute(
                select(GatewayChatRun)
                .where(
                    or_(
                        GatewayChatRun.status == RunStatus.queued.value,
                        and_(
                            GatewayChatRun.status == RunStatus.running.value,
                            GatewayChatRun.lease_expires_at < now,
                        ),
                    )
                )
                .order_by(GatewayChatRun.created_at)
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    claimed: list[str] = []
    for run in candidates:
        if run.cancellation_requested_at:
            assert_run_transition(run.status, RunStatus.cancelled.value)
            run.status = RunStatus.cancelled.value
            run.terminal_at = now
            run.lease_owner = None
            run.lease_expires_at = None
            await _append_status_message(
                db,
                run=run,
                status=RunStatus.cancelled.value,
                content="This run was stopped.",
            )
            _stage_run_event(
                db,
                run=run,
                event_type="status",
                payload={"status": RunStatus.cancelled.value},
            )
            await _retain_runtime_datasets_after_terminal_run(db, run=run)
            continue
        if run.status == RunStatus.queued.value:
            assert_run_transition(run.status, RunStatus.running.value)
        run.status = RunStatus.running.value
        run.started_at = run.started_at or now
        run.execution_attempt += 1
        run.lease_owner = worker_id
        run.lease_expires_at = now + timedelta(seconds=lease_seconds)
        claimed.append(run.id)
    await db.commit()
    return claimed


async def renew_lease(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    lease_seconds: int,
) -> bool:
    run = (
        await db.execute(
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.status == RunStatus.running.value,
                GatewayChatRun.lease_owner == worker_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        return False
    run.lease_expires_at = _now() + timedelta(seconds=lease_seconds)
    await db.commit()
    return True


async def get_worker_run(db: AsyncSession, *, run_id: str, worker_id: str) -> GatewayChatRun | None:
    return (
        await db.execute(
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.status == RunStatus.running.value,
                GatewayChatRun.lease_owner == worker_id,
            )
        )
    ).scalar_one_or_none()


async def worker_context(db: AsyncSession, *, run: GatewayChatRun) -> dict[str, Any]:
    conversation = (
        await db.execute(
            select(GatewayChatConversation).where(
                GatewayChatConversation.id == run.conversation_id,
                GatewayChatConversation.org_id == run.org_id,
                GatewayChatConversation.user_id == run.user_id,
                GatewayChatConversation.surface == "standalone",
            )
        )
    ).scalar_one()
    project = (
        await db.execute(
            select(GatewayWorkspaceProject).where(
                GatewayWorkspaceProject.id == run.project_id,
                GatewayWorkspaceProject.org_id == run.org_id,
            )
        )
    ).scalar_one()
    messages = (
        (
            await db.execute(
                select(GatewayChatMessage)
                .where(GatewayChatMessage.conversation_id == run.conversation_id)
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
                .where(GatewayChatArtifact.conversation_id == run.conversation_id)
                .order_by(GatewayChatArtifact.created_at)
            )
        )
        .scalars()
        .all()
    )
    proposals = list(
        (
            await db.execute(
                select(GatewayQueryProposal)
                .where(GatewayQueryProposal.conversation_id == run.conversation_id)
                .order_by(GatewayQueryProposal.created_at)
            )
        ).scalars()
    )
    proposal_ids = [proposal.id for proposal in proposals]
    approvals = (
        list(
            (
                await db.execute(
                    select(GatewayQueryApproval)
                    .where(GatewayQueryApproval.proposal_id.in_(proposal_ids))
                    .order_by(GatewayQueryApproval.created_at)
                )
            ).scalars()
        )
        if proposal_ids
        else []
    )
    executions = list(
        (
            await db.execute(
                select(GatewayGovernedQueryExecution)
                .where(GatewayGovernedQueryExecution.conversation_id == run.conversation_id)
                .order_by(GatewayGovernedQueryExecution.created_at)
            )
        ).scalars()
    )
    results = list(
        (
            await db.execute(
                select(GatewayStructuredQueryResult)
                .where(
                    GatewayStructuredQueryResult.org_id == run.org_id,
                    GatewayStructuredQueryResult.owner_user_id == run.user_id,
                    GatewayStructuredQueryResult.conversation_id == run.conversation_id,
                )
                .order_by(GatewayStructuredQueryResult.created_at)
            )
        ).scalars()
    )
    return {
        "conversation": conversation,
        "project": project,
        "messages": messages,
        "artifacts": artifacts,
        "query_proposals": proposals,
        "query_approvals": approvals,
        "query_executions": executions,
        "query_results": results,
    }


async def set_execution_session(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    execution_session_id: str,
) -> bool:
    run = (
        await db.execute(
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.lease_owner == worker_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        return False
    run.execution_session_id = execution_session_id
    await db.commit()
    return True


async def persist_artifact(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
    payload: dict[str, Any],
) -> GatewayChatArtifact:
    kind = str(payload.get("kind") or "")
    if kind not in {"table", "chart", "report"}:
        raise ValueError("Unsupported artifact kind")
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("Artifact snapshot must be an object")
    full_snapshot = snapshot
    binary_data: bytes | None = None
    encoded = payload.get("binary_base64")
    if encoded:
        if len(str(encoded)) > (14 * 1024 * 1024):
            raise ValueError("Artifact exceeds the 10 MiB limit")
        try:
            binary_data = base64.b64decode(str(encoded), validate=True)
        except Exception as exc:
            raise ValueError("Artifact binary is not valid base64") from exc
    if kind == "report":
        html_value = str(snapshot.get("html") or "")
        snapshot = {**snapshot, "html": sanitize_report_html(html_value)}
    elif kind == "chart":
        if binary_data is None:
            raise ValueError("Chart artifacts require a PNG representation")
        snapshot = sanitize_chart_snapshot(snapshot)
    else:
        snapshot = normalize_table_snapshot(snapshot)
    provenance = redact_public_payload(payload.get("provenance") or {})
    # Lineage used by saved-report preflight is server-owned. The agent may
    # supply other public provenance, but it cannot choose the frozen dbt
    # commit or the schema fingerprint observed during this conversation.
    conversation = await db.get(GatewayChatConversation, run.conversation_id)
    if conversation is not None:
        provenance["commit_sha"] = conversation.commit_sha
    project = await db.get(GatewayWorkspaceProject, run.project_id)
    if project is not None and project.connection_name:
        try:
            observed_schema = schema_cache.get(project.connection_name)
        except Exception:
            observed_schema = None
        provenance["schema_fingerprint"] = _schema_fingerprint(observed_schema) if observed_schema is not None else None
    assumptions = _bounded_artifact_notes(payload.get("assumptions"))
    exclusions = _bounded_artifact_notes(payload.get("exclusions"))
    caveats = _bounded_artifact_notes(payload.get("caveats"))
    validate_artifact_size(
        {
            "snapshot": snapshot,
            "provenance": provenance,
            "assumptions": assumptions,
            "exclusions": exclusions,
            "caveats": caveats,
        },
        binary_data,
    )
    default_ext = {"table": ".csv", "chart": ".png", "report": ".html"}[kind]
    filename = safe_filename(str(payload.get("filename") or ""), fallback=f"analysis{default_ext}")
    if not filename.lower().endswith(default_ext):
        filename = f"{filename.rsplit('.', 1)[0]}{default_ext}"
    expected_mime_type = {
        "table": "text/csv",
        "chart": "image/png",
        "report": "text/html",
    }[kind]
    supplied_mime_type = str(payload.get("mime_type") or expected_mime_type).split(";", 1)[0].strip().lower()
    if supplied_mime_type != expected_mime_type:
        raise ValueError("Artifact MIME type does not match its kind")
    mime_type = expected_mime_type
    object_bytes = (
        table_to_csv(full_snapshot)
        if kind == "table"
        else binary_data
        if kind == "chart"
        else str(snapshot.get("html") or "").encode("utf-8")
    )
    assert object_bytes is not None
    if len(object_bytes) > 10 * 1024 * 1024:
        raise ValueError("Artifact exceeds the 10 MiB limit")
    chart_source_bytes: bytes | None = None
    if kind == "chart":
        source = full_snapshot.get("source") if isinstance(full_snapshot.get("source"), dict) else full_snapshot
        chart_source_bytes = table_to_csv(source)
        if len(chart_source_bytes) > 10 * 1024 * 1024:
            raise ValueError("Artifact source exceeds the 10 MiB limit")
    candidate_hash = hashlib.sha256(object_bytes).hexdigest()
    existing = (
        await db.execute(
            select(GatewayChatArtifact).where(
                GatewayChatArtifact.run_id == run.id,
                GatewayChatArtifact.kind == kind,
                GatewayChatArtifact.filename == filename,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # The publication key is idempotent and immutable. A retry cannot
        # replace the first snapshot, even if a caller reconstructs different
        # bytes for the same run/kind/filename tuple.
        return existing
    artifact_id = str(uuid.uuid4())
    storage_kind = "inline"
    object_key = None
    source_object_key = None
    byte_size = len(object_bytes)
    # Content identity is always the SHA-256 of the exact primary downloadable
    # bytes, independently of whether those bytes are inline or object-backed.
    content_hash = candidate_hash
    uploaded_keys: list[str] = []
    if enterprise_chat_feature_flags().runtime_artifacts:
        storage = chat_object_storage()
        object_key = runtime_object_key(
            org_id=run.org_id,
            conversation_id=run.conversation_id,
            run_id=run.id,
            category="artifacts",
            object_id=artifact_id,
            filename=filename,
        )
        try:
            stored = await storage.put_bytes(key=object_key, data=object_bytes, content_type=mime_type)
            uploaded_keys.append(object_key)
            storage_kind = "object"
            byte_size = stored.byte_size
            content_hash = stored.content_hash
            if kind == "chart":
                assert chart_source_bytes is not None
                source_object_key = runtime_object_key(
                    org_id=run.org_id,
                    conversation_id=run.conversation_id,
                    run_id=run.id,
                    category="artifact-sources",
                    object_id=artifact_id,
                    filename=f"{filename.rsplit('.', 1)[0]}.csv",
                )
                await storage.put_bytes(
                    key=source_object_key,
                    data=chart_source_bytes,
                    content_type="text/csv",
                )
                uploaded_keys.append(source_object_key)
        except Exception:
            for uploaded_key in reversed(uploaded_keys):
                with suppress(Exception):
                    await storage.delete(uploaded_key)
            raise
        binary_data = None
    elif kind == "table":
        # Keep the exact governed CSV bytes alongside the bounded UI snapshot.
        # This makes inline and object-backed content identity identical.
        binary_data = object_bytes
    artifact = GatewayChatArtifact(
        id=artifact_id,
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        kind=kind,
        filename=filename,
        mime_type=mime_type,
        snapshot_json=snapshot,
        binary_data=binary_data,
        storage_kind=storage_kind,
        object_key=object_key,
        source_object_key=source_object_key,
        byte_size=byte_size,
        content_hash=content_hash,
        provenance_json=provenance,
        freshness_at=_parse_datetime(payload.get("freshness_at")),
        assumptions=assumptions,
        exclusions=exclusions,
        caveats=caveats,
        parent_artifact_id=str(payload.get("parent_artifact_id") or "") or None,
    )
    if artifact.parent_artifact_id:
        parent = (
            await db.execute(
                select(GatewayChatArtifact.id).where(
                    GatewayChatArtifact.id == artifact.parent_artifact_id,
                    GatewayChatArtifact.org_id == run.org_id,
                    GatewayChatArtifact.user_id == run.user_id,
                    GatewayChatArtifact.conversation_id == run.conversation_id,
                )
            )
        ).scalar_one_or_none()
        if parent is None:
            raise ValueError("Parent artifact not found")
    db.add(artifact)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        if uploaded_keys:
            storage = chat_object_storage()
            for uploaded_key in reversed(uploaded_keys):
                with suppress(Exception):
                    await storage.delete(uploaded_key)
        raise
    await db.refresh(artifact)
    return artifact


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


async def complete_run(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    content: str,
    report_proposal: dict[str, Any] | None = None,
    report_action_outcome: dict[str, Any] | None = None,
) -> GatewayChatMessage | None:
    run = (
        await db.execute(
            select(GatewayChatRun)
            .where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.lease_owner == worker_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        return None
    existing = (
        await db.execute(
            select(GatewayChatMessage).where(GatewayChatMessage.idempotency_key == f"chat-run:{run.id}:final")
        )
    ).scalar_one_or_none()
    if existing:
        if run.status == RunStatus.running.value:
            run.status = RunStatus.completed.value
            run.terminal_at = run.terminal_at or _now()
            run.lease_owner = None
            run.lease_expires_at = None
            _stage_run_event(
                db,
                run=run,
                event_type="status",
                payload={"status": RunStatus.completed.value},
            )
            await _retain_runtime_datasets_after_terminal_run(db, run=run)
            from gateway.store.chat_reports import finalize_refresh_for_run

            await finalize_refresh_for_run(db, run=run, succeeded=True)
            await db.commit()
        return existing

    if run.cancellation_requested_at:
        assert_run_transition(run.status, RunStatus.cancelled.value)
        run.status = RunStatus.cancelled.value
        run.terminal_at = _now()
        run.lease_owner = None
        run.lease_expires_at = None
        await _append_status_message(
            db,
            run=run,
            status=RunStatus.cancelled.value,
            content="This run was stopped.",
        )
        _stage_run_event(
            db,
            run=run,
            event_type="status",
            payload={"status": RunStatus.cancelled.value},
        )
        await _retain_runtime_datasets_after_terminal_run(db, run=run)
        from gateway.store.chat_reports import finalize_refresh_for_run

        await finalize_refresh_for_run(db, run=run, succeeded=False)
        await db.commit()
        return None
    conversation = (
        await db.execute(
            select(GatewayChatConversation).where(GatewayChatConversation.id == run.conversation_id).with_for_update()
        )
    ).scalar_one()
    report_suggestion = None
    if report_proposal:
        from gateway.store.chat_reports import validate_report_proposal_for_run

        try:
            validated = await validate_report_proposal_for_run(
                db,
                run=run,
                proposal=report_proposal,
            )
            report_suggestion = validated.model_dump(mode="json") if validated else None
        except (LookupError, RuntimeError, ValueError):
            report_suggestion = None
    no_suggestion_outcome = None
    if isinstance(report_action_outcome, dict) and report_action_outcome.get("action") == "no_suggestion":
        no_suggestion_outcome = {
            "action": "no_suggestion",
            "artifact_kind": report_action_outcome.get("artifact_kind"),
            "artifact_filename": report_action_outcome.get("artifact_filename"),
            "reason": str(report_action_outcome.get("reason") or "")[:2000],
            "source": report_action_outcome.get("source") or "agent",
            "catalog_scan_complete": bool(report_action_outcome.get("catalog_scan_complete")),
        }
    sequence = conversation.message_count + 1
    message = GatewayChatMessage(
        id=str(uuid.uuid4()),
        org_id=run.org_id,
        user_id=run.user_id,
        project_id=run.project_id,
        conversation_id=run.conversation_id,
        role="assistant",
        content=content.strip(),
        metadata_json={
            "surface": "standalone",
            "run_id": run.id,
            "status": "completed",
            "runtime_archive_available": bool(run.runtime_archive_id),
            **({"report_suggestion": report_suggestion} if report_suggestion else {}),
            **({"report_action_outcome": no_suggestion_outcome} if no_suggestion_outcome else {}),
        },
        idempotency_key=f"chat-run:{run.id}:final",
        sequence=sequence,
        created_at=time.time(),
    )
    db.add(message)
    conversation.message_count = sequence
    conversation.updated_at = time.time()
    if not conversation.title or conversation.title == "New chat":
        first_question = (
            await db.execute(
                select(GatewayChatMessage)
                .where(
                    GatewayChatMessage.conversation_id == run.conversation_id,
                    GatewayChatMessage.role == "user",
                )
                .order_by(GatewayChatMessage.sequence)
                .limit(1)
            )
        ).scalar_one_or_none()
        conversation.title = fallback_conversation_title(first_question.content if first_question else content)
    assert_run_transition(run.status, RunStatus.completed.value)
    run.status = RunStatus.completed.value
    run.terminal_at = _now()
    run.lease_owner = None
    run.lease_expires_at = None
    _stage_run_event(
        db,
        run=run,
        event_type="status",
        payload={"status": RunStatus.completed.value},
    )
    await _retain_runtime_datasets_after_terminal_run(db, run=run)
    await db.flush()
    artifacts = (
        (
            await db.execute(
                select(GatewayChatArtifact).where(
                    GatewayChatArtifact.run_id == run.id,
                    GatewayChatArtifact.assistant_message_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for artifact in artifacts:
        artifact.assistant_message_id = message.id
    from gateway.store.chat_reports import finalize_refresh_for_run

    await finalize_refresh_for_run(db, run=run, succeeded=True)
    await db.commit()
    return message


async def wait_for_clarification(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    question: str,
) -> GatewayChatMessage | None:
    run = (
        await db.execute(
            select(GatewayChatRun)
            .where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.lease_owner == worker_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        return None
    idempotency_key = f"chat-run:{run.id}:clarification:{run.execution_attempt}"
    existing = (
        await db.execute(select(GatewayChatMessage).where(GatewayChatMessage.idempotency_key == idempotency_key))
    ).scalar_one_or_none()
    if existing:
        return existing
    conversation = (
        await db.execute(
            select(GatewayChatConversation).where(GatewayChatConversation.id == run.conversation_id).with_for_update()
        )
    ).scalar_one()
    sequence = conversation.message_count + 1
    message = GatewayChatMessage(
        id=str(uuid.uuid4()),
        org_id=run.org_id,
        user_id=run.user_id,
        project_id=run.project_id,
        conversation_id=run.conversation_id,
        role="assistant",
        content=question.strip(),
        metadata_json={
            "surface": "standalone",
            "run_id": run.id,
            "status": "waiting_for_user",
            "clarification": True,
        },
        idempotency_key=idempotency_key,
        sequence=sequence,
        created_at=time.time(),
    )
    db.add(message)
    conversation.message_count = sequence
    conversation.updated_at = time.time()
    assert_run_transition(run.status, RunStatus.waiting_for_user.value)
    run.status = RunStatus.waiting_for_user.value
    run.lease_owner = None
    run.lease_expires_at = None
    _stage_run_event(
        db,
        run=run,
        event_type="status",
        payload={"status": RunStatus.waiting_for_user.value},
    )
    await db.commit()
    return message


async def fail_run(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    code: str,
    message: str,
) -> bool:
    run = (
        await db.execute(
            select(GatewayChatRun)
            .where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.lease_owner == worker_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        return False
    target = RunStatus.cancelled.value if run.cancellation_requested_at else RunStatus.failed.value
    assert_run_transition(run.status, target)
    run.status = target
    run.public_error_code = str(code)[:100]
    run.public_error_message = str(redact_public_payload(message))[:1000]
    run.terminal_at = _now()
    run.lease_owner = None
    run.lease_expires_at = None
    await _append_status_message(
        db,
        run=run,
        status=target,
        content=run.public_error_message or "The run could not be completed.",
    )
    _stage_run_event(
        db,
        run=run,
        event_type="status",
        payload={"status": target},
    )
    await _retain_runtime_datasets_after_terminal_run(db, run=run)
    from gateway.store.chat_reports import finalize_refresh_for_run

    await finalize_refresh_for_run(db, run=run, succeeded=False)
    artifact_object_keys = list(
        (
            await db.execute(
                select(
                    GatewayChatArtifact.object_key,
                    GatewayChatArtifact.source_object_key,
                ).where(GatewayChatArtifact.run_id == run.id)
            )
        ).all()
    )
    await db.execute(delete(GatewayChatArtifact).where(GatewayChatArtifact.run_id == run.id))
    await db.commit()
    if artifact_object_keys:
        storage = chat_object_storage()
        for object_key, source_object_key in artifact_object_keys:
            for key in (object_key, source_object_key):
                if key:
                    with suppress(Exception):
                        await storage.delete(key)
    return True


async def get_artifact(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    artifact_id: str,
) -> GatewayChatArtifact | None:
    return (
        await db.execute(
            select(GatewayChatArtifact)
            .join(
                GatewayChatConversation,
                GatewayChatConversation.id == GatewayChatArtifact.conversation_id,
            )
            .where(
                GatewayChatArtifact.id == artifact_id,
                GatewayChatArtifact.org_id == org_id,
                GatewayChatArtifact.user_id == user_id,
                GatewayChatConversation.surface == "standalone",
                GatewayChatConversation.status == "active",
            )
        )
    ).scalar_one_or_none()


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
