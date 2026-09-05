"""Provide isolated Xata demo warehouses through the /demo-db page.

POST creates a copy-on-write branch and registers a SignalPilot connection.
Each workspace can have one connection for each demo warehouse.
Deleting the connection also deletes its Xata branch.

The gateway stores XATA_KEY as a server-side secret.
The connection stores ``xata_credential_ref="demo"`` instead of the key.
The connection pin limits the shared key to one project and one branch.

SP_DEMO_CATALOG defines the available demo warehouses.
An empty catalog disables the demo connector.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from gateway.api.deps import StoreD
from gateway.auth import OrgAdmin
from gateway.common.ip import request_meta
from gateway.connectors.xata_control import XataControlClient, XataControlConfig, XataControlError
from gateway.connectors.xata_creds import resolve_xata_extras
from gateway.db.models import (
    GatewayChatConversation,
    GatewayChatMessage,
    GatewayChatRun,
    GatewayChatRunEvent,
    GatewayChatUserPreference,
    GatewayDbtManifest,
    GatewayWorkspaceProject,
)
from gateway.models import AuditEntry, ConnectionCreate, DBType
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.demo_policy import DEMO_REQUEST_LIMIT, DEMO_TAG

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

DEMO_CREDENTIAL_REF = "demo"
DEMO_PROJECT_TAG = "journey:demo-v1"
DEMO_REPLAY_VERSION = "experiments-v1"
DEMO_CATALOG_SLUG = "parallax"
DEMO_REPO = "https://github.com/kiwi0401/parallax-demo"
DEMO_PARALLAX_PROJECT = "prj_7r8eolv5c15q12os2k0m3lt408"
# Retained for a later catalog version; it is intentionally not exposed by
# the v1 bootstrap endpoint because no companion dbt repository is available.
DEMO_AKASA_PROJECT = "prj_p6e0sj40ld5gj6hppjda7frf20"
_PROTECTED_BRANCHES = frozenset({"main", "master", "staging", "prod", "production"})
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")


@dataclass(frozen=True)
class Demo:
    """One shared demo warehouse the user can clone."""

    slug: str
    project: str
    title: str
    description: str = ""
    repo_url: str = ""
    parent_branch: str = "main"
    database: str = "xata"
    connection_name: str = ""

    def __post_init__(self) -> None:
        if not self.connection_name:
            object.__setattr__(self, "connection_name", f"{self.slug}-demo")


@dataclass
class DemoConfig:
    api_key: str = ""
    api_url: str = "https://api.xata.tech"
    org: str = ""
    demos: list[Demo] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.org and self.demos)

    def get(self, slug: str) -> Demo | None:
        return next((d for d in self.demos if d.slug == slug), None)


class DemoConnectorCreate(BaseModel):
    demo: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-z0-9][a-z0-9-]{0,30}$")


class DemoBootstrapCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_slug: str = Field(..., pattern="^parallax$")


class DemoBootstrapResponse(BaseModel):
    status: str
    phase: str
    created: bool
    connection_name: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    replay_run_id: str | None = None
    request_limit: int = DEMO_REQUEST_LIMIT
    requests_used: int = 0
    requests_remaining: int = DEMO_REQUEST_LIMIT


def _catalog() -> list[Demo]:
    """Parse SP_DEMO_CATALOG into the list of demo warehouses.

    An empty value returns no demo warehouses.

    SP_DEMO_CATALOG is a JSON array that fits in one AWS parameter:

        [{"slug": "contoso",
          "project": "prj_...",
          "title": "Contoso",
          "description": "experimentation platform warehouse",
          "repo_url": "https://github.com/..."}]

    Skip a malformed entry and log a warning.
    """
    raw = os.getenv("SP_DEMO_CATALOG", "").strip()
    if raw:
        try:
            entries = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("SP_DEMO_CATALOG is not valid JSON — demo connector disabled: %s", e)
            return []
        if not isinstance(entries, list):
            logger.error("SP_DEMO_CATALOG must be a JSON array — demo connector disabled")
            return []
        demos: list[Demo] = []
        for entry in entries:
            if not isinstance(entry, dict):
                logger.warning("SP_DEMO_CATALOG: skipping non-object entry")
                continue
            slug = str(entry.get("slug", "")).strip().lower()
            project = str(entry.get("project", "")).strip()
            if not _SLUG_RE.match(slug) or not project:
                logger.warning("SP_DEMO_CATALOG: skipping entry with bad slug/project (%r)", slug)
                continue
            if any(d.slug == slug for d in demos):
                logger.warning("SP_DEMO_CATALOG: duplicate slug %r — keeping the first", slug)
                continue
            demos.append(
                Demo(
                    slug=slug,
                    project=project,
                    title=str(entry.get("title") or slug).strip(),
                    description=str(entry.get("description") or "").strip(),
                    repo_url=str(entry.get("repo_url") or "").strip(),
                    parent_branch=str(entry.get("parent_branch") or "main").strip(),
                    database=str(entry.get("database") or "xata").strip(),
                    connection_name=str(entry.get("connection_name") or "").strip(),
                )
            )
        return demos

    return []


def _demo_config() -> DemoConfig:
    return DemoConfig(
        api_key=os.getenv("XATA_KEY", "").strip(),
        api_url=os.getenv("SP_DEMO_XATA_API_URL", "https://api.xata.tech").strip(),
        org=os.getenv("SP_DEMO_XATA_ORG", "").strip(),
        demos=_catalog(),
    )


def _control_client(cfg: DemoConfig) -> XataControlClient:
    return XataControlClient(
        XataControlConfig(api_url=cfg.api_url, org=cfg.org, bearer_token=cfg.api_key)
    )


def _require_bootstrap_catalog_entry(demo: Demo) -> None:
    repo_url = (demo.repo_url or "").removesuffix(".git")
    if (
        demo.slug != DEMO_CATALOG_SLUG
        or demo.project != DEMO_PARALLAX_PROJECT
        or demo.parent_branch != "main"
        or repo_url != DEMO_REPO
    ):
        raise HTTPException(status_code=503, detail="Demo catalog repository is not allowlisted")


async def _demo_state(store, cfg: DemoConfig) -> dict[str, dict]:
    """Map demo slug -> {exists, branch, connection_name} for this workspace."""
    by_name = {c.name: c for c in await store.list_connections()}
    state: dict[str, dict] = {}
    for demo in cfg.demos:
        conn = by_name.get(demo.connection_name)
        branch = None
        if conn is not None:
            # branch rides in the encrypted extras, not on ConnectionInfo
            extras = await store.get_credential_extras(conn.name) or {}
            branch = extras.get("branch")
        state[demo.slug] = {
            "exists": conn is not None,
            "branch": branch,
            "connection_name": demo.connection_name,
        }
    return state


@router.get("/demo/connector", dependencies=[RequireScope("read")])
async def get_demo_connector(store: StoreD):
    """The demo catalog and, for each warehouse, whether this workspace cloned it."""
    cfg = _demo_config()
    state = await _demo_state(store, cfg)
    return {
        "enabled": cfg.enabled,
        "demos": [
            {
                "slug": d.slug,
                "title": d.title,
                "description": d.description,
                "repo_url": d.repo_url or None,
                "parent_branch": d.parent_branch,
                **state[d.slug],
            }
            for d in cfg.demos
        ],
    }


async def _ensure_demo_connection(store, request: Request, slug: str):
    """Create the catalog connection once, returning ``(connection, demo, branch, created)``."""
    cfg = _demo_config()
    if not cfg.enabled:
        raise HTTPException(
            status_code=503,
            detail="Demo connector is not configured (XATA_KEY / SP_DEMO_XATA_ORG / SP_DEMO_CATALOG)",
        )
    demo = cfg.get(slug)
    if demo is None:
        raise HTTPException(status_code=404, detail=f"Unknown demo warehouse '{slug}'")

    existing = await store.get_connection(demo.connection_name)
    if existing is not None:
        extras = await store.get_credential_extras(existing.name) or {}
        return existing, demo, str(extras.get("branch") or ""), False

    from gateway.governance.plan_limits import check_connection_limit, get_org_limits

    plan = await get_org_limits(store.org_id)
    check_connection_limit(len(await store.list_connections()), plan)

    branch_name = f"demo-{uuid.uuid4().hex[:8]}"
    try:
        async with _control_client(cfg) as client:
            branches = await client.list_branches(demo.project)
            parent = next((b for b in branches if b.get("name") == demo.parent_branch), None)
            if not parent:
                raise HTTPException(
                    status_code=502,
                    detail=f"Demo warehouse '{demo.title}' is not ready "
                    f"(parent branch '{demo.parent_branch}' not found)",
                )
            branch = await client.create_child_branch(demo.project, branch_name, parent["id"])
    except HTTPException:
        raise
    except XataControlError as e:
        logger.warning("demo.connector branch create failed for %s: %s", demo.slug, e)
        raise HTTPException(status_code=502, detail="Could not create your demo database branch")

    conn = ConnectionCreate(
        name=demo.connection_name,
        db_type=DBType.xata,
        branch=branch_name,
        # No key at rest: reference the gateway-held secret, and pin this
        # connection to its own project + branch so the shared org key cannot
        # reach anything else.
        xata_credential_ref=DEMO_CREDENTIAL_REF,
        xata_pinned=True,
        xata_organization=cfg.org,
        xata_project=demo.project,
        xata_database=demo.database,
        xata_api_url=cfg.api_url,
        description=f"Demo sandbox — your private branch of the {demo.title} warehouse",
        tags=[DEMO_TAG, f"demo:{demo.slug}"],
    )
    try:
        info = await store.create_connection(conn)
    except Exception as e:
        # Roll the branch back so a failed registration doesn't leak branches.
        try:
            async with _control_client(cfg) as client:
                await client.delete_branch(demo.project, branch["id"])
        except Exception:
            logger.warning("demo.connector rollback failed for branch %s", branch_name)
        if isinstance(e, ValueError):
            raise HTTPException(status_code=409, detail="Connection already exists or invalid parameters")
        raise

    client_ip, user_agent = request_meta(request)
    try:
        await store.append_audit(
            AuditEntry(
                id=str(uuid.uuid4()),
                timestamp=time.time(),
                event_type="demo_connector_create",
                metadata={"name": info.name, "branch": branch_name, "demo": demo.slug},
                client_ip=client_ip,
                user_agent=user_agent,
            )
        )
    except Exception:
        logger.warning("Failed to append audit log for demo_connector_create")

    return info, demo, branch_name, True


@router.post("/demo/connector", status_code=201, dependencies=[RequireScope("write")])
async def create_demo_connector(
    store: StoreD, _role: OrgAdmin, request: Request, body: DemoConnectorCreate
):
    """Idempotently fork one catalog warehouse into a private Xata branch."""
    info, demo, branch_name, _created = await _ensure_demo_connection(store, request, body.demo)
    return {
        "connection": info,
        "demo": demo.slug,
        "title": demo.title,
        "branch": branch_name,
        "repo_url": demo.repo_url or None,
    }


async def _demo_project(store, demo: Demo) -> tuple[GatewayWorkspaceProject | None, bool]:
    _require_bootstrap_catalog_entry(demo)
    projects = list(
        (
            await store.session.execute(
                select(GatewayWorkspaceProject).where(
                    GatewayWorkspaceProject.org_id == store._require_org_id(),
                    GatewayWorkspaceProject.status == "active",
                )
            )
        ).scalars()
    )
    existing = next(
        (p for p in projects if DEMO_PROJECT_TAG in (p.tags or []) and f"demo:{demo.slug}" in (p.tags or [])),
        None,
    )
    if existing:
        existing.connection_name = demo.connection_name
        existing.source = "github"
        existing.git_remote = f"{DEMO_REPO}.git"
        existing.default_branch = "main"
        existing.tags = list(
            dict.fromkeys([*(existing.tags or []), DEMO_TAG, f"demo:{demo.slug}", DEMO_PROJECT_TAG])
        )
        await store.session.commit()
        compiled = await store.session.scalar(
            select(func.count(GatewayDbtManifest.id)).where(
                GatewayDbtManifest.org_id == store._require_org_id(),
                GatewayDbtManifest.project_id == existing.id,
                GatewayDbtManifest.status == "success",
            )
        )
        if not compiled:
            await _prepare_demo_project(store, existing)
        return existing, False

    project = await store.create_workspace_project(
        name="parallax-demo",
        display_name="Demo project",
        description="SignalPilot private demo workspace",
        source="github",
        connection_name=demo.connection_name,
        git_remote=f"{DEMO_REPO}.git",
        tags=[DEMO_TAG, f"demo:{demo.slug}", DEMO_PROJECT_TAG],
        settings={"dbt_project_dir": ""},
    )
    row = await store.session.get(GatewayWorkspaceProject, project.id)
    if row is not None:
        await _prepare_demo_project(store, row)
    return row, True


async def _prepare_demo_project(store, project: GatewayWorkspaceProject) -> None:
    """Idempotently import the allowlisted repository and request compilation."""
    try:
        from gateway.api.github import _import_workspace_revision
        from gateway.git.repos import clone_from_remote, materialize_local_branches

        clone_from_remote(project.id, f"{DEMO_REPO}.git")
        materialize_local_branches(project.id, "main")
        await _import_workspace_revision(
            store.session,
            org_id=store._require_org_id(),
            project_id=project.id,
            branch="main",
        )
        from gateway.dbt_map import schedule_compile

        schedule_compile(store._require_org_id(), project.id, "main", trigger="demo-bootstrap")
    except Exception:
        logger.exception("demo bootstrap project preparation failed for %s", project.id)


async def _seed_demo_replay(store, project: GatewayWorkspaceProject) -> tuple[str, str]:
    org_id = store._require_org_id()
    user_id = store.user_id or "local"
    existing = list(
        (
            await store.session.execute(
            select(GatewayChatConversation).where(
                GatewayChatConversation.org_id == org_id,
                GatewayChatConversation.user_id == user_id,
                GatewayChatConversation.project_id == project.id,
                GatewayChatConversation.origin == "demo_replay",
            ).order_by(GatewayChatConversation.updated_at.desc())
            )
        ).scalars()
    )
    for conversation_row in existing:
        run = (
            await store.session.execute(
                select(GatewayChatRun)
                .where(GatewayChatRun.conversation_id == conversation_row.id)
                .order_by(GatewayChatRun.created_at)
            )
        ).scalars().first()
        if not run:
            continue
        marker = await store.session.get(GatewayChatMessage, run.user_message_id)
        metadata = marker.metadata_json if marker else {}
        if metadata.get("demo_replay") is True and metadata.get("fixture_version") == DEMO_REPLAY_VERSION:
            return conversation_row.id, run.id

    now = time.time()
    conversation = GatewayChatConversation(
        id=str(uuid.uuid4()), org_id=org_id, user_id=user_id, project_id=project.id,
        surface="standalone", origin="demo_replay", branch="main", status="active",
        title="Which experiments drove conversion lift?", message_count=2,
        total_tokens=0, total_cost_usd=0.0, created_at=now, updated_at=now,
    )
    user_message = GatewayChatMessage(
        id=str(uuid.uuid4()), org_id=org_id, user_id=user_id, project_id=project.id,
        conversation_id=conversation.id, role="user",
        content="Identify the experiments with the largest conversion lift and assess whether the results are trustworthy.",
        metadata_json={"surface": "standalone", "demo_replay": True, "fixture_version": DEMO_REPLAY_VERSION},
        sequence=1, created_at=now,
    )
    run = GatewayChatRun(
        id=str(uuid.uuid4()), org_id=org_id, user_id=user_id,
        conversation_id=conversation.id, project_id=project.id,
        user_message_id=user_message.id, status="completed", runtime_env="demo-replay",
        started_at=datetime.fromtimestamp(now + 0.2, UTC),
        terminal_at=datetime.fromtimestamp(now + 8, UTC), last_event_sequence=6,
    )
    assistant = GatewayChatMessage(
        id=str(uuid.uuid4()), org_id=org_id, user_id=user_id, project_id=project.id,
        conversation_id=conversation.id, role="assistant",
        content=(
            "The largest observed lift comes from the checkout and onboarding experiments. "
            "The checkout result is the most trustworthy because its sample is large and the confidence interval excludes zero; "
            "the onboarding lift is promising but should be rerun because exposure is uneven across clients."
        ),
        metadata_json={"surface": "standalone", "run_id": run.id, "status": "completed"},
        sequence=2, created_at=now + 8,
    )
    event_specs = [
        ("status", {"status": "running"}, 0.2),
        ("progress", {"message": "Comparing experiment cohorts"}, 1.0),
        ("tool_started", {"tool": "query", "tool_call_id": "demo-query", "input": {"purpose": "measure conversion lift"}}, 2.0),
        ("tool_completed", {"tool": "query", "tool_call_id": "demo-query", "summary": "Experiment cohorts compared"}, 4.0),
        ("text_delta", {"delta": assistant.content}, 5.0),
        ("status", {"status": "completed"}, 8.0),
    ]
    events = [
        GatewayChatRunEvent(
            id=str(uuid.uuid4()), org_id=org_id, user_id=user_id,
            conversation_id=conversation.id, run_id=run.id, sequence=index,
            event_type=kind, payload_json=payload,
            created_at=datetime.fromtimestamp(now + offset, UTC),
        )
        for index, (kind, payload, offset) in enumerate(event_specs, start=1)
    ]
    store.session.add_all([conversation, user_message, run, assistant, *events])
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
        store.session.add(GatewayChatUserPreference(
            org_id=org_id, user_id=user_id, default_chat_project_id=project.id
        ))
    await store.session.commit()
    return conversation.id, run.id


async def _demo_request_usage(store) -> int:
    return int(
        await store.session.scalar(
            select(func.count(GatewayChatRun.id))
            .join(GatewayChatConversation, GatewayChatConversation.id == GatewayChatRun.conversation_id)
            .where(
                GatewayChatRun.org_id == store._require_org_id(),
                GatewayChatConversation.origin != "demo_replay",
            )
        )
        or 0
    )


async def _bootstrap_state(store, slug: str, *, created: bool = False) -> DemoBootstrapResponse:
    cfg = _demo_config()
    demo = cfg.get(slug)
    if demo is None:
        raise HTTPException(status_code=404, detail="Unknown demo catalog")
    _require_bootstrap_catalog_entry(demo)
    connection = await store.get_connection(demo.connection_name)
    projects = list((await store.session.execute(select(GatewayWorkspaceProject).where(
        GatewayWorkspaceProject.org_id == store._require_org_id(),
        GatewayWorkspaceProject.status == "active",
    ))).scalars())
    project = next((p for p in projects if DEMO_PROJECT_TAG in (p.tags or [])), None)
    used = await _demo_request_usage(store)
    base = {
        "created": created,
        "connection_name": connection.name if connection else None,
        "project_id": project.id if project else None,
        "request_limit": DEMO_REQUEST_LIMIT,
        "requests_used": used,
        "requests_remaining": max(0, DEMO_REQUEST_LIMIT - used),
    }
    if not connection:
        return DemoBootstrapResponse(status="provisioning", phase="private_data", **base)
    if not project:
        return DemoBootstrapResponse(status="provisioning", phase="project", **base)
    compiled = await store.session.scalar(select(func.count(GatewayDbtManifest.id)).where(
        GatewayDbtManifest.org_id == store._require_org_id(),
        GatewayDbtManifest.project_id == project.id,
        GatewayDbtManifest.status == "success",
    ))
    if not compiled:
        return DemoBootstrapResponse(status="provisioning", phase="project", **base)
    conversation_id, run_id = await _seed_demo_replay(store, project)
    return DemoBootstrapResponse(
        status="ready", phase="opening", conversation_id=conversation_id,
        replay_run_id=run_id, **base,
    )


@router.post("/demo/bootstrap", response_model=DemoBootstrapResponse, dependencies=[RequireScope("write")])
async def bootstrap_demo(
    body: DemoBootstrapCreate, store: StoreD, _role: OrgAdmin, request: Request, response: Response
):
    configured_demo = _demo_config().get(body.catalog_slug)
    if configured_demo is None:
        raise HTTPException(status_code=404, detail="Unknown demo catalog")
    _require_bootstrap_catalog_entry(configured_demo)
    _info, demo, _branch, connection_created = await _ensure_demo_connection(store, request, body.catalog_slug)
    _project, project_created = await _demo_project(store, demo)
    state = await _bootstrap_state(store, body.catalog_slug, created=connection_created or project_created)
    response.status_code = 200 if state.status == "ready" else 202
    return state


@router.get("/demo/bootstrap", response_model=DemoBootstrapResponse, dependencies=[RequireScope("read")])
async def get_demo_bootstrap(
    store: StoreD, response: Response, catalog_slug: str = Query(DEMO_CATALOG_SLUG, pattern="^parallax$")
):
    state = await _bootstrap_state(store, catalog_slug)
    response.status_code = 200 if state.status == "ready" else 202
    return state


@router.get("/demo/replay/{conversation_id}/{run_id}", dependencies=[RequireScope("read")])
async def authorize_demo_replay(conversation_id: str, run_id: str, store: StoreD):
    marker = await store.session.scalar(
        select(GatewayChatMessage.id)
        .join(GatewayChatRun, GatewayChatRun.user_message_id == GatewayChatMessage.id)
        .join(GatewayChatConversation, GatewayChatConversation.id == GatewayChatRun.conversation_id)
        .where(
            GatewayChatConversation.id == conversation_id,
            GatewayChatConversation.org_id == store._require_org_id(),
            GatewayChatConversation.user_id == (store.user_id or "local"),
            GatewayChatConversation.origin == "demo_replay",
            GatewayChatRun.id == run_id,
        )
    )
    if marker is None:
        raise HTTPException(status_code=404, detail="Demo replay not found")
    message = await store.session.get(GatewayChatMessage, marker)
    metadata = message.metadata_json if message else {}
    if not metadata or metadata.get("demo_replay") is not True:
        raise HTTPException(status_code=404, detail="Demo replay not found")
    return {"authorized": True, "fixture_version": metadata.get("fixture_version")}


async def _delete_demo_branch_strict(store, connection_name: str) -> None:
    connection = await store.get_connection(connection_name)
    if connection is None:
        return
    extras = await store.get_credential_extras(connection_name) or {}
    if DEMO_TAG not in (connection.tags or []):
        return
    resolved = resolve_xata_extras(extras)
    branch_name = str(resolved.get("branch") or "")
    if not branch_name or branch_name.lower() in _PROTECTED_BRANCHES:
        raise HTTPException(status_code=409, detail="Demo branch identity is invalid; cleanup was aborted")
    client = XataControlClient(XataControlConfig(
        api_url=str(resolved.get("xata_api_url") or "https://api.xata.tech"),
        org=str(resolved.get("xata_organization") or ""),
        bearer_token=str(resolved.get("xata_api_key") or ""),
    ))
    async with client:
        branches = await client.list_branches(str(resolved.get("xata_project") or ""))
        branch = next((item for item in branches if item.get("name") == branch_name), None)
        if branch is not None:
            await client.delete_branch(str(resolved.get("xata_project") or ""), branch["id"])


@router.post("/demo/cleanup", dependencies=[RequireScope("write")])
async def cleanup_demo_team(store: StoreD, _role: OrgAdmin):
    """Delete demo-owned project, remote branch, and connection before Clerk org deletion."""
    connections = await store.list_connections()
    demo_connections = [connection for connection in connections if DEMO_TAG in (connection.tags or [])]
    projects = list((await store.session.execute(select(GatewayWorkspaceProject).where(
        GatewayWorkspaceProject.org_id == store._require_org_id(),
    ))).scalars())
    demo_projects = [project for project in projects if DEMO_TAG in (project.tags or [])]
    if not demo_connections and not demo_projects:
        return {"demo": False, "cleaned": False}
    for project in demo_projects:
        if not await store.delete_workspace_project(project.id):
            raise HTTPException(status_code=409, detail="Could not remove demo project; retry cleanup")
    for connection in demo_connections:
        try:
            await _delete_demo_branch_strict(store, connection.name)
        except Exception as exc:
            logger.warning("demo cleanup aborted before organization deletion: %s", exc)
            raise HTTPException(status_code=502, detail="Could not remove private demo data; retry cleanup") from exc
        if not await store.delete_connection(connection.name):
            raise HTTPException(status_code=409, detail="Could not remove demo connection; retry cleanup")
    return {"demo": True, "cleaned": True}


async def prepare_demo_branch_cleanup(store, name: str) -> Callable[[], Awaitable[None]] | None:
    """If `name` is a demo connection, capture what is needed to delete its
    Xata branch and return a best-effort cleanup callable to run AFTER the
    connection row is deleted. Returns None for non-demo connections.

    Configuration comes from the connection's own stored extras so cleanup works
    even if the demo catalog has changed since the branch was created; the key
    itself is resolved from the gateway's secret, never from storage.
    """
    conn = await store.get_connection(name)
    if not conn or conn.db_type != DBType.xata or DEMO_TAG not in (conn.tags or []):
        return None

    extras = await store.get_credential_extras(name) or {}
    branch = extras.get("branch")  # branch rides in the encrypted extras
    if not branch or branch.lower() in _PROTECTED_BRANCHES:
        return None

    try:
        extras = resolve_xata_extras(extras)
    except Exception as e:
        logger.warning("demo.connector cleanup skipped for %s: %s", name, e)
        return None

    api_key = extras.get("xata_api_key") or os.getenv("XATA_KEY", "").strip()
    org = extras.get("xata_organization") or os.getenv("SP_DEMO_XATA_ORG", "").strip()
    project = extras.get("xata_project")
    api_url = extras.get("xata_api_url") or os.getenv("SP_DEMO_XATA_API_URL", "https://api.xata.tech")
    if not (api_key and org and project):
        logger.warning("demo.connector cleanup skipped for %s: missing Xata configuration", name)
        return None

    client = XataControlClient(XataControlConfig(api_url=api_url, org=org, bearer_token=api_key))

    async def _cleanup() -> None:
        try:
            async with client:
                branches = await client.list_branches(project)
                b = next((x for x in branches if x.get("name") == branch), None)
                if b is None:
                    logger.info("demo.connector branch %s already gone", branch)
                    return
                await client.delete_branch(project, b["id"])
                logger.info("demo.connector deleted branch %s (connection %s)", branch, name)
        except Exception as e:
            logger.warning("demo.connector failed to delete branch %s: %s", branch, e)

    return _cleanup
