"""Persistence authority for the Data Chat artifact library and saved reports."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import unicodedata
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
    GatewayChatMessage,
    GatewayChatRun,
    GatewayQueryPlan,
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
    ReportCatalogCard,
    ReportCatalogPage,
    ReportContextMessage,
    ReportContextPackage,
    ReportHistoricalQuery,
    ReportMention,
    ReportMentionCollection,
    ReportRefreshInfo,
    ReportSuggestion,
    ReportSuggestionApprovalResult,
    ReportVersionTimelineItem,
    SavedReportDetail,
    SavedVersionInfo,
    SharedSavedReport,
    SharedVersionInfo,
)
from gateway.standalone_chat.artifacts import table_to_csv
from gateway.standalone_chat.domain import redact_public_payload
from gateway.standalone_chat.object_storage import chat_object_storage


def _now() -> datetime:
    return datetime.now(UTC)


class ReportNotFoundError(LookupError):
    pass


class ReportValidationError(ValueError):
    pass


class ReportCatalogChangedError(RuntimeError):
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


def normalize_report_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))


def _artifact_output_fields(artifact: GatewayChatArtifact) -> list[str]:
    snapshot = artifact.snapshot_json or {}
    if artifact.kind == "chart":
        spec = snapshot.get("spec") if isinstance(snapshot.get("spec"), dict) else {}
        encoding = spec.get("encoding") if isinstance(spec.get("encoding"), dict) else {}
        fields = [
            str(value.get("field")) for value in encoding.values() if isinstance(value, dict) and value.get("field")
        ]
        if fields:
            return list(dict.fromkeys(fields))[:50]
        snapshot = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else snapshot
    columns = snapshot.get("columns") if isinstance(snapshot, dict) else []
    return list(
        dict.fromkeys(
            str(column.get("name") if isinstance(column, dict) else column) for column in (columns or []) if column
        )
    )[:50]


def _referenced_models(sql: str) -> list[str]:
    try:
        from sqlglot import exp, parse_one

        expression = parse_one(sql)
        return list(dict.fromkeys(table.sql() for table in expression.find_all(exp.Table) if table.name))[:100]
    except Exception:
        return []


def _artifact_context_metadata(artifact: GatewayChatArtifact) -> dict[str, Any]:
    provenance = artifact.provenance_json or {}
    safe_provenance: dict[str, Any] = {
        key: provenance[key]
        for key in (
            "code_hash",
            "execution_id",
            "result_id",
            "schema_fingerprint",
        )
        if isinstance(provenance.get(key), (str, int, float, bool))
    }
    for key in ("artifact_references", "source_result_ids"):
        if isinstance(provenance.get(key), list):
            safe_provenance[key] = [str(value)[:500] for value in provenance[key][:100]]
    if isinstance(provenance.get("result_references"), list):
        safe_provenance["result_references"] = [
            {key: reference[key] for key in ("result_id", "execution_id", "completeness") if key in reference}
            for reference in provenance["result_references"][:100]
            if isinstance(reference, dict)
        ]
    return {
        "artifact_id": artifact.id,
        "filename": artifact.filename,
        "kind": artifact.kind,
        "mime_type": artifact.mime_type,
        "output_fields": _artifact_output_fields(artifact),
        "byte_size": artifact.byte_size,
        "provenance": safe_provenance,
    }


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


def _encode_catalog_cursor(revision: str, offset: int) -> str:
    payload = json.dumps([revision, offset], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_catalog_cursor(value: str | None) -> tuple[str, int]:
    if not value:
        return "", 0
    try:
        padded = value + "=" * (-len(value) % 4)
        revision, offset = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(revision, str) or not isinstance(offset, int) or offset < 0:
            raise ValueError
        return revision, offset
    except Exception as exc:
        raise ReportValidationError("Invalid report catalog cursor") from exc


async def report_catalog_revision(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project_id: str,
) -> tuple[str, int]:
    rows = (
        await db.execute(
            select(
                GatewaySavedReport.id,
                GatewaySavedReport.current_version_id,
                GatewaySavedReport.revision,
                GatewaySavedReport.updated_at,
            )
            .where(
                GatewaySavedReport.org_id == org_id,
                GatewaySavedReport.owner_user_id == user_id,
                GatewaySavedReport.project_id == project_id,
            )
            .order_by(GatewaySavedReport.id)
        )
    ).all()
    canonical = [
        [report_id, version_id, revision, updated_at.isoformat()]
        for report_id, version_id, revision, updated_at in rows
    ]
    digest = hashlib.sha256(json.dumps(canonical, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    return digest, len(rows)


async def list_report_mentions(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project_id: str,
    search: str | None = None,
    limit: int = 10,
) -> ReportMentionCollection:
    conditions = [
        GatewaySavedReport.org_id == org_id,
        GatewaySavedReport.owner_user_id == user_id,
        GatewaySavedReport.project_id == project_id,
        GatewaySavedReport.current_version_id.is_not(None),
    ]
    normalized_search = (search or "").strip().lower()
    if normalized_search:
        conditions.append(func.lower(GatewaySavedReport.title).like(f"%{normalized_search}%"))
    reports = list(
        (
            await db.execute(
                select(GatewaySavedReport)
                .where(*conditions)
                .order_by(GatewaySavedReport.updated_at.desc(), GatewaySavedReport.id.desc())
                .limit(limit)
            )
        ).scalars()
    )
    return ReportMentionCollection(
        items=[
            ReportMention(
                report_id=report.id,
                title=report.title,
                kind=report.kind,
                project_id=report.project_id,
                current_version_id=report.current_version_id or "",
            )
            for report in reports
        ]
    )


async def list_saved_report_catalog(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project_id: str,
    cursor: str | None = None,
    limit: int = 50,
) -> ReportCatalogPage:
    """Return compact report semantics without rows, HTML, credentials, or traces."""
    current_revision, total_reports = await report_catalog_revision(
        db,
        org_id=org_id,
        user_id=user_id,
        project_id=project_id,
    )
    cursor_revision, offset = _decode_catalog_cursor(cursor)
    if cursor_revision and cursor_revision != current_revision:
        raise ReportCatalogChangedError("The report catalog changed during the scan")
    reports = list(
        (
            await db.execute(
                select(GatewaySavedReport)
                .where(
                    GatewaySavedReport.org_id == org_id,
                    GatewaySavedReport.owner_user_id == user_id,
                    GatewaySavedReport.project_id == project_id,
                    GatewaySavedReport.current_version_id.is_not(None),
                )
                .order_by(GatewaySavedReport.id)
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    if not reports:
        return ReportCatalogPage(
            items=[],
            catalog_revision=current_revision,
            total_reports=total_reports,
            next_cursor=None,
            proactive_creation_allowed=total_reports <= 500,
        )

    report_ids = [report.id for report in reports]
    current_ids = [report.current_version_id for report in reports if report.current_version_id]
    version_rows = (
        await db.execute(
            select(GatewaySavedReportVersion, GatewayChatArtifact)
            .join(GatewayChatArtifact, GatewayChatArtifact.id == GatewaySavedReportVersion.source_artifact_id)
            .where(
                or_(
                    GatewaySavedReportVersion.id.in_(current_ids),
                    and_(
                        GatewaySavedReportVersion.report_id.in_(report_ids),
                        GatewaySavedReportVersion.ordinal == 1,
                    ),
                )
            )
        )
    ).all()
    version_by_id = {version.id: (version, artifact) for version, artifact in version_rows}
    creation_by_report = {
        version.report_id: (version, artifact) for version, artifact in version_rows if version.ordinal == 1
    }
    run_ids = {artifact.run_id for _, artifact in version_rows}
    runs = {
        run.id: run
        for run in (await db.execute(select(GatewayChatRun).where(GatewayChatRun.id.in_(run_ids)))).scalars()
    }
    message_ids = {run.user_message_id for run in runs.values()} | {
        artifact.assistant_message_id for _, artifact in version_rows if artifact.assistant_message_id
    }
    messages = {
        message.id: message
        for message in (
            await db.execute(select(GatewayChatMessage).where(GatewayChatMessage.id.in_(message_ids)))
        ).scalars()
    }
    current_run_ids = {
        version_by_id[report.current_version_id][1].run_id
        for report in reports
        if report.current_version_id in version_by_id
    }
    plans_by_run: dict[str, list[GatewayQueryPlan]] = {}
    if current_run_ids:
        plans = (
            await db.execute(
                select(GatewayQueryPlan)
                .where(GatewayQueryPlan.run_id.in_(current_run_ids), GatewayQueryPlan.shadow.is_(False))
                .order_by(GatewayQueryPlan.created_at)
            )
        ).scalars()
        for plan in plans:
            plans_by_run.setdefault(str(plan.run_id), []).append(plan)

    cards: list[ReportCatalogCard] = []
    for report in reports:
        current_row = version_by_id.get(report.current_version_id or "")
        creation_row = creation_by_report.get(report.id)
        if current_row is None or creation_row is None:
            continue
        current_version, current_artifact = current_row
        _, creation_artifact = creation_row
        creation_run = runs.get(creation_artifact.run_id)
        request_message = messages.get(creation_run.user_message_id) if creation_run else None
        plans = plans_by_run.get(current_artifact.run_id, [])
        cards.append(
            ReportCatalogCard(
                report_id=report.id,
                title=report.title,
                artifact_kind=report.kind,
                original_business_request=(
                    str(redact_public_payload(request_message.content))[:4_000] if request_message else ""
                ),
                main_output_fields=_artifact_output_fields(current_artifact),
                query_purposes=list(dict.fromkeys(plan.purpose for plan in plans))[:20],
                referenced_models=list(
                    dict.fromkeys(model for plan in plans for model in _referenced_models(plan.normalized_sql))
                )[:100],
                assumptions=[str(value)[:500] for value in (current_artifact.assumptions or [])[:50]],
                exclusions=[str(value)[:500] for value in (current_artifact.exclusions or [])[:50]],
                caveats=[str(value)[:500] for value in (current_artifact.caveats or [])[:50]],
                current_version_id=current_version.id,
                current_version=current_version.ordinal,
                freshness_state=current_version.freshness_state,
                freshness_at=current_version.freshness_at,
                updated_at=report.updated_at,
            )
        )
    next_offset = offset + len(reports)
    return ReportCatalogPage(
        items=cards,
        next_cursor=(_encode_catalog_cursor(current_revision, next_offset) if next_offset < total_reports else None),
        catalog_revision=current_revision,
        total_reports=total_reports,
        proactive_creation_allowed=total_reports <= 500,
    )


async def load_report_context(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project_id: str,
    report_id: str,
) -> ReportContextPackage | None:
    report = (
        await db.execute(
            select(GatewaySavedReport).where(
                GatewaySavedReport.id == report_id,
                GatewaySavedReport.org_id == org_id,
                GatewaySavedReport.owner_user_id == user_id,
                GatewaySavedReport.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if report is None or not report.current_version_id:
        return None
    version_rows = (
        await db.execute(
            select(GatewaySavedReportVersion, GatewayChatArtifact)
            .join(GatewayChatArtifact, GatewayChatArtifact.id == GatewaySavedReportVersion.source_artifact_id)
            .where(
                GatewaySavedReportVersion.report_id == report.id,
                GatewaySavedReportVersion.org_id == org_id,
                GatewaySavedReportVersion.owner_user_id == user_id,
            )
            .order_by(GatewaySavedReportVersion.ordinal)
        )
    ).all()
    if not version_rows:
        return None
    run_ids = {artifact.run_id for _, artifact in version_rows}
    runs = {
        run.id: run
        for run in (
            await db.execute(
                select(GatewayChatRun).where(
                    GatewayChatRun.id.in_(run_ids),
                    GatewayChatRun.org_id == org_id,
                    GatewayChatRun.user_id == user_id,
                    GatewayChatRun.project_id == project_id,
                )
            )
        ).scalars()
    }
    conversations = {
        conversation.id: conversation
        for conversation in (
            await db.execute(
                select(GatewayChatConversation).where(
                    GatewayChatConversation.id.in_({run.conversation_id for run in runs.values()}),
                    GatewayChatConversation.org_id == org_id,
                    GatewayChatConversation.user_id == user_id,
                    GatewayChatConversation.project_id == project_id,
                    GatewayChatConversation.surface == "standalone",
                )
            )
        ).scalars()
    }
    message_ids = {run.user_message_id for run in runs.values()} | {
        artifact.assistant_message_id for _, artifact in version_rows if artifact.assistant_message_id
    }
    messages = {
        message.id: message
        for message in (
            await db.execute(
                select(GatewayChatMessage).where(
                    GatewayChatMessage.id.in_(message_ids),
                    GatewayChatMessage.org_id == org_id,
                    GatewayChatMessage.user_id == user_id,
                    GatewayChatMessage.project_id == project_id,
                )
            )
        ).scalars()
    }
    plans = list(
        (
            await db.execute(
                select(GatewayQueryPlan)
                .where(
                    GatewayQueryPlan.run_id.in_(run_ids),
                    GatewayQueryPlan.org_id == org_id,
                    GatewayQueryPlan.user_id == user_id,
                    GatewayQueryPlan.project_id == project_id,
                    GatewayQueryPlan.shadow.is_(False),
                )
                .order_by(GatewayQueryPlan.created_at)
            )
        ).scalars()
    )

    def message_context(version: GatewaySavedReportVersion, artifact: GatewayChatArtifact) -> ReportContextMessage:
        run = runs.get(artifact.run_id)
        conversation = conversations.get(run.conversation_id) if run else None
        request = messages.get(run.user_message_id) if run else None
        answer = messages.get(artifact.assistant_message_id or "")
        return ReportContextMessage(
            request=(str(redact_public_payload(request.content)) if request else ""),
            answer=(str(redact_public_payload(answer.content)) if answer else ""),
            source_thread_id=(conversation.id if conversation else artifact.conversation_id),
            source_run_id=(run.id if run else artifact.run_id),
        )

    creation_version, creation_artifact = version_rows[0]
    current_version, current_artifact = next(
        (row for row in version_rows if row[0].id == report.current_version_id),
        version_rows[-1],
    )
    timeline = []
    for version, artifact in version_rows:
        run = runs.get(artifact.run_id)
        conversation = conversations.get(run.conversation_id) if run else None
        timeline.append(
            ReportVersionTimelineItem(
                version_id=version.id,
                version=version.ordinal,
                artifact_id=artifact.id,
                artifact_kind=artifact.kind,
                artifact_filename=artifact.filename,
                source_thread_id=(conversation.id if conversation else artifact.conversation_id),
                source_thread_title=(conversation.title or "New chat") if conversation else "Archived chat",
                source_run_id=(run.id if run else artifact.run_id),
                published_at=version.published_at,
            )
        )
    return ReportContextPackage(
        report_id=report.id,
        title=report.title,
        artifact_kind=report.kind,
        project_id=report.project_id,
        current_version_id=current_version.id,
        current_version=current_version.ordinal,
        creation=message_context(creation_version, creation_artifact),
        current=message_context(current_version, current_artifact),
        version_timeline=timeline,
        current_artifact=_artifact_context_metadata(current_artifact),
        historical_queries=[
            ReportHistoricalQuery(
                source_run_id=str(plan.run_id or ""),
                purpose=plan.purpose[:4_000],
                normalized_sql=str(redact_public_payload(plan.normalized_sql))[:100_000],
                referenced_models=_referenced_models(plan.normalized_sql),
            )
            for plan in plans
        ],
        dbt_commit_sha=current_version.dbt_commit_sha,
        freshness_state=current_version.freshness_state,
        freshness_at=current_version.freshness_at,
        assumptions=[str(value)[:500] for value in (current_artifact.assumptions or [])[:100]],
        exclusions=[str(value)[:500] for value in (current_artifact.exclusions or [])[:100]],
        caveats=[str(value)[:500] for value in (current_artifact.caveats or [])[:100]],
    )


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


def _artifact_is_complete(artifact: GatewayChatArtifact) -> bool:
    snapshot = artifact.snapshot_json or {}
    if artifact.kind == "report":
        html = str(snapshot.get("html") or "").strip()
        references = (artifact.provenance_json or {}).get("result_references") or []
        return bool(html) and all(
            not isinstance(reference, dict) or reference.get("completeness") == "complete" for reference in references
        )
    source = snapshot.get("source") if artifact.kind == "chart" else snapshot
    if not isinstance(source, dict):
        return False
    completeness = source.get("completeness")
    return source.get("truncated") is not True and completeness in {None, "complete"}


async def validate_report_proposal_for_run(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
    proposal: dict[str, Any] | None,
) -> ReportSuggestion | None:
    if not proposal:
        return None
    action = str(proposal.get("action") or "")
    if action not in {"create", "update", "open"}:
        raise ReportValidationError("Unsupported report proposal action")
    artifact_kind = str(proposal.get("artifact_kind") or "")
    artifact_filename = str(proposal.get("artifact_filename") or "").strip()
    title = " ".join(str(proposal.get("title") or "").split()).strip()
    reason = " ".join(str(proposal.get("reason") or "").split()).strip()
    if artifact_kind not in {"table", "chart", "report"} or not artifact_filename:
        raise ReportValidationError("The proposed artifact is invalid")
    if not title or len(title) > 200 or not reason or len(reason) > 2_000:
        raise ReportValidationError("The report proposal title or reason is invalid")
    artifact = (
        await db.execute(
            select(GatewayChatArtifact).where(
                GatewayChatArtifact.run_id == run.id,
                GatewayChatArtifact.org_id == run.org_id,
                GatewayChatArtifact.user_id == run.user_id,
                GatewayChatArtifact.conversation_id == run.conversation_id,
                GatewayChatArtifact.kind == artifact_kind,
                GatewayChatArtifact.filename == artifact_filename,
            )
        )
    ).scalar_one_or_none()
    if artifact is None:
        raise ReportValidationError("The proposed artifact was not successfully published")
    if not _artifact_is_complete(artifact):
        raise ReportValidationError("Incomplete or truncated artifacts cannot become reports")

    content_hash = await ensure_artifact_hash(db, artifact)
    exact = (
        await db.execute(
            select(GatewaySavedReport, GatewaySavedReportVersion)
            .join(GatewaySavedReportVersion, GatewaySavedReportVersion.report_id == GatewaySavedReport.id)
            .where(
                GatewaySavedReport.org_id == run.org_id,
                GatewaySavedReport.owner_user_id == run.user_id,
                GatewaySavedReport.project_id == run.project_id,
                GatewaySavedReportVersion.kind == artifact.kind,
                GatewaySavedReportVersion.content_hash == content_hash,
            )
            .order_by(GatewaySavedReportVersion.ordinal.desc())
            .limit(1)
        )
    ).one_or_none()
    if exact is not None:
        exact_report, _ = exact
        if not exact_report.current_version_id:
            raise ReportValidationError("The exact report match has no current version")
        return ReportSuggestion(
            action="open",
            artifact_id=artifact.id,
            title=exact_report.title,
            reason="An exact saved version already exists.",
            report_id=exact_report.id,
            expected_current_version_id=exact_report.current_version_id,
            catalog_revision=str(proposal.get("catalog_revision") or "") or None,
        )

    project_reports = list(
        (
            await db.execute(
                select(GatewaySavedReport).where(
                    GatewaySavedReport.org_id == run.org_id,
                    GatewaySavedReport.owner_user_id == run.user_id,
                    GatewaySavedReport.project_id == run.project_id,
                )
            )
        ).scalars()
    )
    normalized_title = normalize_report_title(title)
    title_match = next(
        (report for report in project_reports if normalize_report_title(report.title) == normalized_title),
        None,
    )
    existing_report_id = str(proposal.get("existing_report_id") or "") or None
    loaded_report_ids = {str(value) for value in proposal.get("loaded_report_ids") or []}
    attached_report_id = str(proposal.get("attached_report_id") or "") or None
    scan_complete = proposal.get("catalog_scan_complete") is True
    creation_allowed = proposal.get("proactive_creation_allowed") is True
    catalog_revision = str(proposal.get("catalog_revision") or "") or None

    if title_match is not None and existing_report_id != title_match.id:
        raise ReportValidationError("A normalized-title match must be updated instead of created")
    if action == "create":
        if existing_report_id:
            raise ReportValidationError("A create proposal cannot target an existing report")
        if not scan_complete or not creation_allowed or not catalog_revision:
            raise ReportValidationError("The complete report catalog must be scanned before creation")
        current_revision, total_reports = await report_catalog_revision(
            db,
            org_id=run.org_id,
            user_id=run.user_id,
            project_id=run.project_id,
        )
        if total_reports > 500:
            raise ReportValidationError("Proactive report creation is unavailable above 500 reports")
        if current_revision != catalog_revision:
            raise ReportCatalogChangedError("The report catalog changed after the scan")
        return ReportSuggestion(
            action="create",
            artifact_id=artifact.id,
            title=title,
            reason=reason,
            catalog_revision=catalog_revision,
        )

    if not existing_report_id:
        raise ReportValidationError("An update or open proposal requires an existing report")
    report = next((candidate for candidate in project_reports if candidate.id == existing_report_id), None)
    if report is None or not report.current_version_id:
        raise ReportNotFoundError("Report not found")
    if report.kind != artifact.kind:
        raise ReportValidationError("Report updates must preserve the artifact type")
    if action == "update" and existing_report_id != attached_report_id:
        if not scan_complete or existing_report_id not in loaded_report_ids:
            raise ReportValidationError("The matched report context must be loaded before an update")
    return ReportSuggestion(
        action=action,
        artifact_id=artifact.id,
        title=report.title,
        reason=reason,
        report_id=report.id,
        expected_current_version_id=report.current_version_id,
        catalog_revision=catalog_revision,
    )


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


async def _append_proposed_version(
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
    owned = await _owned_completed_artifact(
        db,
        org_id=org_id,
        user_id=user_id,
        artifact_id=artifact_id,
    )
    if owned is None:
        raise ReportNotFoundError
    artifact, conversation = owned
    if conversation.project_id != report.project_id:
        raise ReportValidationError("Report and artifact must belong to the same project")
    if artifact.kind != report.kind:
        raise ReportValidationError("Report updates must preserve the artifact type")
    if not _artifact_is_complete(artifact):
        raise ReportValidationError("Incomplete or truncated artifacts cannot become reports")
    content_hash = await ensure_artifact_hash(db, artifact)
    refresh = (
        await db.execute(
            select(GatewayReportRefresh).where(
                GatewayReportRefresh.report_id == report.id,
                GatewayReportRefresh.base_version_id == expected_current_version_id,
                GatewayReportRefresh.run_id == artifact.run_id,
                GatewayReportRefresh.org_id == org_id,
                GatewayReportRefresh.owner_user_id == user_id,
            )
        )
    ).scalar_one_or_none()
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
        matching_report = await db.get(GatewaySavedReport, matching.report_id)
        if matching.report_id != report.id:
            raise ExistingContentError(matching.report_id, matching.id)
        if refresh:
            refresh.status = "current"
            refresh.updated_at = _now()
            await db.commit()
        return "existing", matching_report or report, matching
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
        dbt_commit_sha=str(provenance.get("commit_sha") or conversation.commit_sha or "") or None,
        schema_fingerprint=str(provenance.get("schema_fingerprint") or "") or None,
        published_at=now,
    )
    db.add(version)
    report.current_version_id = version.id
    report.revision += 1
    report.updated_at = now
    if refresh:
        refresh.status = "current"
        refresh.updated_at = now
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        actual = await db.get(GatewaySavedReport, report.id)
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
        if matching and matching.report_id == report.id and actual:
            return "existing", actual, matching
        raise ReportConflictError(report.id, actual.current_version_id if actual else "") from None
    return "created", report, version


async def approve_report_suggestion(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    message_id: str,
) -> ReportSuggestionApprovalResult | None:
    message = (
        await db.execute(
            select(GatewayChatMessage)
            .where(
                GatewayChatMessage.id == message_id,
                GatewayChatMessage.org_id == org_id,
                GatewayChatMessage.user_id == user_id,
                GatewayChatMessage.role == "assistant",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if message is None:
        return None
    metadata = dict(message.metadata_json or {})
    raw_suggestion = metadata.get("report_suggestion")
    if not isinstance(raw_suggestion, dict):
        return None
    approved = raw_suggestion.get("approval")
    if isinstance(approved, dict):
        return ReportSuggestionApprovalResult(
            status=str(approved.get("status") or "existing"),
            report_id=str(approved.get("report_id") or ""),
            version_id=str(approved.get("version_id") or ""),
        )
    suggestion = ReportSuggestion.model_validate(raw_suggestion)
    artifact = (
        await db.execute(
            select(GatewayChatArtifact, GatewayChatConversation)
            .join(GatewayChatConversation, GatewayChatConversation.id == GatewayChatArtifact.conversation_id)
            .where(
                GatewayChatArtifact.id == suggestion.artifact_id,
                GatewayChatArtifact.assistant_message_id == message.id,
                GatewayChatArtifact.org_id == org_id,
                GatewayChatArtifact.user_id == user_id,
                GatewayChatConversation.project_id == message.project_id,
            )
        )
    ).one_or_none()
    if artifact is None:
        raise ReportNotFoundError
    source_artifact, _ = artifact

    if suggestion.action == "create":
        current_revision, total_reports = await report_catalog_revision(
            db,
            org_id=org_id,
            user_id=user_id,
            project_id=message.project_id or "",
        )
        if total_reports > 500 or current_revision != suggestion.catalog_revision:
            raise ReportCatalogChangedError("The report catalog changed after the scan")
        status, report, version = await promote_artifact(
            db,
            org_id=org_id,
            user_id=user_id,
            artifact_id=source_artifact.id,
            title=suggestion.title,
        )
        if report.project_id != message.project_id:
            raise ReportValidationError("Exact report content belongs to another project")
        result_status = "created" if status == "created" else "existing"
    elif suggestion.action == "update":
        if not suggestion.report_id or not suggestion.expected_current_version_id:
            raise ReportValidationError("The update suggestion is incomplete")
        status, report, version = await _append_proposed_version(
            db,
            org_id=org_id,
            user_id=user_id,
            report_id=suggestion.report_id,
            artifact_id=source_artifact.id,
            expected_current_version_id=suggestion.expected_current_version_id,
        )
        result_status = "updated" if status == "created" else "existing"
    else:
        report = await db.get(GatewaySavedReport, suggestion.report_id or "")
        if (
            report is None
            or report.org_id != org_id
            or report.owner_user_id != user_id
            or report.project_id != message.project_id
            or not report.current_version_id
        ):
            raise ReportNotFoundError
        version = await db.get(GatewaySavedReportVersion, report.current_version_id)
        if version is None:
            raise ReportNotFoundError
        result_status = "opened"

    approval = {
        "status": result_status,
        "report_id": report.id,
        "version_id": version.id,
        "approved_at": _now().isoformat(),
    }
    raw_suggestion = {**raw_suggestion, "approval": approval}
    message.metadata_json = {**metadata, "report_suggestion": raw_suggestion}
    await db.commit()
    return ReportSuggestionApprovalResult(
        status=result_status,
        report_id=report.id,
        version_id=version.id,
    )


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
            conversation_id=latest_refresh.original_conversation_id,
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
    conversation = (
        await db.execute(
            select(GatewayChatConversation).where(
                GatewayChatConversation.id == conversation_id,
                GatewayChatConversation.org_id == org_id,
                GatewayChatConversation.user_id == user_id,
                GatewayChatConversation.surface == "standalone",
            )
        )
    ).scalar_one_or_none()
    if conversation is None or not conversation.project_id:
        return None
    return await verified_project_report_reference(
        db,
        org_id=org_id,
        user_id=user_id,
        project_id=conversation.project_id,
        report_id=report_id,
    )


async def verified_project_report_reference(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project_id: str,
    report_id: str,
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
                GatewaySavedReport.project_id == project_id,
                GatewaySavedReportVersion.id == GatewaySavedReport.current_version_id,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    report, version = row
    return {
        "mode": "attached",
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
    project = await db.get(GatewayWorkspaceProject, report.project_id)
    source_conversation = await db.get(
        GatewayChatConversation,
        report.original_conversation_id,
    )
    if project is None or source_conversation is None:
        raise ReportNotFoundError
    reference = {
        "mode": "refresh",
        "report_id": report.id,
        "version_id": version.id,
        "version_ordinal": version.ordinal,
        "title": report.title,
        "kind": report.kind,
        "source_artifact_id": version.source_artifact_id,
    }
    prompt = (
        f'Refresh saved report "{report.title}" using current live warehouse data. '
        f"Publish a {report.kind} artifact for review."
    )
    from gateway.store import standalone_chat as chat_store

    conversation, run = await chat_store.create_conversation_with_run(
        db,
        org_id=org_id,
        user_id=user_id,
        project=project,
        branch=source_conversation.branch or project.default_branch or "main",
        message=prompt,
        commit_sha=source_conversation.commit_sha,
        per_query_budget_usd=source_conversation.per_query_budget_usd,
        chat_budget_usd=source_conversation.chat_budget_usd,
        message_metadata={"report_reference": reference},
        commit=False,
    )
    refresh = GatewayReportRefresh(
        id=str(uuid.uuid4()),
        report_id=report.id,
        base_version_id=expected_version_id,
        org_id=org_id,
        owner_user_id=user_id,
        original_conversation_id=conversation.id,
        drift_state="unknown",
        drift_json={"explanation": "Refresh requested in a new Data Chat."},
        run_id=run.id,
        status="refreshing",
        candidate_artifact_ids_json=[],
        created_at=now,
        updated_at=now,
    )
    db.add(refresh)
    await db.commit()
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
