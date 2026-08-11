"""Standalone data-chat APIs, authenticated sharing, and event streaming."""

from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import io
import json
import re
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from gateway.auth import OrgRole
from gateway.db.engine import get_session_factory
from gateway.db.models import (
    GatewayChatArtifact,
    GatewayChatConversation,
    GatewayChatRun,
    GatewayChatRuntimeArchive,
    GatewayChatUserPreference,
    GatewayGovernedQueryExecution,
    GatewayStructuredQueryResult,
    GatewayWorkspaceProject,
)
from gateway.git.repos import branch_head_sha
from gateway.governance.query_executor import governed_query_executor
from gateway.models.standalone_chat import (
    ChatBootstrapResponse,
    ChatRunInfo,
    ChatShareGrantInfo,
    ForkConfirmation,
    ForkedConversationInfo,
    ForkPreviewInfo,
    QueryApprovalDecision,
    SharedConversationDetail,
    StandaloneClarificationCreate,
    StandaloneConversationCreate,
    StandaloneConversationDetail,
    StandaloneConversationPatch,
    StandaloneRunCreate,
)
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.artifacts import table_to_csv
from gateway.standalone_chat.config import enterprise_chat_feature_flags, standalone_chat_enabled
from gateway.standalone_chat.object_storage import chat_object_storage, runtime_object_key
from gateway.standalone_chat.projects import (
    authorize_chat_project,
    cached_starter_questions,
    evaluate_project_readiness,
    resolve_default_project,
)
from gateway.standalone_chat.query_approvals import decide_query_proposal
from gateway.store import standalone_chat as chat_store

from .deps import StoreD

router = APIRouter(prefix="/api/chat")

_ARCHIVE_CSP = (
    "default-src 'none'; img-src data: blob:; media-src data: blob:; "
    "style-src 'unsafe-inline'; font-src data:; "
    "script-src 'unsafe-inline' 'unsafe-eval' blob:; worker-src blob:; "
    "connect-src 'none'; frame-src 'none'; object-src 'none'; "
    "form-action 'none'; base-uri 'none'"
)


def _sanitize_runtime_archive_html(value: str) -> str:
    """Preserve the static notebook bundle while removing navigation escapes."""
    sanitized = re.sub(
        r"<meta\b[^>]*http-equiv\s*=\s*(['\"]?)refresh\1[^>]*>",
        "",
        value,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"<base\b[^>]*>", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(
        r"<meta\b[^>]*http-equiv\s*=\s*(['\"]?)content-security-policy\1[^>]*>",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )
    csp_meta = f'<meta http-equiv="Content-Security-Policy" content="{_ARCHIVE_CSP}">'
    with_csp, replacements = re.subn(
        r"<head(\s[^>]*)?>",
        lambda match: f"{match.group(0)}{csp_meta}",
        sanitized,
        count=1,
        flags=re.IGNORECASE,
    )
    if replacements:
        return with_csp
    return re.sub(
        r"<html(\s[^>]*)?>",
        lambda match: f"{match.group(0)}<head>{csp_meta}</head>",
        sanitized,
        count=1,
        flags=re.IGNORECASE,
    )


async def _runtime_result_rows(result: GatewayStructuredQueryResult) -> list[dict]:
    if result.storage_kind != "object":
        return list(result.rows_json or [])
    if not result.object_key:
        raise HTTPException(status_code=422, detail="Artifact result payload is unavailable")
    data = await chat_object_storage().get_bytes(result.object_key, max_bytes=10 * 1024 * 1024)
    if result.content_hash and hashlib.sha256(data).hexdigest() != result.content_hash:
        raise HTTPException(status_code=500, detail="Artifact result failed integrity validation")
    try:
        rows = json.loads(data)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Artifact result payload is invalid") from exc
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise HTTPException(status_code=500, detail="Artifact result payload is invalid")
    return rows


class DefaultProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1, max_length=200)


