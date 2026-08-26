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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from gateway.api.deps import StoreD
from gateway.auth import OrgAdmin
from gateway.common.ip import request_meta
from gateway.connectors.xata_control import XataControlClient, XataControlConfig, XataControlError
from gateway.connectors.xata_creds import resolve_xata_extras
from gateway.models import AuditEntry, ConnectionCreate, DBType
from gateway.security.scope_guard import RequireScope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

DEMO_TAG = "sp-demo"
DEMO_CREDENTIAL_REF = "demo"
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


@router.post("/demo/connector", status_code=201, dependencies=[RequireScope("write")])
async def create_demo_connector(
    store: StoreD, _role: OrgAdmin, request: Request, body: DemoConnectorCreate
):
    """Fork one demo warehouse into a fresh Xata branch and register it as a
    connection. Once per warehouse per workspace: 409 if already cloned."""
    cfg = _demo_config()
    if not cfg.enabled:
        raise HTTPException(
            status_code=503,
            detail="Demo connector is not configured (XATA_KEY / SP_DEMO_XATA_ORG / SP_DEMO_CATALOG)",
        )
    demo = cfg.get(body.demo)
    if demo is None:
        raise HTTPException(status_code=404, detail=f"Unknown demo warehouse '{body.demo}'")

    if await store.get_connection(demo.connection_name) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"You have already added the '{demo.title}' demo (connection "
            f"'{demo.connection_name}'). Remove it from the Connections page to start over.",
        )

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

    return {
        "connection": info,
        "demo": demo.slug,
        "title": demo.title,
        "branch": branch_name,
        "repo_url": demo.repo_url or None,
    }


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
