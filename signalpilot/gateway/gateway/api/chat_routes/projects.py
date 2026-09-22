"""Chat bootstrap and project-selection routes."""

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from gateway.auth import OrgAdmin, OrgID, OrgRole
from gateway.auth.permissions import normalize_role, permissions_for
from gateway.billing.entitlements import OrgEntitlement, get_entitlement
from gateway.db.models import GatewayChatUserPreference, GatewayWorkspaceProject
from gateway.models.standalone_chat import ChatBootstrapResponse
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.config import (
    CHAT_EFFORT_OPTIONS,
    CHAT_MODEL_OPTIONS,
    default_chat_effort,
    default_chat_model,
    enterprise_chat_feature_flags,
    standalone_chat_enabled,
)
from gateway.standalone_chat.projects import (
    authorize_chat_project,
    cached_starter_questions,
    evaluate_project_readiness,
    resolve_default_project,
)
from gateway.store.standalone_chat.preferences import default_chat_budgets

from ..deps import RequireBillablePlan, StoreD, deployment_capabilities
from .common import is_admin as _is_admin
from .common import readiness_or_error as _readiness_or_error
from .common import require_enabled as _require_enabled
from .common import unready_detail as _unready_detail

router = APIRouter()


class DefaultProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1, max_length=200)


def exposed_enterprise_features(entitlement: OrgEntitlement) -> dict[str, bool]:
    """The ``enterprise_features`` payload: each flag is ``is_billable and not kill_switch_off``.

    The keys stay as the web app knows them; only the source changed, from the
    environment alone to the plan rule combined with the operator kill switches.
    """
    billable = entitlement.is_billable
    flags = enterprise_chat_feature_flags().as_dict()
    return {name: billable and value for name, value in flags.items() if name != "sandbox_runtime"}


@router.get("/bootstrap", response_model=ChatBootstrapResponse, dependencies=[RequireScope("read")])
async def bootstrap_chat(store: StoreD, role: OrgRole, org_id: OrgID, refresh: bool = False):
    """Chat bootstrap for every org.

    A free org gets ``enabled=False`` with its entitlement, so the web app can
    show a plan prompt; a billable org gets its projects. ``capabilities``
    reports what this deployment can run regardless of plan. ``?refresh=1``
    bypasses the entitlement cache (used once after Stripe Checkout).
    """
    entitlement = await get_entitlement(org_id, refresh=refresh)
    exposed_flags = exposed_enterprise_features(entitlement)
    capabilities = deployment_capabilities()
    model_options = [{"id": model_id, "label": label} for model_id, label in CHAT_MODEL_OPTIONS]
    selected_model = default_chat_model()
    effort_options = [{"id": effort_id, "label": label} for effort_id, label in CHAT_EFFORT_OPTIONS]
    selected_effort = default_chat_effort()
    if not standalone_chat_enabled() or not entitlement.is_billable:
        return ChatBootstrapResponse(
            enabled=False,
            plan_locked=True,
            projects=[],
            selected_project_id=None,
            is_admin=_is_admin(role),
            role=normalize_role(role),
            permissions=sorted(permissions_for(role)),
            starter_questions=[],
            available_models=model_options,
            default_model=selected_model,
            available_efforts=effort_options,
            default_effort=selected_effort,
            enterprise_features=exposed_flags,
            entitlement=entitlement.to_dict(),
            capabilities=capabilities,
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
    per_query_budget_usd, chat_budget_usd = await default_chat_budgets(
        store.session, org_id=org_id, user_id=user_id
    )
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
                "connection_type": readiness_by_project[project.id].connection_type,
                "registered": readiness_by_project[project.id].registered,
            }
            for project in projects
        ],
        selected_project_id=selected_id,
        is_admin=_is_admin(role),
        role=normalize_role(role),
        permissions=sorted(permissions_for(role)),
        starter_questions=starters,
        default_per_query_budget_usd=per_query_budget_usd,
        default_chat_budget_usd=chat_budget_usd,
        available_models=model_options,
        default_model=selected_model,
        available_efforts=effort_options,
        default_effort=selected_effort,
        enterprise_features=exposed_flags,
        entitlement=entitlement.to_dict(),
        capabilities=capabilities,
    )


@router.get(
    "/projects/{project_id}/readiness",
    dependencies=[RequireScope("read"), RequireBillablePlan],
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
        "connection_type": readiness.connection_type,
        "registered": readiness.registered,
        "starter_questions": starters,
    }


@router.put("/default-project", status_code=204, dependencies=[RequireScope("write"), RequireBillablePlan])
async def update_default_project(body: DefaultProjectUpdate, store: StoreD, _role: OrgAdmin):
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
