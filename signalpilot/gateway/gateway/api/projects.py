"""dbt Project CRUD and management endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from ..models import ProjectCreate, ProjectUpdate
from ..store import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
)

router = APIRouter(prefix="/api")


@router.get("/projects")
async def get_projects():
    """List all registered dbt projects."""
    return list_projects()


@router.post("/projects", status_code=201)
async def add_project(proj: ProjectCreate):
    """Create a new dbt project."""
    try:
        info = create_project(proj)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return info


@router.get("/projects/{name}")
async def get_project_detail(name: str):
    """Get a single dbt project by name."""
    proj = get_project(name)
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    return proj


@router.put("/projects/{name}")
async def edit_project(name: str, update: ProjectUpdate):
    """Update an existing dbt project."""
    result = update_project(name, update)
    if not result:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    return result


@router.delete("/projects/{name}", status_code=204)
async def remove_project(name: str):
    """Delete a dbt project."""
    if not delete_project(name):
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")


@router.post("/projects/{name}/scan")
async def scan_project(name: str):
    """Re-scan a dbt project (placeholder — updates last_scanned_at)."""
    proj = get_project(name)
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    now = time.time()
    result = update_project(name, ProjectUpdate(last_scanned_at=now))
    return {"project": name, "scanned_at": now, "status": "ok"}
