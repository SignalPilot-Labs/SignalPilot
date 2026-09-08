"""POST /api/chat/conversations/{id}/files/{file_id}/publish-dashboard."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from gateway.auth import OrgRole
from gateway.auth.user import is_org_admin_role
from gateway.dashboards import service
from gateway.dashboards.query import governed_executor
from gateway.dashboards.serializers import PublishDashboardRequest, dashboard_out, version_out
from gateway.dashboards.storage import dashboard_storage
from gateway.security.scope_guard import RequireScope
from gateway.store import standalone_chat as chat_store

from ..deps import StoreD
from .common import owned_conversation_or_404, require_enabled

router = APIRouter()


@router.post(
    "/conversations/{conversation_id}/files/{file_id}/publish-dashboard",
    status_code=201,
    dependencies=[RequireScope("query")],
)
async def publish_dashboard(
    conversation_id: str,
    file_id: str,
    body: PublishDashboardRequest,
    store: StoreD,
    role: OrgRole,
):
    """Publish a chat dashboard file to the team gallery as a new dashboard or version."""
    require_enabled()
    conversation = await owned_conversation_or_404(store, conversation_id)
    org_id = store._require_org_id()
    user_id = store.user_id or "local"
    file_row = await chat_store.get_conversation_file(
        store.session,
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation_id,
        file_id=file_id,
    )
    if file_row is None:
        raise HTTPException(status_code=404, detail="File not found")
    manifest = await chat_store.list_conversation_files(
        store.session,
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    admin = is_org_admin_role(role)
    try:
        dashboard, version = await service.publish(
            store.session,
            dashboard_storage(),
            governed_executor(),
            org_id=org_id,
            user_id=user_id,
            is_admin=admin,
            conversation_id=conversation_id,
            file_row=file_row,
            manifest=manifest,
            body=body,
            project_id=conversation.project_id,
        )
    except service.DashboardError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    return {
        "dashboard": dashboard_out(
            dashboard,
            viewer_user_id=user_id,
            is_admin=admin,
            current_version_no=version.version_no,
        ),
        "version": version_out(version),
    }
