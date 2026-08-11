"""Data Chat artifact library, immutable reports, refreshes, and fixed-version sharing."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import select

from gateway.db.models import GatewayChatArtifact, GatewayChatRun
from gateway.models.chat_reports import (
    ChatLibraryResponse,
    PromoteArtifactRequest,
    PromotionResult,
    PublishReportVersionRequest,
    RefreshCreateResult,
    ReportCatalogPage,
    ReportContextPackage,
    ReportMentionCollection,
    ReportShareGrantInfo,
    ReportSuggestionApprovalResult,
    SavedReportDetail,
    SharedSavedReport,
    VersionPublishResult,
)
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.config import enterprise_chat_feature_flags, standalone_chat_enabled
from gateway.store import chat_reports as report_store

from .deps import StoreD

router = APIRouter(prefix="/api/chat")


def _require_enabled() -> None:
    if not standalone_chat_enabled():
        raise HTTPException(status_code=404, detail="Data Chat reports are not available")


def _require_browser_principal(request: Request) -> None:
    auth = getattr(request.state, "auth", None) or {}
    claims = getattr(request.state, "_jwt_claims", None) or {}
    method = auth.get("auth_method")
    if method in {"api_key", "notebook_session"} or claims.get("execution_identity"):
        raise HTTPException(status_code=403, detail="An interactive browser user is required")


async def _require_runtime_run(request: Request, store: StoreD, run_id: str):
    claims = getattr(request.state, "_jwt_claims", None) or {}
    if claims.get("execution_identity") != f"chat:{run_id}":
        raise HTTPException(status_code=403, detail="A run-scoped identity is required")
    run = (
        await store.session.execute(
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.org_id == store._require_org_id(),
                GatewayChatRun.user_id == (store.user_id or "local"),
                GatewayChatRun.project_id == claims.get("project_id"),
                GatewayChatRun.status == "running",
                GatewayChatRun.cancellation_requested_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=403, detail="Report tool scope mismatch")
    return run


def _require_sharing() -> None:
    if not enterprise_chat_feature_flags().organization_sharing:
        raise HTTPException(status_code=404, detail="Report sharing is not available")


def _conflict(exc: report_store.ReportConflictError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "stale_report_version",
            "report_id": exc.report_id,
            "actual_current_version_id": exc.actual_current_version_id,
        },
    )


@router.get("/library", response_model=ChatLibraryResponse, dependencies=[RequireScope("read")])
async def get_library(
    store: StoreD,
    search: Annotated[str | None, Query(max_length=200)] = None,
    kind: Annotated[Literal["table", "chart", "report"] | None, Query()] = None,
    project_id: Annotated[str | None, Query(max_length=200)] = None,
    original_thread_id: Annotated[str | None, Query(max_length=100)] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    freshness: Annotated[Literal["fresh", "changes_detected", "unknown"] | None, Query()] = None,
    saved: Annotated[Literal["saved", "unsaved"] | None, Query()] = None,
    artifact_cursor: Annotated[str | None, Query(max_length=500)] = None,
    report_cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
):
    _require_enabled()
    if created_from and created_to and created_from > created_to:
        raise HTTPException(status_code=422, detail="created_from must be before created_to")
    try:
        return await report_store.list_library(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            search=search,
            kind=kind,
            project_id=project_id,
            original_thread_id=original_thread_id,
            created_from=created_from,
            created_to=created_to,
            freshness=freshness,
            saved=saved,
            artifact_cursor=artifact_cursor,
            report_cursor=report_cursor,
            limit=limit,
        )
    except report_store.ReportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/report-mentions",
    response_model=ReportMentionCollection,
    dependencies=[RequireScope("read")],
)
async def get_report_mentions(
    store: StoreD,
    project_id: Annotated[str, Query(min_length=1, max_length=200)],
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
):
    _require_enabled()
    return await report_store.list_report_mentions(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        project_id=project_id,
        search=search,
        limit=limit,
    )


@router.get(
    "/runs/{run_id}/report-catalog",
    response_model=ReportCatalogPage,
    dependencies=[RequireScope("read")],
)
async def get_run_report_catalog(
    run_id: str,
    store: StoreD,
    request: Request,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=50, le=50)] = 50,
):
    _require_enabled()
    run = await _require_runtime_run(request, store, run_id)
    try:
        return await report_store.list_saved_report_catalog(
            store.session,
            org_id=run.org_id,
            user_id=run.user_id,
            project_id=run.project_id,
            cursor=cursor,
            limit=limit,
        )
    except report_store.ReportCatalogChangedError as exc:
        raise HTTPException(status_code=409, detail={"code": "report_catalog_changed"}) from exc
    except report_store.ReportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/runs/{run_id}/report-context/{report_id}",
    response_model=ReportContextPackage,
    dependencies=[RequireScope("read")],
)
async def get_run_report_context(
    run_id: str,
    report_id: str,
    store: StoreD,
    request: Request,
):
    _require_enabled()
    run = await _require_runtime_run(request, store, run_id)
    context = await report_store.load_report_context(
        store.session,
        org_id=run.org_id,
        user_id=run.user_id,
        project_id=run.project_id,
        report_id=report_id,
    )
    if context is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return context


@router.get(
    "/runs/{run_id}/published-report-artifact",
    dependencies=[RequireScope("read")],
)
async def get_run_published_report_artifact(
    run_id: str,
    store: StoreD,
    request: Request,
    artifact_kind: Annotated[Literal["table", "chart", "report"], Query()],
    artifact_filename: Annotated[str, Query(min_length=1, max_length=255)],
):
    _require_enabled()
    run = await _require_runtime_run(request, store, run_id)
    artifact = (
        await store.session.execute(
            select(GatewayChatArtifact).where(
                GatewayChatArtifact.run_id == run.id,
                GatewayChatArtifact.org_id == run.org_id,
                GatewayChatArtifact.user_id == run.user_id,
                GatewayChatArtifact.kind == artifact_kind,
                GatewayChatArtifact.filename == artifact_filename,
            )
        )
    ).scalar_one_or_none()
    return {
        "published": artifact is not None,
        "complete": bool(artifact and report_store._artifact_is_complete(artifact)),
    }


@router.post(
    "/report-suggestions/{message_id}/approve",
    response_model=ReportSuggestionApprovalResult,
    dependencies=[RequireScope("write")],
)
async def approve_report_suggestion(
    message_id: str,
    store: StoreD,
    request: Request,
):
    _require_enabled()
    _require_browser_principal(request)
    try:
        result = await report_store.approve_report_suggestion(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            message_id=message_id,
        )
    except report_store.ReportCatalogChangedError as exc:
        raise HTTPException(status_code=409, detail={"code": "report_catalog_changed"}) from exc
    except report_store.ReportConflictError as exc:
        raise _conflict(exc) from exc
    except report_store.ExistingContentError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "existing_report_content", "report_id": exc.report_id},
        ) from exc
    except report_store.ReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Report suggestion not found") from exc
    except report_store.ReportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Report suggestion not found")
    return result


@router.post(
    "/reports",
    response_model=PromotionResult,
    status_code=201,
    dependencies=[RequireScope("write")],
)
async def promote_artifact(body: PromoteArtifactRequest, store: StoreD, request: Request, response: Response):
    _require_enabled()
    _require_browser_principal(request)
    try:
        status, report, version = await report_store.promote_artifact(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            artifact_id=body.artifact_id,
            title=body.title,
        )
    except report_store.ReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc
    except report_store.ReportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if status in {"existing", "updated"}:
        response.status_code = 200
    return PromotionResult(status=status, report_id=report.id, version_id=version.id)


@router.get("/reports/{report_id}", response_model=SavedReportDetail, dependencies=[RequireScope("read")])
async def get_report(report_id: str, store: StoreD):
    _require_enabled()
    detail = await report_store.get_owned_report_detail(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        report_id=report_id,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return detail


@router.post(
    "/reports/{report_id}/versions",
    response_model=VersionPublishResult,
    status_code=201,
    dependencies=[RequireScope("write")],
)
async def publish_version(
    report_id: str,
    body: PublishReportVersionRequest,
    store: StoreD,
    request: Request,
    response: Response,
):
    _require_enabled()
    _require_browser_principal(request)
    try:
        status, report, version = await report_store.publish_version(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            report_id=report_id,
            artifact_id=body.artifact_id,
            expected_current_version_id=body.expected_current_version_id,
        )
    except report_store.ReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Report or artifact not found") from exc
    except report_store.ReportConflictError as exc:
        raise _conflict(exc) from exc
    except report_store.ExistingContentError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "existing_report_content", "report_id": exc.report_id, "version_id": exc.version_id},
        ) from exc
    except report_store.ReportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if status == "existing":
        response.status_code = 200
    return VersionPublishResult(
        status=status,
        report_id=report.id,
        version_id=version.id,
        current_version_id=report.current_version_id or version.id,
    )


async def _refresh_context(store: StoreD, report_id: str) -> tuple[object, object]:
    context = await report_store.refresh_context(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        report_id=report_id,
    )
    if context is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return context


def _refresh_result(refresh) -> RefreshCreateResult:
    return RefreshCreateResult(
        refresh_id=refresh.id,
        report_id=refresh.report_id,
        version_id=refresh.base_version_id,
        conversation_id=refresh.original_conversation_id,
        run_id=refresh.run_id,
        status=refresh.status,
        drift_state=refresh.drift_state,
        explanation=str((refresh.drift_json or {}).get("explanation") or ""),
        checked_at=refresh.created_at,
    )


@router.post(
    "/reports/{report_id}/refreshes",
    response_model=RefreshCreateResult,
    status_code=201,
    dependencies=[RequireScope("write")],
)
async def create_refresh(report_id: str, store: StoreD, request: Request):
    _require_enabled()
    _require_browser_principal(request)
    report, version = await _refresh_context(store, report_id)
    try:
        refresh = await report_store.create_refresh(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            report_id=report.id,
            expected_version_id=version.id,
        )
    except report_store.ReportConflictError as exc:
        raise _conflict(exc) from exc
    except (RuntimeError, LookupError) as exc:
        raise HTTPException(status_code=409, detail="The original thread cannot start a refresh right now") from exc
    return _refresh_result(refresh)


@router.post(
    "/report-versions/{version_id}/share",
    response_model=ReportShareGrantInfo,
    status_code=201,
    dependencies=[RequireScope("write")],
)
async def share_version(version_id: str, store: StoreD, request: Request, response: Response):
    _require_enabled()
    _require_sharing()
    _require_browser_principal(request)
    try:
        grant, token = await report_store.create_share_grant(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            version_id=version_id,
        )
    except report_store.ReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Report version not found") from exc
    except report_store.ActiveShareGrantError as exc:
        raise HTTPException(status_code=409, detail={"code": "active_share_exists"}) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return ReportShareGrantInfo(token=token, version_id=version_id, created_at=grant.created_at)


@router.delete(
    "/report-versions/{version_id}/share",
    status_code=204,
    dependencies=[RequireScope("write")],
)
async def revoke_version_share(version_id: str, store: StoreD, request: Request):
    _require_enabled()
    _require_sharing()
    _require_browser_principal(request)
    found = await report_store.revoke_share_grant(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        version_id=version_id,
    )
    if not found:
        raise HTTPException(status_code=404, detail="Report version not found")
    return Response(status_code=204)


@router.get(
    "/shared-reports/{token}",
    response_model=SharedSavedReport,
    dependencies=[RequireScope("read")],
)
async def redeem_shared_report(token: str, store: StoreD, response: Response):
    _require_enabled()
    _require_sharing()
    shared = await report_store.redeem_shared_report(
        store.session,
        org_id=store._require_org_id(),
        recipient_user_id=store.user_id or "local",
        token=token,
    )
    if shared is None:
        raise HTTPException(
            status_code=404,
            detail="Shared report not found",
            headers={"Cache-Control": "private, no-store"},
        )
    response.headers["Cache-Control"] = "private, no-store"
    return shared


@router.get(
    "/report-versions/{version_id}/download",
    dependencies=[RequireScope("read")],
)
async def download_version(
    version_id: str,
    store: StoreD,
    format: Annotated[Literal["csv", "png", "html"] | None, Query()] = None,
):
    _require_enabled()
    artifact = await report_store.authorized_version_artifact(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        version_id=version_id,
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Report version not found")
    selected_format = format or {"table": "csv", "chart": "png", "report": "html"}[artifact.kind]
    allowed = {"table": {"csv"}, "chart": {"png", "csv"}, "report": {"html"}}[artifact.kind]
    if selected_format not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported report version format")
    try:
        content = await report_store.artifact_download_bytes(
            artifact,
            source=selected_format == "csv" and artifact.kind == "chart",
        )
    except report_store.ReportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    media_type = {"csv": "text/csv; charset=utf-8", "png": "image/png", "html": "text/html; charset=utf-8"}[
        selected_format
    ]
    base = artifact.filename.rsplit(".", 1)[0]
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{base}.{selected_format}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
