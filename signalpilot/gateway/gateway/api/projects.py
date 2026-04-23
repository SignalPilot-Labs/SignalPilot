"""dbt Project CRUD and management endpoints."""

from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
    update_project(name, ProjectUpdate(last_scanned_at=now))
    return {"project": name, "scanned_at": now, "model_count": proj.model_count, "status": "ok"}


class DbtCloudDiscoverRequest(BaseModel):
    """Request to discover projects from a dbt Cloud account."""
    token: str = Field(..., min_length=1)
    account_id: str = Field(..., min_length=1)


@router.post("/dbt-cloud/projects")
async def discover_dbt_cloud_projects(req: DbtCloudDiscoverRequest):
    """Fetch project list from dbt Cloud API (proxied to avoid CORS)."""
    url = f"https://cloud.getdbt.com/api/v2/accounts/{req.account_id}/projects/"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"Authorization": f"Token {req.token}"})
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid dbt Cloud API token")
        raise HTTPException(status_code=e.response.status_code, detail="dbt Cloud API error")
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Cannot reach dbt Cloud API")

    data = resp.json().get("data", [])
    return [
        {
            "id": p["id"],
            "name": p.get("name", ""),
            "git_url": (p.get("repository") or {}).get("remote_url"),
        }
        for p in data
    ]