class RuntimeArtifactCreate(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    kind: str = Field(..., pattern=r"^(table|chart|report)$")
    result_id: str = Field(..., min_length=1, max_length=200)
    content_base64: str = Field(..., min_length=1, max_length=14 * 1024 * 1024)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    exclusions: list[str] = Field(default_factory=list, max_length=100)
    caveats: list[str] = Field(default_factory=list, max_length=100)
    code_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class RuntimeArchiveCreate(BaseModel):
    source_base64: str = Field(..., min_length=1, max_length=3 * 1024 * 1024)
    html_base64: str = Field(..., min_length=1, max_length=14 * 1024 * 1024)
    manifest_base64: str = Field(..., min_length=1, max_length=3 * 1024 * 1024)


def _require_enabled() -> None:
    if not standalone_chat_enabled():
        raise HTTPException(status_code=404, detail="Standalone chat is not enabled")


def _require_enterprise_feature(name: str) -> None:
    if not getattr(enterprise_chat_feature_flags(), name):
        raise HTTPException(status_code=404, detail="Chat capability is not enabled")


def _is_admin(role: str) -> bool:
    return role in {"admin", "org:admin"}


async def _readiness_or_error(
    store: StoreD,
    project_id: str,
    *,
    branch_override: str | None = None,
):
    project = await authorize_chat_project(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        project_id=project_id,
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    readiness = await evaluate_project_readiness(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        project=project,
        branch_override=branch_override,
    )
    return project, readiness


def _unready_detail(readiness, *, admin: bool) -> dict[str, str | bool]:
    return {
        "code": readiness.code,
        "message": (
            readiness.message
            if admin
            else "This project is not ready for data chat. Ask an administrator to finish setup."
        ),
        "setup_cta": admin,
    }


@router.get("/bootstrap", response_model=ChatBootstrapResponse, dependencies=[RequireScope("read")])
async def bootstrap_chat(store: StoreD, role: OrgRole):
    feature_flags = enterprise_chat_feature_flags()
    exposed_flags = {
        "query_approval": feature_flags.query_approval,
        "structured_results": feature_flags.structured_results,
        "organization_sharing": feature_flags.organization_sharing,
        "forking": feature_flags.forking,
        "size_router": feature_flags.size_router,
        "size_router_shadow": feature_flags.size_router_shadow,
        "notebook_analysis": feature_flags.notebook_analysis,
        "runtime_results": feature_flags.runtime_results,
        "runtime_artifacts": feature_flags.runtime_artifacts,
        "dataset_refs": feature_flags.dataset_refs,
    }
    if not standalone_chat_enabled():
        return ChatBootstrapResponse(
            enabled=False,
            projects=[],
            selected_project_id=None,
            is_admin=_is_admin(role),
            starter_questions=[],
            enterprise_features=exposed_flags,
        )
    org_id = store._require_org_id()
    user_id = store.user_id or "local"
    candidate_projects = list(
        (
            await store.session.execute(
                select(GatewayWorkspaceProject)
                .where(
                    GatewayWorkspaceProject.org_id == org_id,
                    GatewayWorkspaceProject.status == "active",
                )
                .order_by(GatewayWorkspaceProject.display_name)
            )
        ).scalars()
    )
    projects = [
        project
        for project in candidate_projects
        if await authorize_chat_project(
            store.session,
            org_id=org_id,
            user_id=user_id,
            project_id=project.id,
        )
        is not None
    ]
    readiness_by_project = {
        project.id: await evaluate_project_readiness(
            store.session,
            org_id=org_id,
            user_id=user_id,
            project=project,
        )
        for project in projects
    }
    ready_ids = {project_id for project_id, readiness in readiness_by_project.items() if readiness.ready}
    selected_id = await resolve_default_project(
        store.session,
        org_id=org_id,
        user_id=user_id,
        ready_project_ids=ready_ids,
        projects=projects,
    )
    starters: list[str] = []
    if selected_id:
        selected = next(project for project in projects if project.id == selected_id)
        starters = await cached_starter_questions(
            store.session,
            org_id=org_id,
            project=selected,
            readiness=readiness_by_project[selected_id],
        )
    preference = (
        await store.session.execute(
            select(GatewayChatUserPreference).where(
                GatewayChatUserPreference.org_id == org_id,
                GatewayChatUserPreference.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    return ChatBootstrapResponse(
        enabled=True,
        projects=[
            {
                "id": project.id,
                "name": project.name,
                "display_name": project.display_name,
                "connection_name": project.connection_name,
                "default_branch": readiness_by_project[project.id].branch or project.default_branch or "main",
                "ready": readiness_by_project[project.id].ready,
                "readiness_message": (
                    readiness_by_project[project.id].message
                    if readiness_by_project[project.id].ready
                    else _unready_detail(
                        readiness_by_project[project.id],
                        admin=_is_admin(role),
                    )["message"]
                ),
            }
            for project in projects
        ],
        selected_project_id=selected_id,
        is_admin=_is_admin(role),
        starter_questions=starters,
        default_per_query_budget_usd=(preference.default_per_query_budget_usd if preference else 0.25),
        default_chat_budget_usd=(preference.default_chat_budget_usd if preference else 1.0),
        enterprise_features=exposed_flags,
    )


@router.get(
    "/projects/{project_id}/readiness",
    dependencies=[RequireScope("read")],
)
async def project_readiness(project_id: str, store: StoreD, role: OrgRole):
    _require_enabled()
    project, readiness = await _readiness_or_error(store, project_id)
    starters = (
        await cached_starter_questions(
            store.session,
            org_id=store._require_org_id(),
            project=project,
            readiness=readiness,
        )
        if readiness.ready
        else []
    )
    return {
        "project_id": project.id,
        "ready": readiness.ready,
        "code": readiness.code,
        "message": _unready_detail(readiness, admin=_is_admin(role))["message"],
        "setup_cta": not readiness.ready and _is_admin(role),
        "branch": readiness.branch,
        "connection_name": readiness.connection_name,
        "starter_questions": starters,
    }


@router.put("/default-project", status_code=204, dependencies=[RequireScope("write")])
async def update_default_project(body: DefaultProjectUpdate, store: StoreD):
    _require_enabled()
    project, _ = await _readiness_or_error(store, body.project_id)
    org_id = store._require_org_id()
    user_id = store.user_id or "local"
    preference = (
        await store.session.execute(
            select(GatewayChatUserPreference).where(
                GatewayChatUserPreference.org_id == org_id,
                GatewayChatUserPreference.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if preference:
        preference.default_chat_project_id = project.id
    else:
        store.session.add(
            GatewayChatUserPreference(
                org_id=org_id,
                user_id=user_id,
                default_chat_project_id=project.id,
            )
        )
    await store.session.commit()
    return Response(status_code=204)


@router.get("/conversations", dependencies=[RequireScope("read")])
async def list_conversations(store: StoreD):
    _require_enabled()
    conversations = await chat_store.list_conversations(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
    )
    return {"conversations": conversations}


@router.post(
    "/conversations",
    status_code=201,
    response_model=StandaloneConversationDetail,
    dependencies=[RequireScope("write")],
)
async def create_conversation(body: StandaloneConversationCreate, store: StoreD, role: OrgRole):
    _require_enabled()
    project, readiness = await _readiness_or_error(store, body.project_id)
    if not readiness.ready or not readiness.branch:
        raise HTTPException(
            status_code=409,
            detail=_unready_detail(readiness, admin=_is_admin(role)),
        )
    conversation, _ = await chat_store.create_conversation_with_run(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        project=project,
        branch=readiness.branch,
        message=body.message,
        commit_sha=branch_head_sha(project.id, readiness.branch),
        per_query_budget_usd=body.per_query_budget_usd,
        chat_budget_usd=body.chat_budget_usd,
    )
    detail = await chat_store.get_conversation_detail(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        conversation_id=conversation.id,
    )
    assert detail is not None
    return detail


@router.get(
    "/conversations/{conversation_id}",
    response_model=StandaloneConversationDetail,
    dependencies=[RequireScope("read")],
)
async def get_conversation(conversation_id: str, store: StoreD):
    _require_enabled()
    detail = await chat_store.get_conversation_detail(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        conversation_id=conversation_id,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return detail


@router.patch(
    "/conversations/{conversation_id}",
    dependencies=[RequireScope("write")],
)
async def rename_conversation(
    conversation_id: str,
    body: StandaloneConversationPatch,
    store: StoreD,
):
    _require_enabled()
    changed = await chat_store.rename_conversation(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        conversation_id=conversation_id,
        title=body.title,
    )
    if not changed:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"id": conversation_id, "title": body.title}


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    dependencies=[RequireScope("write")],
)
async def archive_conversation(conversation_id: str, store: StoreD):
    _require_enabled()
    archived = await chat_store.archive_conversation(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        conversation_id=conversation_id,
    )
    if not archived:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return Response(status_code=204)


@router.post(
    "/conversations/{conversation_id}/share",
    status_code=201,
    response_model=ChatShareGrantInfo,
    dependencies=[RequireScope("write")],
)
async def share_conversation(
    conversation_id: str,
    store: StoreD,
    response: Response,
):
    _require_enabled()
    _require_enterprise_feature("organization_sharing")
    result = await chat_store.create_share_grant(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        conversation_id=conversation_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    grant, token = result
    response.headers["Cache-Control"] = "private, no-store"
    return ChatShareGrantInfo(token=token, created_at=grant.created_at)


@router.delete(
    "/conversations/{conversation_id}/share",
    status_code=204,
    dependencies=[RequireScope("write")],
)
async def revoke_conversation_share(conversation_id: str, store: StoreD):
    _require_enabled()
    _require_enterprise_feature("organization_sharing")
    found = await chat_store.revoke_share_grants(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        conversation_id=conversation_id,
    )
    if not found:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return Response(status_code=204)


@router.get(
    "/shared/{token}",
    response_model=SharedConversationDetail,
    dependencies=[RequireScope("read")],
)
async def get_shared_conversation(
    token: str,
    store: StoreD,
    response: Response,
):
    _require_enabled()
    _require_enterprise_feature("organization_sharing")
    detail = await chat_store.get_shared_conversation(
        store.session,
        org_id=store._require_org_id(),
        token=token,
    )
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail="Shared conversation not found",
            headers={"Cache-Control": "private, no-store"},
        )
    response.headers["Cache-Control"] = "private, no-store"
    return detail


@router.post(
    "/shared/{token}/fork",
    status_code=201,
    response_model=ForkedConversationInfo,
    dependencies=[RequireScope("write")],
)
async def fork_shared_conversation(token: str, body: ForkConfirmation, store: StoreD):
    _require_enabled()
    _require_enterprise_feature("forking")
    try:
        conversation = await chat_store.fork_shared_conversation(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            token=token,
            per_query_budget_usd=body.per_query_budget_usd,
            chat_budget_usd=body.chat_budget_usd,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if conversation is None:
        raise HTTPException(status_code=404, detail="Shared conversation not found")
    return ForkedConversationInfo(id=conversation.id)


@router.get(
    "/shared/{token}/fork-preview",
    response_model=ForkPreviewInfo,
    dependencies=[RequireScope("read")],
)
async def preview_shared_conversation_fork(token: str, store: StoreD):
    _require_enabled()
    _require_enterprise_feature("forking")
    preview = await chat_store.get_fork_preview(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        token=token,
    )
    if preview is None:
        raise HTTPException(status_code=404, detail="Shared conversation not found")
    return preview


@router.post(
    "/query-proposals/{proposal_id}/decision",
    response_model=ChatRunInfo,
    dependencies=[RequireScope("write")],
)
async def decide_query(
    proposal_id: str,
    body: QueryApprovalDecision,
    store: StoreD,
):
    _require_enabled()
    _require_enterprise_feature("query_approval")
    try:
        run = await decide_query_proposal(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            proposal_id=proposal_id,
            decision=body.decision,
            approval_scope=body.scope,
            per_query_budget_usd=body.per_query_budget_usd,
            chat_budget_usd=body.chat_budget_usd,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="Query proposal not found")
    return chat_store._run_info(run)


@router.post(
    "/conversations/{conversation_id}/runs",
    status_code=201,
    response_model=ChatRunInfo,
    dependencies=[RequireScope("write")],
)
async def create_run(
    conversation_id: str,
    body: StandaloneRunCreate,
    store: StoreD,
    role: OrgRole,
):
    _require_enabled()
    conversation = (
        await store.session.execute(
            select(GatewayChatConversation).where(
                GatewayChatConversation.id == conversation_id,
                GatewayChatConversation.org_id == store._require_org_id(),
                GatewayChatConversation.user_id == (store.user_id or "local"),
                GatewayChatConversation.surface == "standalone",
                GatewayChatConversation.status == "active",
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _, readiness = await _readiness_or_error(
        store,
        conversation.project_id or "",
        branch_override=conversation.branch,
    )
    if not readiness.ready:
        raise HTTPException(
            status_code=409,
            detail=_unready_detail(readiness, admin=_is_admin(role)),
        )
    report_reference = None
    if body.report_reference is not None:
        from gateway.store.chat_reports import verified_report_reference

        report_reference = await verified_report_reference(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            conversation_id=conversation_id,
            report_id=body.report_reference.report_id,
            version_id=body.report_reference.version_id,
        )
        if report_reference is None:
            raise HTTPException(status_code=404, detail="Report reference not found")
    try:
        run = await chat_store.create_run(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            conversation_id=conversation_id,
            message=body.message,
            message_metadata={"report_reference": report_reference} if report_reference else None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    return chat_store._run_info(run)


@router.get("/runs/{run_id}/events", dependencies=[RequireScope("read")])
async def stream_run_events(
    run_id: str,
    store: StoreD,
    after: Annotated[int, Query(ge=0)] = 0,
):
    _require_enabled()
    initial = await chat_store.list_run_events(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        run_id=run_id,
        after=after,
    )
    if initial is None:
        raise HTTPException(status_code=404, detail="Run not found")
    org_id = store._require_org_id()
    user_id = store.user_id or "local"

    async def generate():
        cursor = after
        keepalive_ticks = 0
        while True:
            factory = get_session_factory()
            async with factory() as session:
                events = await chat_store.list_run_events(
                    session,
                    org_id=org_id,
                    user_id=user_id,
                    run_id=run_id,
                    after=cursor,
                )
                if events is None:
                    return
                for event in events:
                    cursor = event.sequence
                    payload = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
                    yield f"id: {event.sequence}\nevent: {event.type}\ndata: {payload}\n\n"
                run_status = (
                    await session.execute(
                        select(GatewayChatRun.status).where(
                            GatewayChatRun.id == run_id,
                            GatewayChatRun.org_id == org_id,
                            GatewayChatRun.user_id == user_id,
                        )
                    )
                ).scalar_one_or_none()
            if (
                run_status
                in {
                    "completed",
                    "failed",
                    "cancelled",
                    "waiting_for_user",
                    "waiting_for_query_approval",
                }
                and not events
            ):
                return
            keepalive_ticks += 1
            if keepalive_ticks >= 15:
                keepalive_ticks = 0
                yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/cancel", response_model=ChatRunInfo, dependencies=[RequireScope("write")])
async def cancel_run(run_id: str, store: StoreD):
    _require_enabled()
    run = await chat_store.request_cancellation(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        run_id=run_id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.execution_session_id and run.status == "running":
        try:
            from gateway.standalone_chat.execution import cancel_execution_session

            await cancel_execution_session(store.session, run)
        except Exception:
            pass
    active_queries = list(
        (
            await store.session.execute(
                select(GatewayGovernedQueryExecution).where(
                    GatewayGovernedQueryExecution.org_id == store._require_org_id(),
                    GatewayGovernedQueryExecution.user_id == (store.user_id or "local"),
                    GatewayGovernedQueryExecution.run_id == run.id,
                    GatewayGovernedQueryExecution.status.in_(("estimating", "running")),
                )
            )
        ).scalars()
    )
    for execution in active_queries:
        execution.status = "cancelled"
        execution.public_error_code = "query_cancelled"
        execution.terminal_at = datetime.now(UTC)
    if active_queries:
        await store.session.commit()
    for execution in active_queries:
        await governed_query_executor.cancel(execution.id)
        try:
            from gateway.governance.runtime_datasets import runtime_dataset_executor

            await runtime_dataset_executor.cancel(execution.id)
        except Exception:
            pass
    return chat_store._run_info(run)


@router.post(
    "/runs/{run_id}/clarification",
    response_model=ChatRunInfo,
    dependencies=[RequireScope("write")],
)
async def clarify_run(run_id: str, body: StandaloneClarificationCreate, store: StoreD):
    _require_enabled()
    try:
        run = await chat_store.submit_clarification(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            run_id=run_id,
            message=body.message,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return chat_store._run_info(run)


@router.post(
    "/runs/{run_id}/retry",
    status_code=201,
    response_model=ChatRunInfo,
    dependencies=[RequireScope("write")],
)
async def retry_run(run_id: str, store: StoreD, role: OrgRole):
    _require_enabled()
    failed = (
        await store.session.execute(
            select(GatewayChatRun)
            .join(
                GatewayChatConversation,
                GatewayChatConversation.id == GatewayChatRun.conversation_id,
            )
            .where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.org_id == store._require_org_id(),
                GatewayChatRun.user_id == (store.user_id or "local"),
                GatewayChatConversation.surface == "standalone",
                GatewayChatConversation.status == "active",
            )
        )
    ).scalar_one_or_none()
    if failed is None:
        raise HTTPException(status_code=404, detail="Run not found")
    conversation_branch = await store.session.scalar(
        select(GatewayChatConversation.branch).where(
            GatewayChatConversation.id == failed.conversation_id,
            GatewayChatConversation.org_id == store._require_org_id(),
            GatewayChatConversation.user_id == (store.user_id or "local"),
            GatewayChatConversation.surface == "standalone",
            GatewayChatConversation.status == "active",
        )
    )
    _, readiness = await _readiness_or_error(
        store,
        failed.project_id,
        branch_override=conversation_branch,
    )
    if not readiness.ready:
        raise HTTPException(
            status_code=409,
            detail=_unready_detail(readiness, admin=_is_admin(role)),
        )
    try:
        run = await chat_store.retry_run(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            run_id=run_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return chat_store._run_info(run)


@router.post("/runtime-artifacts", status_code=201, dependencies=[RequireScope("query")])
async def publish_runtime_artifact(body: RuntimeArtifactCreate, store: StoreD, request: Request):
    if not enterprise_chat_feature_flags().runtime_artifacts:
        raise HTTPException(status_code=404, detail="Runtime artifact publication is not enabled")
    claims = getattr(request.state, "_jwt_claims", {}) or {}
    identity = claims.get("execution_identity")
    if not isinstance(identity, str) or not identity.startswith("chat:"):
        raise HTTPException(status_code=403, detail="Runtime artifact publication requires a chat run")
    run_id = identity.removeprefix("chat:")
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
        raise HTTPException(status_code=403, detail="Runtime artifact scope mismatch")
    source_result = (
        await store.session.execute(
            select(GatewayStructuredQueryResult).where(
                GatewayStructuredQueryResult.id == body.result_id,
                GatewayStructuredQueryResult.org_id == run.org_id,
                GatewayStructuredQueryResult.owner_user_id == run.user_id,
                GatewayStructuredQueryResult.conversation_id == run.conversation_id,
                GatewayStructuredQueryResult.run_id == run.id,
            )
        )
    ).scalar_one_or_none()
    if source_result is None:
        raise HTTPException(status_code=422, detail="Artifact result_id must belong to the active run")
    if source_result.code_hash and source_result.code_hash != body.code_hash:
        raise HTTPException(status_code=422, detail="Artifact code hash does not match its derived result")
    try:
        content = base64.b64decode(body.content_base64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Artifact content is not valid base64") from exc
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Artifact must be non-empty and no larger than 10 MiB")

    payload: dict = {
        "kind": body.kind,
        "filename": body.filename,
        "assumptions": body.assumptions,
        "exclusions": body.exclusions,
        "caveats": body.caveats,
        "provenance": {
            "result_id": source_result.id,
            "source_result_ids": source_result.source_result_ids_json,
            "code_hash": body.code_hash,
        },
    }
    if body.kind == "table":
        try:
            text_value = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text_value))
            rows = list(reader)
        except (UnicodeDecodeError, csv.Error) as exc:
            raise HTTPException(status_code=422, detail="Table artifact must be valid UTF-8 CSV") from exc
        if not reader.fieldnames or len(rows) > 100_000:
            raise HTTPException(status_code=422, detail="Table artifact must have headers and at most 100,000 rows")
        payload["mime_type"] = "text/csv"
        payload["snapshot"] = {
            "columns": [{"name": name, "type": "string"} for name in reader.fieldnames],
            "rows": rows,
            "saved_row_count": len(rows),
            "completeness": source_result.result_completeness,
            "truncated": source_result.result_completeness != "complete",
        }
    elif body.kind == "chart":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(status_code=422, detail="Chart artifact content does not match PNG")
        source_rows = await _runtime_result_rows(source_result)
        payload["mime_type"] = "image/png"
        payload["binary_base64"] = body.content_base64
        payload["snapshot"] = {
            "runtime_png": True,
            "spec": {},
            "rows": list(source_result.preview_rows_json or []),
            "source": {
                "columns": source_result.columns_json,
                "rows": source_rows,
                "saved_row_count": source_result.saved_row_count,
                "truncated": source_result.result_completeness != "complete",
            },
            "truncated": source_result.result_completeness != "complete",
        }
    else:
        try:
            html_value = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="Report artifact must be valid UTF-8 HTML") from exc
        payload["mime_type"] = "text/html"
        payload["snapshot"] = {"html": html_value}

    try:
        artifact = await chat_store.persist_artifact(store.session, run=run, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await chat_store.append_event(
        store.session,
        run_id=run.id,
        event_type="artifact_created",
        payload={"artifact_id": artifact.id, "kind": artifact.kind, "filename": artifact.filename},
    )
    return {
        "artifact_id": artifact.id,
        "filename": artifact.filename,
        "kind": artifact.kind,
        "byte_size": artifact.byte_size or len(content),
    }


@router.post("/runtime-archives", status_code=201, dependencies=[RequireScope("query")])
async def publish_runtime_archive(body: RuntimeArchiveCreate, store: StoreD, request: Request):
    if not enterprise_chat_feature_flags().runtime_artifacts:
        raise HTTPException(status_code=404, detail="Runtime notebook archives are not enabled")
    claims = getattr(request.state, "_jwt_claims", {}) or {}
    identity = claims.get("execution_identity")
    if not isinstance(identity, str) or not identity.startswith("chat:"):
        raise HTTPException(status_code=403, detail="Runtime archive publication requires a chat run")
    run_id = identity.removeprefix("chat:")
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
        raise HTTPException(status_code=403, detail="Runtime archive scope mismatch")
    try:
        source = base64.b64decode(body.source_base64, validate=True)
        html = base64.b64decode(body.html_base64, validate=True)
        manifest = base64.b64decode(body.manifest_base64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Runtime archive payload is not valid base64") from exc
    if len(source) > 2 * 1024 * 1024 or len(html) > 10 * 1024 * 1024 or len(manifest) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Runtime archive payload exceeds its bounded size")
    try:
        source.decode("utf-8")
        html_text = html.decode("utf-8")
        manifest_value = json.loads(manifest)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Runtime archive payload is invalid") from exc
    if not isinstance(manifest_value, dict) or "<html" not in html_text[:10_000].lower():
        raise HTTPException(status_code=422, detail="Runtime archive payload is invalid")
    html_text = _sanitize_runtime_archive_html(html_text)
    html = html_text.encode("utf-8")
    archive_hashes = tuple(hashlib.sha256(value).hexdigest() for value in (source, html, manifest))
    existing = (
        await store.session.execute(
            select(GatewayChatRuntimeArchive).where(GatewayChatRuntimeArchive.run_id == run.id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if archive_hashes != (existing.source_hash, existing.html_hash, existing.manifest_hash):
            raise HTTPException(status_code=409, detail="Runtime archive is already bound to different content")
        return {"archive_id": existing.id, "run_id": run.id}
    archive_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"signalpilot-runtime-archive:{run.id}"))
    storage = chat_object_storage()
    objects = []
    try:
        for _label, filename, data, content_type in (
            ("source", "analysis.py", source, "text/x-python"),
            ("html", "analysis.html", html, "text/html"),
            ("manifest", "manifest.json", manifest, "application/json"),
        ):
            key = runtime_object_key(
                org_id=run.org_id,
                conversation_id=run.conversation_id,
                run_id=run.id,
                category="notebook-archive",
                object_id=archive_id,
                filename=filename,
            )
            objects.append(await storage.put_bytes(key=key, data=data, content_type=content_type))
    except Exception:
        for item in reversed(objects):
            with suppress(Exception):
                await storage.delete(item.key)
        raise
    archive = GatewayChatRuntimeArchive(
        id=archive_id,
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        source_object_key=objects[0].key,
        html_object_key=objects[1].key,
        manifest_object_key=objects[2].key,
        source_hash=objects[0].content_hash,
        html_hash=objects[1].content_hash,
        manifest_hash=objects[2].content_hash,
    )
    store.session.add(archive)
    run.runtime_archive_id = archive.id
    try:
        await store.session.commit()
    except IntegrityError as exc:
        await store.session.rollback()
        winner = (
            await store.session.execute(
                select(GatewayChatRuntimeArchive).where(GatewayChatRuntimeArchive.run_id == run.id)
            )
        ).scalar_one_or_none()
        if winner is not None and archive_hashes == (
            winner.source_hash,
            winner.html_hash,
            winner.manifest_hash,
        ):
            return {"archive_id": winner.id, "run_id": run.id}
        for item in reversed(objects):
            with suppress(Exception):
                await storage.delete(item.key)
        raise HTTPException(status_code=409, detail="Runtime archive identity conflict") from exc
    except Exception:
        await store.session.rollback()
        for item in reversed(objects):
            with suppress(Exception):
                await storage.delete(item.key)
        raise
    await chat_store.append_event(
        store.session,
        run_id=run.id,
        event_type="archive_completed",
        payload={"archive_id": archive.id},
    )
    return {"archive_id": archive.id, "run_id": run.id}


@router.get("/runs/{run_id}/notebook", dependencies=[RequireScope("read")])
async def get_runtime_notebook(run_id: str, store: StoreD):
    archive = (
        await store.session.execute(
            select(GatewayChatRuntimeArchive)
            .join(GatewayChatRun, GatewayChatRun.id == GatewayChatRuntimeArchive.run_id)
            .where(
                GatewayChatRuntimeArchive.run_id == run_id,
                GatewayChatRuntimeArchive.org_id == store._require_org_id(),
                GatewayChatRuntimeArchive.user_id == (store.user_id or "local"),
                GatewayChatRun.conversation_id == GatewayChatRuntimeArchive.conversation_id,
            )
        )
    ).scalar_one_or_none()
    if archive is None:
        raise HTTPException(status_code=404, detail="Runtime notebook archive not found")
    content = await chat_object_storage().get_bytes(archive.html_object_key, max_bytes=10 * 1024 * 1024)
    if hashlib.sha256(content).hexdigest() != archive.html_hash:
        raise HTTPException(status_code=500, detail="Runtime notebook archive failed integrity validation")
    return Response(
        content=content,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": _ARCHIVE_CSP,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/artifacts/{artifact_id}/download", dependencies=[RequireScope("read")])
async def download_artifact(
    artifact_id: str,
    store: StoreD,
    format: Annotated[str, Query(pattern=r"^(csv|png|html)$")],
):
    _require_enabled()
    artifact = await chat_store.get_artifact(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        artifact_id=artifact_id,
    )
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail="Artifact not found",
            headers={"Cache-Control": "private, no-store"},
        )
    return await _artifact_download_response(artifact, format)


@router.get(
    "/shared/{token}/artifacts/{artifact_id}/download",
    dependencies=[RequireScope("read")],
)
async def download_shared_artifact(
    token: str,
    artifact_id: str,
    store: StoreD,
    format: Annotated[str, Query(pattern=r"^(csv|png|html)$")],
):
    _require_enabled()
    _require_enterprise_feature("organization_sharing")
    artifact = await chat_store.get_shared_artifact(
        store.session,
        org_id=store._require_org_id(),
        token=token,
        artifact_id=artifact_id,
    )
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail="Artifact not found",
            headers={"Cache-Control": "private, no-store"},
        )
    return await _artifact_download_response(artifact, format)


async def _artifact_download_response(
    artifact: GatewayChatArtifact,
    format: str,
) -> Response:
    allowed = {
        "table": {"csv"},
        "chart": {"png", "csv"},
        "report": {"html"},
    }[artifact.kind]
    if format not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported artifact format")
    if format == "csv" and artifact.storage_kind == "object":
        key = artifact.source_object_key if artifact.kind == "chart" else artifact.object_key
        if not key:
            raise HTTPException(status_code=422, detail="Artifact has no downloadable source rows")
        content = await chat_object_storage().get_bytes(key, max_bytes=10 * 1024 * 1024)
        if (
            key == artifact.object_key
            and artifact.content_hash
            and hashlib.sha256(content).hexdigest() != artifact.content_hash
        ):
            raise HTTPException(status_code=500, detail="Artifact failed integrity validation")
        media_type = "text/csv; charset=utf-8"
    elif format == "csv":
        if artifact.kind == "table" and artifact.binary_data:
            content = artifact.binary_data
            media_type = "text/csv; charset=utf-8"
        else:
            snapshot = artifact.snapshot_json.get("source") if artifact.kind == "chart" else artifact.snapshot_json
            if artifact.kind == "chart" and not isinstance(snapshot, dict):
                snapshot = artifact.snapshot_json
            if not isinstance(snapshot, dict):
                raise HTTPException(status_code=422, detail="Artifact has no downloadable source rows")
            content = table_to_csv(snapshot)
            media_type = "text/csv; charset=utf-8"
    elif format == "png":
        if artifact.storage_kind == "object" and artifact.object_key:
            content = await chat_object_storage().get_bytes(
                artifact.object_key,
                max_bytes=10 * 1024 * 1024,
            )
            if artifact.content_hash and hashlib.sha256(content).hexdigest() != artifact.content_hash:
                raise HTTPException(status_code=500, detail="Artifact failed integrity validation")
        elif artifact.binary_data:
            content = artifact.binary_data
        else:
            raise HTTPException(status_code=422, detail="Artifact has no PNG representation")
        media_type = "image/png"
    else:
        if artifact.storage_kind == "object" and artifact.object_key:
            content = await chat_object_storage().get_bytes(
                artifact.object_key,
                max_bytes=10 * 1024 * 1024,
            )
            if artifact.content_hash and hashlib.sha256(content).hexdigest() != artifact.content_hash:
                raise HTTPException(status_code=500, detail="Artifact failed integrity validation")
        else:
            content = str(artifact.snapshot_json.get("html") or "").encode("utf-8")
        media_type = "text/html; charset=utf-8"
    base = artifact.filename.rsplit(".", 1)[0]
    filename = f"{base}.{format}"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
