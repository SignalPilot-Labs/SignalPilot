"""Notion integration CRUD and test endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from gateway.api.deps import StoreD
from gateway.auth import OrgAdmin
from gateway.models.notion import (
    NotionIntegrationCreate,
    NotionIntegrationInfo,
    NotionIntegrationUpdate,
)
from gateway.notion.client import test_connection
from gateway.security.scope_guard import RequireScope

router = APIRouter(prefix="/api/integrations/notion")


@router.get("", dependencies=[RequireScope("read")])
async def list_notion_integrations(store: StoreD) -> list[NotionIntegrationInfo]:
    """List all Notion integrations."""
    return await store.list_notion_integrations()


@router.post("", status_code=201, dependencies=[RequireScope("write")])
async def create_notion_integration(
    integration: NotionIntegrationCreate,
    store: StoreD,
    _role: OrgAdmin,
) -> NotionIntegrationInfo:
    """Create a new Notion integration."""
    try:
        return await store.create_notion_integration(integration)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("/{name}", dependencies=[RequireScope("read")])
async def get_notion_integration(name: str, store: StoreD) -> NotionIntegrationInfo:
    """Get a Notion integration by name."""
    info = await store.get_notion_integration(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Notion integration '{name}' not found")
    return info


@router.put("/{name}", dependencies=[RequireScope("write")])
async def update_notion_integration(
    name: str,
    update: NotionIntegrationUpdate,
    store: StoreD,
    _role: OrgAdmin,
) -> NotionIntegrationInfo:
    """Update a Notion integration."""
    result = await store.update_notion_integration(name, update)
    if not result:
        raise HTTPException(status_code=404, detail=f"Notion integration '{name}' not found")
    return result


@router.delete("/{name}", status_code=204, dependencies=[RequireScope("write")])
async def delete_notion_integration(name: str, store: StoreD, _role: OrgAdmin) -> None:
    """Delete a Notion integration."""
    if not await store.delete_notion_integration(name):
        raise HTTPException(status_code=404, detail=f"Notion integration '{name}' not found")


@router.post("/{name}/test", dependencies=[RequireScope("read")])
async def test_notion_integration(name: str, store: StoreD) -> dict[str, str]:
    """Test a Notion integration's API key connectivity."""
    api_key = await store.get_notion_api_key(name)
    if not api_key:
        raise HTTPException(status_code=404, detail=f"Notion integration '{name}' not found")
    ok, message = await test_connection(api_key)
    if not ok:
        return {"status": "error", "message": message}
    return {"status": "ok", "message": "Connected to Notion API successfully"}
