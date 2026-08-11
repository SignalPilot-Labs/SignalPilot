"""Persistence authority for the Data Chat artifact library and saved reports."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayChatArtifact,
    GatewayChatConversation,
    GatewayChatRun,
    GatewayReportRefresh,
    GatewayReportShareAccess,
    GatewayReportShareGrant,
    GatewaySavedReport,
    GatewaySavedReportVersion,
    GatewayWorkspaceProject,
)
from gateway.models.chat_reports import (
    ChatLibraryResponse,
    LibraryArtifact,
    LibraryArtifactHistoryItem,
    LibraryCollection,
    LibraryFacets,
    LibraryReport,
    ReportRefreshInfo,
    SavedReportDetail,
    SavedVersionInfo,
    SharedSavedReport,
    SharedVersionInfo,
)
from gateway.standalone_chat.artifacts import table_to_csv
from gateway.standalone_chat.object_storage import chat_object_storage


def _now() -> datetime:
    return datetime.now(UTC)


class ReportNotFoundError(LookupError):
    pass


class ReportValidationError(ValueError):
    pass


class ActiveShareGrantError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReportConflictError(RuntimeError):
    report_id: str
    actual_current_version_id: str

    def __str__(self) -> str:
        return "The report changed in another session"


@dataclass(frozen=True)
class ExistingContentError(RuntimeError):
    report_id: str
    version_id: str


def _download_formats(kind: str) -> list[str]:
    return {"table": ["csv"], "chart": ["png", "csv"], "report": ["html"]}.get(kind, [])


def _inline_artifact_bytes(artifact: GatewayChatArtifact) -> bytes:
    if artifact.kind == "table":
        return artifact.binary_data or table_to_csv(artifact.snapshot_json or {})
    if artifact.kind == "chart":
        if artifact.binary_data is None:
            raise ReportValidationError("Chart artifact content is unavailable")
        return artifact.binary_data
    if artifact.kind == "report":
        return str((artifact.snapshot_json or {}).get("html") or "").encode("utf-8")
    raise ReportValidationError("Unsupported artifact kind")


async def artifact_download_bytes(artifact: GatewayChatArtifact, *, source: bool = False) -> bytes:
    """Return the exact governed download bytes without requiring an active thread."""
    if artifact.storage_kind == "object":
        key = artifact.source_object_key if source and artifact.kind == "chart" else artifact.object_key
        if not key:
            raise ReportValidationError("Artifact content is unavailable")
        content = await chat_object_storage().get_bytes(key, max_bytes=10 * 1024 * 1024)
        if not source and artifact.content_hash and hashlib.sha256(content).hexdigest() != artifact.content_hash:
            raise ReportValidationError("Artifact integrity check failed")
        return content
    if source and artifact.kind == "chart":
        snapshot = artifact.snapshot_json or {}
        source_snapshot = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else snapshot
        return table_to_csv(source_snapshot)
    return _inline_artifact_bytes(artifact)


async def ensure_artifact_hash(db: AsyncSession, artifact: GatewayChatArtifact) -> str:
    if artifact.content_hash:
        return artifact.content_hash
    content = await artifact_download_bytes(artifact)
    artifact.content_hash = hashlib.sha256(content).hexdigest()
    artifact.byte_size = len(content)
    await db.flush()
    return artifact.content_hash


async def backfill_inline_artifact_hashes(db: AsyncSession, *, limit: int = 200) -> int:
    """Bounded startup backfill; object-backed misses remain safely lazy."""
    artifacts = list(
        (
            await db.execute(
                select(GatewayChatArtifact)
                .where(
                    GatewayChatArtifact.content_hash.is_(None),
                    GatewayChatArtifact.storage_kind == "inline",
                )
                .order_by(GatewayChatArtifact.created_at)
                .limit(limit)
            )
        ).scalars()
    )
    updated = 0
    for artifact in artifacts:
        try:
            content = _inline_artifact_bytes(artifact)
        except ReportValidationError:
            continue
        artifact.content_hash = hashlib.sha256(content).hexdigest()
        artifact.byte_size = len(content)
        updated += 1
    if updated:
        await db.commit()
    return updated


def _artifact_freshness(artifact: GatewayChatArtifact) -> tuple[str, datetime | None, datetime]:
    # Artifacts have provenance timestamps but have not necessarily had a drift
    # comparison. They therefore remain unknown until promoted and checked.
    return "unknown", artifact.freshness_at, artifact.created_at


def _library_artifact_history_item(
    artifact: GatewayChatArtifact,
    version: GatewaySavedReportVersion | None,
    report: GatewaySavedReport | None,
) -> LibraryArtifactHistoryItem:
    state, freshness_at, checked_at = _artifact_freshness(artifact)
    return LibraryArtifactHistoryItem(
        id=artifact.id,
        kind=artifact.kind,
        filename=artifact.filename,
        created_at=artifact.created_at,
        freshness_state=state,
        freshness_at=freshness_at,
        freshness_checked_at=checked_at,
        saved_report_id=report.id if report else None,
        saved_version_id=version.id if version else None,
        snapshot=artifact.snapshot_json or {},
        download_formats=_download_formats(artifact.kind),
    )


def _encode_cursor(value: tuple[datetime, str] | None) -> str | None:
    if value is None:
        return None
    payload = json.dumps([value[0].isoformat(), value[1]], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str | None) -> tuple[datetime, str] | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        timestamp, row_id = json.loads(base64.urlsafe_b64decode(padded).decode())
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC), str(row_id))
    except Exception as exc:
        raise ReportValidationError("Invalid pagination cursor") from exc


async def list_library(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    search: str | None = None,
    kind: str | None = None,
    project_id: str | None = None,
    original_thread_id: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    freshness: str | None = None,
    saved: str | None = None,
    artifact_cursor: str | None = None,
    report_cursor: str | None = None,
    limit: int = 30,
) -> ChatLibraryResponse:
    """Search approved metadata only; artifact snapshots never enter predicates."""
    artifact_conditions = [
        GatewayChatArtifact.org_id == org_id,
        GatewayChatArtifact.user_id == user_id,
        GatewayChatConversation.surface == "standalone",
        GatewayChatRun.status == "completed",
    ]
    normalized_search = (search or "").strip().lower()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        artifact_conditions.append(
            or_(
                func.lower(GatewayChatArtifact.filename).like(pattern),
                func.lower(func.coalesce(GatewayWorkspaceProject.display_name, "")).like(pattern),
                func.lower(func.coalesce(GatewayWorkspaceProject.name, "")).like(pattern),
                func.lower(func.coalesce(GatewayChatConversation.title, "")).like(pattern),
            )
        )
    if kind:
        artifact_conditions.append(GatewayChatArtifact.kind == kind)
    if project_id:
        artifact_conditions.append(GatewayChatArtifact.conversation_id == GatewayChatConversation.id)
        artifact_conditions.append(GatewayChatConversation.project_id == project_id)
    if original_thread_id:
        artifact_conditions.append(GatewayChatArtifact.conversation_id == original_thread_id)
    if created_from:
        artifact_conditions.append(GatewayChatArtifact.created_at >= created_from)
    if created_to:
        artifact_conditions.append(GatewayChatArtifact.created_at <= created_to)
    if freshness and freshness != "unknown":
        # A raw artifact has not undergone the reliable drift comparison needed
        # to claim either Fresh or Changes detected.
        artifact_conditions.append(False)
    if saved == "saved":
        artifact_conditions.append(GatewaySavedReportVersion.id.is_not(None))
    elif saved == "unsaved":
        artifact_conditions.append(GatewaySavedReportVersion.id.is_(None))
    ranked_artifacts = (
        select(
            GatewayChatArtifact.id.label("artifact_id"),
            GatewayChatArtifact.created_at.label("artifact_created_at"),
            func.row_number()
            .over(
                partition_by=(
                    GatewayChatArtifact.conversation_id,
                    func.lower(GatewayChatArtifact.filename),
                ),
                order_by=(
                    GatewayChatArtifact.created_at.desc(),
                    GatewayChatArtifact.id.desc(),
                ),
            )
            .label("group_position"),
        )
        .join(GatewayChatConversation, GatewayChatConversation.id == GatewayChatArtifact.conversation_id)
        .join(GatewayChatRun, GatewayChatRun.id == GatewayChatArtifact.run_id)
        .outerjoin(GatewayWorkspaceProject, GatewayWorkspaceProject.id == GatewayChatConversation.project_id)
        .outerjoin(
            GatewaySavedReportVersion,
            GatewaySavedReportVersion.source_artifact_id == GatewayChatArtifact.id,
        )
        .where(*artifact_conditions)
        .subquery()
    )
    artifact_page_conditions = [ranked_artifacts.c.group_position == 1]
    decoded_artifact_cursor = _decode_cursor(artifact_cursor)
    if decoded_artifact_cursor:
        cursor_at, cursor_id = decoded_artifact_cursor
        artifact_page_conditions.append(
            or_(
                ranked_artifacts.c.artifact_created_at < cursor_at,
                and_(
                    ranked_artifacts.c.artifact_created_at == cursor_at,
                    ranked_artifacts.c.artifact_id < cursor_id,
                ),
            )
        )

    artifact_rows = list(
        (
            await db.execute(
                select(
                    GatewayChatArtifact,
                    GatewayChatConversation,
                    GatewayWorkspaceProject,
                    GatewaySavedReportVersion,
                    GatewaySavedReport,
                )
                .join(ranked_artifacts, ranked_artifacts.c.artifact_id == GatewayChatArtifact.id)
                .join(GatewayChatConversation, GatewayChatConversation.id == GatewayChatArtifact.conversation_id)
                .join(GatewayChatRun, GatewayChatRun.id == GatewayChatArtifact.run_id)
                .outerjoin(GatewayWorkspaceProject, GatewayWorkspaceProject.id == GatewayChatConversation.project_id)
                .outerjoin(
                    GatewaySavedReportVersion,
                    GatewaySavedReportVersion.source_artifact_id == GatewayChatArtifact.id,
                )
                .outerjoin(GatewaySavedReport, GatewaySavedReport.id == GatewaySavedReportVersion.report_id)
                .where(*artifact_page_conditions)
                .order_by(
                    ranked_artifacts.c.artifact_created_at.desc(),
                    ranked_artifacts.c.artifact_id.desc(),
                )
                .limit(limit + 1)
            )
        ).all()
    )
    artifact_more = len(artifact_rows) > limit
    artifact_rows = artifact_rows[:limit]
    history_by_group: dict[tuple[str, str], list[LibraryArtifactHistoryItem]] = {}
    if artifact_rows:
        group_conditions = [
            and_(
                GatewayChatArtifact.conversation_id == artifact.conversation_id,
                func.lower(GatewayChatArtifact.filename) == artifact.filename.lower(),
            )
            for artifact, *_ in artifact_rows
        ]
        history_rows = (
            await db.execute(
                select(
                    GatewayChatArtifact,
                    GatewaySavedReportVersion,
                    GatewaySavedReport,
                )
                .join(GatewayChatRun, GatewayChatRun.id == GatewayChatArtifact.run_id)
                .outerjoin(
                    GatewaySavedReportVersion,
                    GatewaySavedReportVersion.source_artifact_id == GatewayChatArtifact.id,
                )
                .outerjoin(GatewaySavedReport, GatewaySavedReport.id == GatewaySavedReportVersion.report_id)
                .where(
                    GatewayChatArtifact.org_id == org_id,
                    GatewayChatArtifact.user_id == user_id,
                    GatewayChatRun.status == "completed",
                    or_(*group_conditions),
                )
                .order_by(
                    GatewayChatArtifact.created_at.desc(),
                    GatewayChatArtifact.id.desc(),
                )
            )
        ).all()
        for history_artifact, history_version, history_report in history_rows:
            key = (history_artifact.conversation_id, history_artifact.filename.lower())
            history_by_group.setdefault(key, []).append(
                _library_artifact_history_item(history_artifact, history_version, history_report)
            )
    artifact_items: list[LibraryArtifact] = []
    for artifact, conversation, project, version, report in artifact_rows:
        history_item = _library_artifact_history_item(artifact, version, report)
        artifact_items.append(
            LibraryArtifact(
                **history_item.model_dump(),
                project_id=conversation.project_id,
                project_name=(project.display_name or project.name) if project else None,
                original_thread_id=conversation.id,
                original_thread_title=conversation.title or "New chat",
                history=history_by_group.get((artifact.conversation_id, artifact.filename.lower()), [history_item]),
            )
        )

    report_items = await _list_library_reports(
        db,
        org_id=org_id,
        user_id=user_id,
        search=normalized_search,
        kind=kind,
        project_id=project_id,
        original_thread_id=original_thread_id,
        created_from=created_from,
        created_to=created_to,
        freshness=freshness,
        saved=saved,
        cursor=_decode_cursor(report_cursor),
        limit=limit,
    )
    facets = await _library_facets(db, org_id=org_id, user_id=user_id)
    next_artifact = None
    if artifact_more and artifact_rows:
        last_artifact = artifact_rows[-1][0]
        next_artifact = _encode_cursor((last_artifact.created_at, last_artifact.id))
    return ChatLibraryResponse(
        artifacts=LibraryCollection(items=artifact_items, next_cursor=next_artifact),
        reports=LibraryCollection(items=report_items[0], next_cursor=report_items[1]),
        facets=facets,
    )


async def _list_library_reports(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    search: str,
    kind: str | None,
    project_id: str | None,
    original_thread_id: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
    freshness: str | None,
    saved: str | None,
    cursor: tuple[datetime, str] | None,
    limit: int,
) -> tuple[list[LibraryReport], str | None]:
    if saved == "unsaved":
        return [], None
    owned_conditions = [GatewaySavedReport.org_id == org_id, GatewaySavedReport.owner_user_id == user_id]
    pattern = f"%{search}%"
    if search:
        owned_conditions.append(
            or_(
                func.lower(GatewaySavedReport.title).like(pattern),
                func.lower(GatewaySavedReportVersion.filename).like(pattern),
                func.lower(func.coalesce(GatewayWorkspaceProject.display_name, "")).like(pattern),
                func.lower(func.coalesce(GatewayWorkspaceProject.name, "")).like(pattern),
                func.lower(func.coalesce(GatewayChatConversation.title, "")).like(pattern),
            )
        )
    if kind:
        owned_conditions.append(GatewaySavedReport.kind == kind)
    if project_id:
        owned_conditions.append(GatewaySavedReport.project_id == project_id)
    if original_thread_id:
        owned_conditions.append(GatewaySavedReport.original_conversation_id == original_thread_id)
    if created_from:
        owned_conditions.append(GatewaySavedReport.updated_at >= created_from)
    if created_to:
        owned_conditions.append(GatewaySavedReport.updated_at <= created_to)
    if freshness:
        owned_conditions.append(GatewaySavedReportVersion.freshness_state == freshness)
    if cursor:
        cursor_at, cursor_id = cursor
        owned_conditions.append(
            or_(
                GatewaySavedReport.updated_at < cursor_at,
                and_(GatewaySavedReport.updated_at == cursor_at, GatewaySavedReport.id < cursor_id),
            )
        )
    owned = list(
        (
            await db.execute(
                select(
                    GatewaySavedReport,
                    GatewaySavedReportVersion,
                    GatewayChatArtifact,
                    GatewayChatConversation,
                    GatewayWorkspaceProject,
                )
                .join(GatewaySavedReportVersion, GatewaySavedReportVersion.id == GatewaySavedReport.current_version_id)
                .join(GatewayChatArtifact, GatewayChatArtifact.id == GatewaySavedReportVersion.source_artifact_id)
                .join(
                    GatewayChatConversation, GatewayChatConversation.id == GatewaySavedReport.original_conversation_id
                )
                .outerjoin(GatewayWorkspaceProject, GatewayWorkspaceProject.id == GatewaySavedReport.project_id)
                .where(*owned_conditions)
                .order_by(GatewaySavedReport.updated_at.desc(), GatewaySavedReport.id.desc())
                .limit(limit + 1)
            )
        ).all()
    )

    shared_conditions = [
        GatewayReportShareAccess.org_id == org_id,
        GatewayReportShareAccess.recipient_user_id == user_id,
        GatewayReportShareGrant.state == "active",
    ]
    if search:
        shared_conditions.append(
            or_(
                func.lower(GatewaySavedReport.title).like(pattern),
                func.lower(GatewaySavedReportVersion.filename).like(pattern),
            )
        )
    if kind:
        shared_conditions.append(GatewaySavedReportVersion.kind == kind)
    # Shared versions intentionally expose neither project nor original thread.
    if project_id or original_thread_id:
        shared_conditions.append(False)
    if created_from:
        shared_conditions.append(GatewaySavedReportVersion.published_at >= created_from)
    if created_to:
        shared_conditions.append(GatewaySavedReportVersion.published_at <= created_to)
    if freshness:
        shared_conditions.append(GatewaySavedReportVersion.freshness_state == freshness)
    if cursor:
        cursor_at, cursor_id = cursor
        shared_conditions.append(
            or_(
                GatewaySavedReportVersion.published_at < cursor_at,
                and_(GatewaySavedReportVersion.published_at == cursor_at, GatewaySavedReportVersion.id < cursor_id),
            )
        )
    shared = list(
        (
            await db.execute(
                select(
                    GatewaySavedReport,
                    GatewaySavedReportVersion,
                    GatewayChatArtifact,
                    GatewayReportShareAccess,
                )
                .join(GatewayReportShareGrant, GatewayReportShareGrant.id == GatewayReportShareAccess.grant_id)
                .join(GatewaySavedReportVersion, GatewaySavedReportVersion.id == GatewayReportShareGrant.version_id)
                .join(GatewaySavedReport, GatewaySavedReport.id == GatewaySavedReportVersion.report_id)
                .join(GatewayChatArtifact, GatewayChatArtifact.id == GatewaySavedReportVersion.source_artifact_id)
                .where(*shared_conditions)
                .order_by(GatewaySavedReportVersion.published_at.desc(), GatewaySavedReportVersion.id.desc())
                .limit(limit + 1)
            )
        ).all()
    )
    sortable: list[tuple[datetime, str, LibraryReport]] = []
    for report, version, artifact, conversation, project in owned:
        sortable.append(
            (
                report.updated_at,
                report.id,
                LibraryReport(
                    id=report.id,
                    report_id=report.id,
                    title=report.title,
                    kind=report.kind,
                    filename=version.filename,
                    is_shared=False,
                    project_id=report.project_id,
                    project_name=(project.display_name or project.name) if project else None,
                    original_thread_id=report.original_conversation_id,
                    original_thread_title=conversation.title or "New chat",
                    version_id=version.id,
                    version_ordinal=version.ordinal,
                    freshness_state=version.freshness_state,
                    freshness_at=version.freshness_at,
                    freshness_checked_at=version.freshness_checked_at,
                    updated_at=report.updated_at,
                    snapshot=artifact.snapshot_json or {},
                    download_url=f"/api/chat/report-versions/{version.id}/download",
                ),
            )
        )
    for report, version, artifact, _access in shared:
        sortable.append(
            (
                version.published_at,
                version.id,
                LibraryReport(
                    id=f"shared:{version.id}",
                    report_id=None,
                    title=report.title,
                    kind=version.kind,
                    filename=version.filename,
                    is_shared=True,
                    version_id=version.id,
                    version_ordinal=version.ordinal,
                    freshness_state=version.freshness_state,
                    freshness_at=version.freshness_at,
                    freshness_checked_at=version.freshness_checked_at,
                    updated_at=version.published_at,
                    snapshot=artifact.snapshot_json or {},
                    download_url=f"/api/chat/report-versions/{version.id}/download",
                ),
            )
        )
    sortable.sort(key=lambda row: (row[0], row[1]), reverse=True)
    more = len(sortable) > limit
    selected = sortable[:limit]
    next_cursor = _encode_cursor((selected[-1][0], selected[-1][1])) if more and selected else None
    return [row[2] for row in selected], next_cursor


async def _library_facets(db: AsyncSession, *, org_id: str, user_id: str) -> LibraryFacets:
    rows = list(
        (
            await db.execute(
                select(GatewayChatArtifact.kind, GatewayWorkspaceProject, GatewayChatConversation)
                .join(GatewayChatConversation, GatewayChatConversation.id == GatewayChatArtifact.conversation_id)
                .outerjoin(GatewayWorkspaceProject, GatewayWorkspaceProject.id == GatewayChatConversation.project_id)
                .where(
                    GatewayChatArtifact.org_id == org_id,
                    GatewayChatArtifact.user_id == user_id,
                    GatewayChatConversation.surface == "standalone",
                )
            )
        ).all()
    )
    kinds: set[str] = set()
    projects: dict[str, str] = {}
    threads: dict[str, str] = {}
    for kind, project, conversation in rows:
        kinds.add(kind)
        if project:
            projects[project.id] = project.display_name or project.name
        threads[conversation.id] = conversation.title or "New chat"
    return LibraryFacets(
        artifact_types=sorted(kinds),
        projects=[{"id": row_id, "name": name} for row_id, name in sorted(projects.items(), key=lambda row: row[1])],
        original_threads=[
            {"id": row_id, "title": title} for row_id, title in sorted(threads.items(), key=lambda row: row[1])
        ],
    )


async def _owned_completed_artifact(
    db: AsyncSession, *, org_id: str, user_id: str, artifact_id: str
) -> tuple[GatewayChatArtifact, GatewayChatConversation] | None:
    return (
        await db.execute(
            select(GatewayChatArtifact, GatewayChatConversation)
            .join(GatewayChatConversation, GatewayChatConversation.id == GatewayChatArtifact.conversation_id)
            .join(GatewayChatRun, GatewayChatRun.id == GatewayChatArtifact.run_id)
            .where(
                GatewayChatArtifact.id == artifact_id,
                GatewayChatArtifact.org_id == org_id,
                GatewayChatArtifact.user_id == user_id,
                GatewayChatConversation.surface == "standalone",
                GatewayChatRun.status == "completed",
            )
        )
    ).one_or_none()


async def promote_artifact(
    db: AsyncSession, *, org_id: str, user_id: str, artifact_id: str, title: str
) -> tuple[str, GatewaySavedReport, GatewaySavedReportVersion]:
    owned = await _owned_completed_artifact(db, org_id=org_id, user_id=user_id, artifact_id=artifact_id)
    if owned is None:
        raise ReportNotFoundError
    artifact, conversation = owned
    refresh = (
        await db.execute(
            select(GatewayReportRefresh).where(
                GatewayReportRefresh.run_id == artifact.run_id,
                GatewayReportRefresh.org_id == org_id,
                GatewayReportRefresh.owner_user_id == user_id,
                GatewayReportRefresh.status == "update_available",
            )
        )
    ).scalar_one_or_none()
    if refresh and artifact.id in set(refresh.candidate_artifact_ids_json or []):
        status, report, version = await publish_version(
            db,
            org_id=org_id,
            user_id=user_id,
            report_id=refresh.report_id,
            artifact_id=artifact.id,
            expected_current_version_id=refresh.base_version_id,
        )
        return ("updated" if status == "created" else status), report, version

    title_key = title.lower()
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(f"saved-report:{org_id}:{user_id}:{title_key}")))
        )
    content_hash = await ensure_artifact_hash(db, artifact)
    existing_version = (
        await db.execute(
            select(GatewaySavedReportVersion).where(
                GatewaySavedReportVersion.org_id == org_id,
                GatewaySavedReportVersion.owner_user_id == user_id,
                or_(
                    GatewaySavedReportVersion.source_artifact_id == artifact.id,
                    and_(
                        GatewaySavedReportVersion.kind == artifact.kind,
                        GatewaySavedReportVersion.content_hash == content_hash,
                    ),
                ),
            )
        )
    ).scalar_one_or_none()
    if existing_version:
        report = await db.get(GatewaySavedReport, existing_version.report_id)
        assert report is not None
        return "existing", report, existing_version

    same_title = (
        await db.execute(
            select(GatewaySavedReport)
            .where(
                GatewaySavedReport.org_id == org_id,
                GatewaySavedReport.owner_user_id == user_id,
                func.lower(GatewaySavedReport.title) == title_key,
            )
            .order_by(GatewaySavedReport.updated_at.desc(), GatewaySavedReport.id.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()

    now = _now()
    provenance = artifact.provenance_json or {}
    if same_title is not None:
        if same_title.kind != artifact.kind:
            raise ReportValidationError("Report updates must preserve the artifact type")
        version = GatewaySavedReportVersion(
            id=str(uuid.uuid4()),
            report_id=same_title.id,
            org_id=org_id,
            owner_user_id=user_id,
            ordinal=same_title.revision + 1,
            source_artifact_id=artifact.id,
            kind=artifact.kind,
            content_hash=content_hash,
            filename=artifact.filename,
            freshness_state="fresh" if artifact.freshness_at else "unknown",
            freshness_at=artifact.freshness_at,
            freshness_checked_at=now,
            dbt_commit_sha=str(provenance.get("commit_sha") or conversation.commit_sha or "") or None,
            schema_fingerprint=str(provenance.get("schema_fingerprint") or "") or None,
            published_at=now,
        )
        db.add(version)
        same_title.current_version_id = version.id
        same_title.revision += 1
        same_title.updated_at = now
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            winner = (
                await db.execute(
                    select(GatewaySavedReportVersion).where(
                        GatewaySavedReportVersion.org_id == org_id,
                        GatewaySavedReportVersion.owner_user_id == user_id,
                        or_(
                            GatewaySavedReportVersion.source_artifact_id == artifact.id,
                            and_(
                                GatewaySavedReportVersion.kind == artifact.kind,
                                GatewaySavedReportVersion.content_hash == content_hash,
                            ),
                        ),
                    )
                )
            ).scalar_one_or_none()
            if winner is None:
                raise
            winner_report = await db.get(GatewaySavedReport, winner.report_id)
            assert winner_report is not None
            return "existing", winner_report, winner
        return "updated", same_title, version

    report = GatewaySavedReport(
        id=str(uuid.uuid4()),
        org_id=org_id,
        owner_user_id=user_id,
        project_id=conversation.project_id or "",
        original_conversation_id=conversation.id,
        kind=artifact.kind,
        title=title,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    version = GatewaySavedReportVersion(
        id=str(uuid.uuid4()),
        report_id=report.id,
        org_id=org_id,
        owner_user_id=user_id,
        ordinal=1,
        source_artifact_id=artifact.id,
        kind=artifact.kind,
        content_hash=content_hash,
        filename=artifact.filename,
        freshness_state="fresh" if artifact.freshness_at else "unknown",
        freshness_at=artifact.freshness_at,
        freshness_checked_at=now,
        dbt_commit_sha=str(provenance.get("commit_sha") or conversation.commit_sha or "") or None,
        schema_fingerprint=str(provenance.get("schema_fingerprint") or "") or None,
        published_at=now,
    )
    report.current_version_id = version.id
    db.add_all([report, version])
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        winner = (
            await db.execute(
                select(GatewaySavedReportVersion).where(
                    GatewaySavedReportVersion.org_id == org_id,
                    GatewaySavedReportVersion.owner_user_id == user_id,
                    or_(
                        GatewaySavedReportVersion.source_artifact_id == artifact.id,
                        and_(
                            GatewaySavedReportVersion.kind == artifact.kind,
                            GatewaySavedReportVersion.content_hash == content_hash,
                        ),
                    ),
                )
            )
        ).scalar_one_or_none()
        if winner is None:
            raise
        winner_report = await db.get(GatewaySavedReport, winner.report_id)
        assert winner_report is not None
        return "existing", winner_report, winner
    return "created", report, version


def _version_info(version: GatewaySavedReportVersion, artifact: GatewayChatArtifact) -> SavedVersionInfo:
    return SavedVersionInfo(
        id=version.id,
        ordinal=version.ordinal,
        kind=version.kind,
        filename=version.filename,
        content_hash=version.content_hash,
        freshness_state=version.freshness_state,
        freshness_at=version.freshness_at,
        freshness_checked_at=version.freshness_checked_at,
        dbt_commit_sha=version.dbt_commit_sha,
        schema_fingerprint=version.schema_fingerprint,
        published_at=version.published_at,
        snapshot=artifact.snapshot_json or {},
        download_url=f"/api/chat/report-versions/{version.id}/download",
    )


def _shared_version_info(version: GatewaySavedReportVersion, artifact: GatewayChatArtifact) -> SharedVersionInfo:
    return SharedVersionInfo(
        id=version.id,
        ordinal=version.ordinal,
        kind=version.kind,
        filename=version.filename,
        freshness_state=version.freshness_state,
        freshness_at=version.freshness_at,
        freshness_checked_at=version.freshness_checked_at,
        published_at=version.published_at,
        snapshot=artifact.snapshot_json or {},
        download_url=f"/api/chat/report-versions/{version.id}/download",
    )


async def get_owned_report_detail(
    db: AsyncSession, *, org_id: str, user_id: str, report_id: str
) -> SavedReportDetail | None:
    report = (
        await db.execute(
            select(GatewaySavedReport).where(
                GatewaySavedReport.id == report_id,
                GatewaySavedReport.org_id == org_id,
                GatewaySavedReport.owner_user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if report is None or not report.current_version_id:
        return None
    versions = list(
        (
            await db.execute(
                select(GatewaySavedReportVersion)
                .where(GatewaySavedReportVersion.report_id == report.id)
                .order_by(GatewaySavedReportVersion.ordinal.desc())
            )
        ).scalars()
    )
    artifact_ids = [version.source_artifact_id for version in versions]
    artifacts = {
        artifact.id: artifact
        for artifact in (
            await db.execute(select(GatewayChatArtifact).where(GatewayChatArtifact.id.in_(artifact_ids)))
        ).scalars()
    }
    current = next(version for version in versions if version.id == report.current_version_id)
    conversation = await db.get(GatewayChatConversation, report.original_conversation_id)
    project = await db.get(GatewayWorkspaceProject, report.project_id)
    latest_refresh = (
        await db.execute(
            select(GatewayReportRefresh)
            .where(
                GatewayReportRefresh.report_id == report.id,
                GatewayReportRefresh.org_id == org_id,
                GatewayReportRefresh.owner_user_id == user_id,
            )
            .order_by(GatewayReportRefresh.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    active_share_version_ids = list(
        (
            await db.execute(
                select(GatewayReportShareGrant.version_id).where(
                    GatewayReportShareGrant.report_id == report.id,
                    GatewayReportShareGrant.org_id == org_id,
                    GatewayReportShareGrant.owner_user_id == user_id,
                    GatewayReportShareGrant.state == "active",
                )
            )
        ).scalars()
    )
    refresh_info = None
    if latest_refresh:
        refresh_info = ReportRefreshInfo(
            id=latest_refresh.id,
            base_version_id=latest_refresh.base_version_id,
            status=latest_refresh.status,
            drift_state=latest_refresh.drift_state,
            explanation=str((latest_refresh.drift_json or {}).get("explanation") or ""),
            checked_at=latest_refresh.created_at,
            run_id=latest_refresh.run_id,
            candidate_artifact_ids=list(latest_refresh.candidate_artifact_ids_json or []),
        )
    return SavedReportDetail(
        id=report.id,
        title=report.title,
        kind=report.kind,
        project_id=report.project_id,
        project_name=(project.display_name or project.name) if project else None,
        original_thread_id=report.original_conversation_id,
        original_thread_title=(conversation.title or "New chat") if conversation else "Archived chat",
        current_version_id=report.current_version_id,
        revision=report.revision,
        created_at=report.created_at,
        updated_at=report.updated_at,
        current_version=_version_info(current, artifacts[current.source_artifact_id]),
        versions=[_version_info(version, artifacts[version.source_artifact_id]) for version in versions],
        active_share_version_ids=active_share_version_ids,
        refresh=refresh_info,
    )


async def verified_report_reference(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    report_id: str,
    version_id: str,
) -> dict[str, Any] | None:
    row = (
        await db.execute(
            select(GatewaySavedReport, GatewaySavedReportVersion)
            .join(
                GatewaySavedReportVersion,
                GatewaySavedReportVersion.report_id == GatewaySavedReport.id,
            )
            .where(
                GatewaySavedReport.id == report_id,
                GatewaySavedReport.org_id == org_id,
                GatewaySavedReport.owner_user_id == user_id,
                GatewaySavedReport.original_conversation_id == conversation_id,
                GatewaySavedReportVersion.id == version_id,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    report, version = row
    return {
        "mode": "follow_up",
        "report_id": report.id,
        "version_id": version.id,
        "version_ordinal": version.ordinal,
        "title": report.title,
        "kind": report.kind,
        "source_artifact_id": version.source_artifact_id,
    }


async def publish_version(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    report_id: str,
    artifact_id: str,
    expected_current_version_id: str,
) -> tuple[str, GatewaySavedReport, GatewaySavedReportVersion]:
    report = (
        await db.execute(
            select(GatewaySavedReport)
            .where(
                GatewaySavedReport.id == report_id,
                GatewaySavedReport.org_id == org_id,
                GatewaySavedReport.owner_user_id == user_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if report is None:
        raise ReportNotFoundError
    if report.current_version_id != expected_current_version_id:
        raise ReportConflictError(report.id, report.current_version_id or "")
    owned = await _owned_completed_artifact(db, org_id=org_id, user_id=user_id, artifact_id=artifact_id)
    if owned is None:
        raise ReportNotFoundError
    artifact, conversation = owned
    if artifact.kind != report.kind:
        raise ReportValidationError("Report updates must preserve the artifact type")
    refresh = (
        await db.execute(
            select(GatewayReportRefresh).where(
                GatewayReportRefresh.report_id == report.id,
                GatewayReportRefresh.base_version_id == expected_current_version_id,
                GatewayReportRefresh.run_id == artifact.run_id,
                GatewayReportRefresh.status == "update_available",
                GatewayReportRefresh.org_id == org_id,
                GatewayReportRefresh.owner_user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if refresh is None or artifact.id not in set(refresh.candidate_artifact_ids_json or []):
        raise ReportValidationError("Artifact is not a completed refresh candidate for this report")
    content_hash = await ensure_artifact_hash(db, artifact)
    matching = (
        await db.execute(
            select(GatewaySavedReportVersion).where(
                GatewaySavedReportVersion.org_id == org_id,
                GatewaySavedReportVersion.owner_user_id == user_id,
                GatewaySavedReportVersion.kind == artifact.kind,
                GatewaySavedReportVersion.content_hash == content_hash,
            )
        )
    ).scalar_one_or_none()
    if matching:
        if matching.report_id != report.id:
            raise ExistingContentError(matching.report_id, matching.id)
        refresh.status = "current"
        refresh.updated_at = _now()
        await db.commit()
        return "existing", report, matching
    now = _now()
    provenance = artifact.provenance_json or {}
    version = GatewaySavedReportVersion(
        id=str(uuid.uuid4()),
        report_id=report.id,
        org_id=org_id,
        owner_user_id=user_id,
        ordinal=report.revision + 1,
        source_artifact_id=artifact.id,
        kind=artifact.kind,
        content_hash=content_hash,
        filename=artifact.filename,
        freshness_state="fresh" if artifact.freshness_at else "unknown",
        freshness_at=artifact.freshness_at,
        freshness_checked_at=now,
        dbt_commit_sha=conversation.commit_sha,
        schema_fingerprint=str(provenance.get("schema_fingerprint") or "") or None,
        published_at=now,
    )
    db.add(version)
    report.current_version_id = version.id
    report.revision += 1
    report.updated_at = now
    refresh.status = "current"
    refresh.updated_at = now
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        actual = (
            await db.execute(
                select(GatewaySavedReport).where(
                    GatewaySavedReport.id == report_id,
                    GatewaySavedReport.org_id == org_id,
                    GatewaySavedReport.owner_user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if actual is None:
            raise ReportNotFoundError
        matching = (
            await db.execute(
                select(GatewaySavedReportVersion).where(
                    GatewaySavedReportVersion.org_id == org_id,
                    GatewaySavedReportVersion.owner_user_id == user_id,
                    GatewaySavedReportVersion.kind == artifact.kind,
                    GatewaySavedReportVersion.content_hash == content_hash,
                )
            )
        ).scalar_one_or_none()
        if matching and matching.report_id == actual.id:
            return "existing", actual, matching
        raise ReportConflictError(actual.id, actual.current_version_id or "")
    return "created", report, version


async def refresh_context(
    db: AsyncSession, *, org_id: str, user_id: str, report_id: str
) -> tuple[GatewaySavedReport, GatewaySavedReportVersion] | None:
    return (
        await db.execute(
            select(
                GatewaySavedReport,
                GatewaySavedReportVersion,
            )
            .join(GatewaySavedReportVersion, GatewaySavedReportVersion.id == GatewaySavedReport.current_version_id)
            .join(GatewayChatConversation, GatewayChatConversation.id == GatewaySavedReport.original_conversation_id)
            .where(
                GatewaySavedReport.id == report_id,
                GatewaySavedReport.org_id == org_id,
                GatewaySavedReport.owner_user_id == user_id,
                GatewayChatConversation.org_id == org_id,
                GatewayChatConversation.user_id == user_id,
                GatewayChatConversation.surface == "standalone",
            )
        )
    ).one_or_none()


async def create_refresh(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    report_id: str,
    expected_version_id: str,
) -> GatewayReportRefresh:
    report = (
        await db.execute(
            select(GatewaySavedReport).where(
                GatewaySavedReport.id == report_id,
                GatewaySavedReport.org_id == org_id,
                GatewaySavedReport.owner_user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if report is None:
        raise ReportNotFoundError
    if report.current_version_id != expected_version_id:
        raise ReportConflictError(report.id, report.current_version_id or "")
    now = _now()
    version = await db.get(GatewaySavedReportVersion, expected_version_id)
    assert version is not None
    refresh = GatewayReportRefresh(
        id=str(uuid.uuid4()),
        report_id=report.id,
        base_version_id=expected_version_id,
        org_id=org_id,
        owner_user_id=user_id,
        original_conversation_id=report.original_conversation_id,
        drift_state="unknown",
        drift_json={"explanation": "Refresh requested in the original thread."},
        status="refreshing",
        candidate_artifact_ids_json=[],
        created_at=now,
        updated_at=now,
    )
    db.add(refresh)
    await db.commit()
    await queue_refresh(db, refresh=refresh)
    return refresh


async def queue_refresh(db: AsyncSession, *, refresh: GatewayReportRefresh) -> None:
    from gateway.store import standalone_chat as chat_store

    report = await db.get(GatewaySavedReport, refresh.report_id)
    version = await db.get(GatewaySavedReportVersion, refresh.base_version_id)
    assert report is not None and version is not None
    if report.current_version_id != version.id:
        raise ReportConflictError(report.id, report.current_version_id or "")
    reference = {
        "mode": "refresh",
        "report_id": report.id,
        "version_id": version.id,
        "version_ordinal": version.ordinal,
        "title": report.title,
        "kind": report.kind,
        "source_artifact_id": version.source_artifact_id,
        "drift": refresh.drift_json,
    }
    prompt = (
        f'Refresh saved report "{report.title}" using current live warehouse data. '
        f"Publish a {report.kind} artifact for review."
    )
    try:
        run = await chat_store.create_run(
            db,
            org_id=refresh.org_id,
            user_id=refresh.owner_user_id,
            conversation_id=refresh.original_conversation_id,
            message=prompt,
            message_metadata={"report_reference": reference},
        )
    except Exception:
        refresh = await db.get(GatewayReportRefresh, refresh.id)
        if refresh:
            refresh.status = "failed"
            refresh.updated_at = _now()
            await db.commit()
        raise
    refresh = await db.get(GatewayReportRefresh, refresh.id)
    assert refresh is not None
    refresh.run_id = run.id
    refresh.status = "refreshing"
    refresh.updated_at = _now()
    await db.commit()


async def finalize_refresh_for_run(db: AsyncSession, *, run: GatewayChatRun, succeeded: bool) -> None:
    refresh = (
        await db.execute(
            select(GatewayReportRefresh).where(
                GatewayReportRefresh.run_id == run.id,
                GatewayReportRefresh.org_id == run.org_id,
                GatewayReportRefresh.owner_user_id == run.user_id,
            )
        )
    ).scalar_one_or_none()
    if refresh is None:
        return
    now = _now()
    if not succeeded:
        refresh.status = "failed"
        refresh.updated_at = now
        refresh.completed_at = now
        return
    report = await db.get(GatewaySavedReport, refresh.report_id)
    if report is None:
        refresh.status = "failed"
        refresh.updated_at = now
        return
    candidates = list(
        (
            await db.execute(
                select(GatewayChatArtifact.id).where(
                    GatewayChatArtifact.run_id == run.id,
                    GatewayChatArtifact.org_id == run.org_id,
                    GatewayChatArtifact.user_id == run.user_id,
                    GatewayChatArtifact.kind == report.kind,
                )
            )
        ).scalars()
    )
    refresh.candidate_artifact_ids_json = candidates
    refresh.status = "update_available" if candidates else "failed"
    refresh.updated_at = now
    refresh.completed_at = now


async def rebind_refresh_retry(db: AsyncSession, *, failed_run_id: str, retry_run_id: str) -> None:
    refresh = (
        await db.execute(select(GatewayReportRefresh).where(GatewayReportRefresh.run_id == failed_run_id))
    ).scalar_one_or_none()
    if refresh is None:
        return
    refresh.run_id = retry_run_id
    refresh.status = "refreshing"
    refresh.candidate_artifact_ids_json = []
    refresh.completed_at = None
    refresh.updated_at = _now()


async def create_share_grant(
    db: AsyncSession, *, org_id: str, user_id: str, version_id: str
) -> tuple[GatewayReportShareGrant, str]:
    row = (
        await db.execute(
            select(GatewaySavedReportVersion, GatewaySavedReport)
            .join(GatewaySavedReport, GatewaySavedReport.id == GatewaySavedReportVersion.report_id)
            .where(
                GatewaySavedReportVersion.id == version_id,
                GatewaySavedReport.org_id == org_id,
                GatewaySavedReport.owner_user_id == user_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise ReportNotFoundError
    version, report = row
    active = (
        await db.execute(
            select(GatewayReportShareGrant.id).where(
                GatewayReportShareGrant.version_id == version.id,
                GatewayReportShareGrant.state == "active",
            )
        )
    ).scalar_one_or_none()
    if active:
        raise ActiveShareGrantError("This version already has an active share link")
    token = secrets.token_urlsafe(32)
    grant = GatewayReportShareGrant(
        id=str(uuid.uuid4()),
        version_id=version.id,
        report_id=report.id,
        org_id=org_id,
        owner_user_id=user_id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        state="active",
    )
    db.add(grant)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ActiveShareGrantError("This version already has an active share link") from exc
    return grant, token


async def revoke_share_grant(db: AsyncSession, *, org_id: str, user_id: str, version_id: str) -> bool:
    owned = (
        await db.execute(
            select(GatewaySavedReportVersion.id)
            .join(GatewaySavedReport, GatewaySavedReport.id == GatewaySavedReportVersion.report_id)
            .where(
                GatewaySavedReportVersion.id == version_id,
                GatewaySavedReport.org_id == org_id,
                GatewaySavedReport.owner_user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if owned is None:
        return False
    grants = list(
        (
            await db.execute(
                select(GatewayReportShareGrant).where(
                    GatewayReportShareGrant.version_id == version_id,
                    GatewayReportShareGrant.state == "active",
                )
            )
        ).scalars()
    )
    now = _now()
    for grant in grants:
        grant.state = "revoked"
        grant.revoked_at = now
        await db.execute(delete(GatewayReportShareAccess).where(GatewayReportShareAccess.grant_id == grant.id))
    await db.commit()
    return True


async def redeem_shared_report(
    db: AsyncSession, *, org_id: str, recipient_user_id: str, token: str
) -> SharedSavedReport | None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = (
        await db.execute(
            select(
                GatewayReportShareGrant,
                GatewaySavedReportVersion,
                GatewaySavedReport,
                GatewayChatArtifact,
            )
            .join(GatewaySavedReportVersion, GatewaySavedReportVersion.id == GatewayReportShareGrant.version_id)
            .join(GatewaySavedReport, GatewaySavedReport.id == GatewayReportShareGrant.report_id)
            .join(GatewayChatArtifact, GatewayChatArtifact.id == GatewaySavedReportVersion.source_artifact_id)
            .where(
                GatewayReportShareGrant.org_id == org_id,
                GatewayReportShareGrant.token_hash == token_hash,
                GatewayReportShareGrant.state == "active",
            )
        )
    ).one_or_none()
    if row is None:
        return None
    grant, version, report, artifact = row
    access = (
        await db.execute(
            select(GatewayReportShareAccess).where(
                GatewayReportShareAccess.grant_id == grant.id,
                GatewayReportShareAccess.recipient_user_id == recipient_user_id,
            )
        )
    ).scalar_one_or_none()
    if recipient_user_id == grant.owner_user_id:
        pass
    elif access is None:
        db.add(
            GatewayReportShareAccess(
                id=str(uuid.uuid4()),
                grant_id=grant.id,
                org_id=org_id,
                recipient_user_id=recipient_user_id,
            )
        )
    else:
        access.last_opened_at = _now()
    await db.commit()
    return SharedSavedReport(
        title=report.title,
        kind=version.kind,
        version=_shared_version_info(version, artifact),
        shared_at=grant.created_at,
    )


async def authorized_version_artifact(
    db: AsyncSession, *, org_id: str, user_id: str, version_id: str
) -> GatewayChatArtifact | None:
    owned = (
        await db.execute(
            select(GatewayChatArtifact)
            .join(GatewaySavedReportVersion, GatewaySavedReportVersion.source_artifact_id == GatewayChatArtifact.id)
            .where(
                GatewaySavedReportVersion.id == version_id,
                GatewaySavedReportVersion.org_id == org_id,
                GatewaySavedReportVersion.owner_user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if owned:
        return owned
    return (
        await db.execute(
            select(GatewayChatArtifact)
            .join(GatewaySavedReportVersion, GatewaySavedReportVersion.source_artifact_id == GatewayChatArtifact.id)
            .join(GatewayReportShareGrant, GatewayReportShareGrant.version_id == GatewaySavedReportVersion.id)
            .join(GatewayReportShareAccess, GatewayReportShareAccess.grant_id == GatewayReportShareGrant.id)
            .where(
                GatewaySavedReportVersion.id == version_id,
                GatewayReportShareGrant.org_id == org_id,
                GatewayReportShareGrant.state == "active",
                GatewayReportShareAccess.org_id == org_id,
                GatewayReportShareAccess.recipient_user_id == user_id,
            )
        )
    ).scalar_one_or_none()
