"""Author-private standalone data-chat APIs and resumable event streaming."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from gateway.auth import OrgRole
from gateway.db.engine import get_session_factory
from gateway.db.models import (
    GatewayChatConversation,
    GatewayChatRun,
    GatewayChatUserPreference,
    GatewayWorkspaceProject,
)
from gateway.models.standalone_chat import (
    ChatBootstrapResponse,
    ChatRunInfo,
    StandaloneClarificationCreate,
    StandaloneConversationCreate,
    StandaloneConversationDetail,
    StandaloneConversationPatch,
    StandaloneRunCreate,
)
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.artifacts import table_to_csv
from gateway.standalone_chat.config import standalone_chat_enabled
from gateway.standalone_chat.projects import (
    authorize_chat_project,
    cached_starter_questions,
    evaluate_project_readiness,
    resolve_default_project,
)
from gateway.store import standalone_chat as chat_store

from .deps import StoreD

router = APIRouter(prefix="/api/chat")


class DefaultProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1, max_length=200)


def _require_enabled() -> None:
    if not standalone_chat_enabled():
        raise HTTPException(status_code=404, detail="Standalone chat is not enabled")


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
    if not standalone_chat_enabled():
        return ChatBootstrapResponse(
            enabled=False,
            projects=[],
            selected_project_id=None,
            is_admin=_is_admin(role),
            starter_questions=[],
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
    ready_ids = {
        project_id
        for project_id, readiness in readiness_by_project.items()
        if readiness.ready
    }
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
    return ChatBootstrapResponse(
        enabled=True,
        projects=[
            {
                "id": project.id,
                "name": project.name,
                "display_name": project.display_name,
                "connection_name": project.connection_name,
                "default_branch": readiness_by_project[project.id].branch
                or project.default_branch
                or "main",
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
    try:
        run = await chat_store.create_run(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            conversation_id=conversation_id,
            message=body.message,
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
            if run_status in {"completed", "failed", "cancelled", "waiting_for_user"} and not events:
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
        raise HTTPException(status_code=404, detail="Artifact not found")
    allowed = {
        "table": {"csv"},
        "chart": {"png", "csv"},
        "report": {"html"},
    }[artifact.kind]
    if format not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported artifact format")
    if format == "csv":
        snapshot = (
            artifact.snapshot_json.get("source")
            if artifact.kind == "chart"
            else artifact.snapshot_json
        )
        if artifact.kind == "chart" and not isinstance(snapshot, dict):
            snapshot = artifact.snapshot_json
        if not isinstance(snapshot, dict):
            raise HTTPException(status_code=422, detail="Artifact has no downloadable source rows")
        content = table_to_csv(snapshot)
        media_type = "text/csv; charset=utf-8"
    elif format == "png":
        if not artifact.binary_data:
            raise HTTPException(status_code=422, detail="Artifact has no PNG representation")
        content = artifact.binary_data
        media_type = "image/png"
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
