"""Chat bootstrap and project-selection routes."""

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from gateway.auth import OrgRole
from gateway.db.models import GatewayChatUserPreference, GatewayWorkspaceProject
from gateway.models.standalone_chat import ChatBootstrapResponse
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.config import enterprise_chat_feature_flags, standalone_chat_enabled
from gateway.standalone_chat.projects import (
    authorize_chat_project,
    cached_starter_questions,
    evaluate_project_readiness,
    resolve_default_project,
)

from ..deps import StoreD
from .common import is_admin as _is_admin
from .common import readiness_or_error as _readiness_or_error
from .common import require_enabled as _require_enabled
from .common import unready_detail as _unready_detail

router = APIRouter()


class DefaultProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1, max_length=200)


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
