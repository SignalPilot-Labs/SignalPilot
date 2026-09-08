"""Published dashboards API: gallery, detail, bundles, settings, refresh.

Auth mirrors the chat file routes: ``RequireScope("read")`` for reads,
``RequireScope("query")`` for writes, org scoping through the store. A
dashboard is visible when its visibility is org, or the caller
created it. It is editable by its creator or an org admin.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response

from ..auth import OrgRole
from ..auth.user import is_org_admin_role
from ..dashboards import service, store
from ..dashboards.datasets import CSV_CONTENT_TYPE
from ..dashboards.refresh import run_refresh
from ..dashboards.serializers import (
    UpdateDashboardRequest,
    dashboard_out,
    refresh_out,
    version_out,
)
from ..dashboards.storage import DashboardStorage, dashboard_storage
from ..db.engine import get_session_factory
from ..db.models import GatewayPublishedDashboard, GatewayPublishedDashboardVersion
from ..db.models.dashboards import new_refresh_id
from ..security.scope_guard import RequireScope
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def storage() -> DashboardStorage:
    """Resolved per request so tests can substitute a fake backend."""
    return dashboard_storage()


_background_refreshes: set[asyncio.Task[None]] = set()


def _log_refresh_task(task: asyncio.Task[None]) -> None:
    _background_refreshes.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("Dashboard refresh task failed: %s", task.exception())


def launch_refresh(refresh_id: str) -> None:
    """Run a refresh in the background; the request returns at once.

    The task is held in a module set so the event loop cannot drop it
    mid-flight, and any exception that escapes ``run_refresh`` is logged.
    """
    task = asyncio.create_task(run_refresh(get_session_factory(), refresh_id))
    _background_refreshes.add(task)
    task.add_done_callback(_log_refresh_task)


def _user(store_: StoreD) -> str:
    return store_.user_id or "local"


async def _serialize(store_: StoreD, role: str, dashboard: GatewayPublishedDashboard):
    numbers = await store.version_numbers(store_.session, [dashboard.current_version_id or ""])
    return dashboard_out(
        dashboard,
        viewer_user_id=_user(store_),
        is_admin=is_org_admin_role(role),
        current_version_no=numbers.get(dashboard.current_version_id or ""),
    )


async def _visible_or_404(store_: StoreD, id_or_slug: str) -> GatewayPublishedDashboard:
    dashboard = await store.get_dashboard(store_.session, org_id=store_._require_org_id(), id_or_slug=id_or_slug)
    if dashboard is None or not store.is_visible(dashboard, _user(store_)):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return dashboard


async def _editable_or_error(store_: StoreD, role: str, id_or_slug: str) -> GatewayPublishedDashboard:
    dashboard = await _visible_or_404(store_, id_or_slug)
    if not store.can_edit(dashboard, _user(store_), is_admin=is_org_admin_role(role)):
        raise HTTPException(status_code=403, detail="You cannot edit this dashboard")
    return dashboard


async def _version_or_404(store_: StoreD, dashboard: GatewayPublishedDashboard, version_id: str) -> GatewayPublishedDashboardVersion:
    version = await store.get_version(store_.session, dashboard_id=dashboard.id, version_id=version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return version


def _raise(error: service.DashboardError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)


async def _bundle(dashboard_view, version: GatewayPublishedDashboardVersion):
    spec = await storage().get_spec(version.spec_key)
    datasets = await service.load_bundle_datasets(storage(), spec, version)
    return {
        "dashboard": dashboard_view,
        "version": version_out(version),
        "spec": spec,
        "datasets": datasets,
    }


# ── Gallery and detail ──────────────────────────────────────────────────────


@router.get("/dashboards", dependencies=[RequireScope("read")])
async def list_dashboards(store_: StoreD, role: OrgRole, include_archived: bool = Query(False)):
    rows = await store.list_dashboards(
        store_.session,
        org_id=store_._require_org_id(),
        user_id=_user(store_),
        include_archived=include_archived,
    )
    numbers = await store.version_numbers(store_.session, [row.current_version_id or "" for row in rows])
    admin = is_org_admin_role(role)
    return {
        "dashboards": [
            dashboard_out(
                row,
                viewer_user_id=_user(store_),
                is_admin=admin,
                current_version_no=numbers.get(row.current_version_id or ""),
            )
            for row in rows
        ]
    }


@router.get("/dashboards/{id_or_slug}", dependencies=[RequireScope("read")])
async def get_dashboard(id_or_slug: str, store_: StoreD, role: OrgRole):
    dashboard = await _visible_or_404(store_, id_or_slug)
    versions = await store.list_versions(store_.session, dashboard.id)
    refreshes = await store.list_refreshes(store_.session, dashboard.id)
    return {
        "dashboard": await _serialize(store_, role, dashboard),
        "versions": [version_out(row) for row in versions],
        "refreshes": [refresh_out(row) for row in refreshes],
    }


@router.get("/dashboards/{dashboard_id}/versions/{version_id}/bundle", dependencies=[RequireScope("read")])
async def get_bundle(dashboard_id: str, version_id: str, store_: StoreD, role: OrgRole):
    dashboard = await _visible_or_404(store_, dashboard_id)
    version = await _version_or_404(store_, dashboard, version_id)
    return await _bundle(await _serialize(store_, role, dashboard), version)


@router.get("/dashboards/{dashboard_id}/versions/{version_id}/datasets/{name}", dependencies=[RequireScope("read")])
async def download_dataset(dashboard_id: str, version_id: str, name: str, store_: StoreD):
    dashboard = await _visible_or_404(store_, dashboard_id)
    version = await _version_or_404(store_, dashboard, version_id)
    key = (version.dataset_keys or {}).get(name)
    if not key:
        raise HTTPException(status_code=404, detail="Dataset not found")
    meta = (version.dataset_meta or {}).get(name) or {}
    filename = str(meta.get("filename") or f"{name}.csv")
    data = await storage().get_dataset(key)
    ascii_name = re.sub(r'[^\x20-\x7e]|["\\]', "_", filename) or "dataset"
    return Response(
        content=data,
        media_type=CSV_CONTENT_TYPE,
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=0, must-revalidate",
        },
    )


# ── Settings and lifecycle ──────────────────────────────────────────────────


@router.patch("/dashboards/{dashboard_id}", dependencies=[RequireScope("query")])
async def update_dashboard(dashboard_id: str, body: UpdateDashboardRequest, store_: StoreD, role: OrgRole):
    dashboard = await _editable_or_error(store_, role, dashboard_id)
    await service.update_settings(store_.session, dashboard, body)
    return {"dashboard": await _serialize(store_, role, dashboard)}


@router.post("/dashboards/{dashboard_id}/refresh", status_code=202, dependencies=[RequireScope("query")])
async def refresh_now(dashboard_id: str, store_: StoreD, role: OrgRole):
    dashboard = await _editable_or_error(store_, role, dashboard_id)
    if dashboard.archived_at is not None:
        raise HTTPException(status_code=409, detail="Unarchive the dashboard before refreshing it")
    if await store.active_refresh(store_.session, dashboard.id) is not None:
        raise HTTPException(status_code=409, detail="A refresh is already queued or running")
    refresh = await store.create_refresh(
        store_.session,
        dashboard=dashboard,
        refresh_id=new_refresh_id(),
        mode=dashboard.refresh_mode,
        trigger="manual",
    )
    launch_refresh(refresh.id)
    return {"refresh": refresh_out(refresh)}


@router.get("/dashboards/{dashboard_id}/refreshes", dependencies=[RequireScope("read")])
async def list_refreshes(dashboard_id: str, store_: StoreD, limit: int = Query(20, ge=1, le=100)):
    dashboard = await _visible_or_404(store_, dashboard_id)
    rows = await store.list_refreshes(store_.session, dashboard.id, limit=limit)
    return {"refreshes": [refresh_out(row) for row in rows]}


@router.post("/dashboards/{dashboard_id}/versions/{version_id}/restore", dependencies=[RequireScope("query")])
async def restore_version(dashboard_id: str, version_id: str, store_: StoreD, role: OrgRole):
    dashboard = await _editable_or_error(store_, role, dashboard_id)
    version = await _version_or_404(store_, dashboard, version_id)
    restored = await service.restore_version(store_.session, storage(), dashboard, version, user_id=_user(store_))
    return {"dashboard": await _serialize(store_, role, dashboard), "version": version_out(restored)}


@router.post("/dashboards/{dashboard_id}/archive", dependencies=[RequireScope("query")])
async def archive_dashboard(dashboard_id: str, store_: StoreD, role: OrgRole):
    dashboard = await _editable_or_error(store_, role, dashboard_id)
    await service.set_archived(store_.session, dashboard, True)
    return {"dashboard": await _serialize(store_, role, dashboard)}


@router.post("/dashboards/{dashboard_id}/unarchive", dependencies=[RequireScope("query")])
async def unarchive_dashboard(dashboard_id: str, store_: StoreD, role: OrgRole):
    dashboard = await _editable_or_error(store_, role, dashboard_id)
    await service.set_archived(store_.session, dashboard, False)
    return {"dashboard": await _serialize(store_, role, dashboard)}


@router.delete("/dashboards/{dashboard_id}", status_code=204, response_model=None, dependencies=[RequireScope("query")])
async def delete_dashboard(dashboard_id: str, store_: StoreD, role: OrgRole):
    dashboard = await _editable_or_error(store_, role, dashboard_id)
    await service.delete(store_.session, storage(), dashboard)
    return Response(status_code=204)


@router.post("/dashboards/{dashboard_id}/edit-chat", dependencies=[RequireScope("query")])
async def open_edit_chat(dashboard_id: str, store_: StoreD, role: OrgRole):
    dashboard = await _visible_or_404(store_, dashboard_id)
    version = await store.current_version(store_.session, dashboard)
    if version is None:
        raise HTTPException(status_code=409, detail="Dashboard has no current version")
    try:
        conversation_id = await service.create_edit_chat(
            store_.session, storage(), dashboard, version, user_id=_user(store_)
        )
    except service.DashboardError as error:
        raise _raise(error) from error
    return {"conversation_id": conversation_id}
