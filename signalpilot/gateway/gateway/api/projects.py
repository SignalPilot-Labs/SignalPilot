"""dbt Project CRUD and management endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from ..models import ProjectCreate, ProjectUpdate
from ..scope_guard import RequireScope
from .deps import StoreD

router = APIRouter(prefix="/api")


@router.get("/projects", dependencies=[RequireScope("read")])
async def get_projects(store: StoreD):
    """List all registered dbt projects."""
    return await store.list_projects()


@router.post("/projects", status_code=201, dependencies=[RequireScope("write")])
async def add_project(proj: ProjectCreate, store: StoreD):
    """Create a new dbt project."""
    try:
        info = await store.create_project(proj)
    except ValueError:
        raise HTTPException(status_code=409, detail="Project already exists")
    return info


@router.get("/projects/{name}", dependencies=[RequireScope("read")])
async def get_project_detail(name: str, store: StoreD):
    """Get a single dbt project by name."""
    proj = await store.get_project(name)
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    return proj


@router.put("/projects/{name}", dependencies=[RequireScope("write")])
async def edit_project(name: str, update: ProjectUpdate, store: StoreD):
    """Update an existing dbt project."""
    result = await store.update_project(name, update)
    if not result:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    return result


@router.delete("/projects/{name}", status_code=204, dependencies=[RequireScope("write")])
async def remove_project(name: str, store: StoreD):
    """Delete a dbt project."""
    if not await store.delete_project(name):
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")


@router.post("/projects/{name}/scan", dependencies=[RequireScope("write")])
async def scan_project(name: str, store: StoreD):
    """Re-scan a dbt project (placeholder — updates last_scanned_at)."""
    proj = await store.get_project(name)
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    now = time.time()
    await store.update_project(name, ProjectUpdate(last_scanned_at=now))
    return {"project": name, "scanned_at": now, "model_count": proj.model_count, "status": "ok"}
