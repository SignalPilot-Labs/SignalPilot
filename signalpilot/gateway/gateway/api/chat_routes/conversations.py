"""Conversation lifecycle, sharing, and fork routes."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response

from gateway.auth import OrgRole
from gateway.git.repos import branch_head_sha
from gateway.models.standalone_chat import (
    ChatShareGrantInfo,
    ForkConfirmation,
    ForkedConversationInfo,
    ForkPreviewInfo,
    SharedConversationDetail,
    StandaloneConversationCreate,
    StandaloneConversationDetail,
    StandaloneConversationEffortUpdate,
    StandaloneConversationModelUpdate,
    StandaloneConversationPatch,
)
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.notebook_resource import (
    get_conversation_notebook as resolve_conversation_notebook,
)
from gateway.standalone_chat.notebook_resource import (
    get_conversation_notebooks as resolve_conversation_notebooks,
)
from gateway.store import standalone_chat as chat_store

from ..deps import StoreD
from .common import is_admin as _is_admin
from .common import readiness_or_error as _readiness_or_error
from .common import require_enabled as _require_enabled
from .common import require_enterprise_feature as _require_enterprise_feature
from .common import unready_detail as _unready_detail

router = APIRouter()


@router.get("/conversations", dependencies=[RequireScope("read")])
async def list_conversations(
    store: StoreD,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    _require_enabled()
    conversations = await chat_store.list_conversations(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        limit=limit,
        offset=offset,
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
    from gateway.standalone_chat.demo_limits import enforce_demo_request_limit

    await enforce_demo_request_limit(store.session, org_id=store._require_org_id())
    project, readiness = await _readiness_or_error(store, body.project_id)
    if not readiness.ready or not readiness.branch:
        raise HTTPException(
            status_code=409,
            detail=_unready_detail(readiness, admin=_is_admin(role)),
        )
    report_reference = None
    if body.report_reference is not None:
        from gateway.store.chat_reports import verified_project_report_reference

        report_reference = await verified_project_report_reference(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            project_id=project.id,
            report_id=body.report_reference.report_id,
        )
        if report_reference is None:
            raise HTTPException(status_code=404, detail="Report reference not found")
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
        model=body.model,
        effort=body.effort,
        message_metadata={"report_reference": report_reference} if report_reference else None,
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


@router.get(
    "/conversations/{conversation_id}/notebook",
    dependencies=[RequireScope("read")],
)
async def get_conversation_notebook(conversation_id: str, store: StoreD, request: Request):
    """Return the conversation's notebook: live attach ids plus saved document.

    This is the single source of truth for the chat notebook panel. The
    client does not derive notebook state from run events.
    """
    _require_enabled()
    conversation = await chat_store.get_owned_conversation(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await resolve_conversation_notebook(
        store.session,
        conversation=conversation,
        http_client=request.app.state.notebook_proxy_client,
    )


@router.get(
    "/conversations/{conversation_id}/notebooks",
    dependencies=[RequireScope("read")],
)
async def get_conversation_notebooks(conversation_id: str, store: StoreD, request: Request):
    """Return every notebook of the conversation, "analysis" first."""
    _require_enabled()
    conversation = await chat_store.get_owned_conversation(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    notebooks = await resolve_conversation_notebooks(
        store.session,
        conversation=conversation,
        http_client=request.app.state.notebook_proxy_client,
    )
    return {"notebooks": notebooks}


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


@router.put(
    "/conversations/{conversation_id}/model",
    dependencies=[RequireScope("write")],
)
async def update_conversation_model(
    conversation_id: str,
    body: StandaloneConversationModelUpdate,
    store: StoreD,
):
    _require_enabled()
    changed = await chat_store.update_conversation_model(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        conversation_id=conversation_id,
        model=body.model,
    )
    if not changed:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"id": conversation_id, "model": body.model}


@router.put(
    "/conversations/{conversation_id}/effort",
    dependencies=[RequireScope("write")],
)
async def update_conversation_effort(
    conversation_id: str,
    body: StandaloneConversationEffortUpdate,
    store: StoreD,
):
    _require_enabled()
    changed = await chat_store.update_conversation_effort(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        conversation_id=conversation_id,
        effort=body.effort,
    )
    if not changed:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"id": conversation_id, "effort": body.effort}


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
