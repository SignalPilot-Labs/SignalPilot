"""User workspace endpoints — per-user flat file backup on S3.

Not git. Just the latest state of the user's working directory, including
uncommitted changes and runtime state. Used for fast VM restore.

S3 layout: workspaces/{org_id}/{user_id}/{project_id}/{path}
"""

import time

from fastapi import APIRouter, HTTPException, Query, Request, Response

from ..security.scope_guard import RequireScope
from .deps import S3D, StoreD

router = APIRouter(prefix="/api/workspaces")


async def _verify_project_access(store: StoreD, project_id: str) -> None:
    """Verify the project exists and belongs to the caller's org."""
    proj = await store.get_workspace_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")


def _ws_prefix(org_id: str, user_id: str, project_id: str) -> str:
    return f"workspaces/{org_id}/{user_id}/{project_id}"


def _detect_content_type(path: str) -> str:
    if path.endswith(".json"):
        return "application/json"
    if path.endswith(".yml") or path.endswith(".yaml"):
        return "text/yaml"
    if path.endswith(".py"):
        return "text/x-python"
    if path.endswith(".sql"):
        return "text/sql"
    if path.endswith(".csv"):
        return "text/csv"
    if path.endswith(".md"):
        return "text/markdown"
    return "application/octet-stream"


@router.get("/{project_id}/files", dependencies=[RequireScope("read")])
async def list_files(
    project_id: str,
    store: StoreD,
    s3: S3D,
    prefix: str = Query("", max_length=500),
):
    """List files in the user's workspace for this project."""
    await _verify_project_access(store, project_id)
    org_id = store.org_id or "local"
    user_id = store.user_id or "local"
    ws = _ws_prefix(org_id, user_id, project_id)
    s3_prefix = f"{ws}/{prefix}" if prefix else ws

    objects = await s3.list_objects(s3_prefix, max_keys=5000)
    strip = f"{ws}/"
    files = [
        {"key": o["key"][len(strip):] if o["key"].startswith(strip) else o["key"],
         "size": o["size"], "last_modified": o["last_modified"]}
        for o in objects
    ]
    return {"project_id": project_id, "user_id": user_id, "files": files}


@router.get("/{project_id}/files/{file_path:path}", dependencies=[RequireScope("read")])
async def read_file(project_id: str, file_path: str, store: StoreD, s3: S3D):
    """Read a file from the user's workspace."""
    await _verify_project_access(store, project_id)
    org_id = store.org_id or "local"
    user_id = store.user_id or "local"
    ws = _ws_prefix(org_id, user_id, project_id)
    try:
        data = await s3.get_object(f"{ws}/{file_path}")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    return Response(content=data, media_type=_detect_content_type(file_path))


@router.put("/{project_id}/files/{file_path:path}", status_code=201, dependencies=[RequireScope("write")])
async def write_file(project_id: str, file_path: str, request: Request, store: StoreD, s3: S3D):
    """Write a file to the user's workspace."""
    await _verify_project_access(store, project_id)
    org_id = store.org_id or "local"
    user_id = store.user_id or "local"
    ws = _ws_prefix(org_id, user_id, project_id)
    body = await request.body()
    ct = request.headers.get("content-type", "application/octet-stream")
    key = await s3.put_object(f"{ws}/{file_path}", body, ct)
    return {"key": file_path, "size": len(body)}


@router.delete("/{project_id}/files/{file_path:path}", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_file(project_id: str, file_path: str, store: StoreD, s3: S3D):
    """Delete a file from the user's workspace."""
    await _verify_project_access(store, project_id)
    org_id = store.org_id or "local"
    user_id = store.user_id or "local"
    ws = _ws_prefix(org_id, user_id, project_id)
    await s3.delete_object(f"{ws}/{file_path}")


@router.get("/{project_id}/status", dependencies=[RequireScope("read")])
async def workspace_status(project_id: str, store: StoreD, s3: S3D):
    """Check if a workspace exists and its size. Used by notebook to decide: restore vs clone."""
    await _verify_project_access(store, project_id)
    org_id = store.org_id or "local"
    user_id = store.user_id or "local"
    ws = _ws_prefix(org_id, user_id, project_id)

    objects = await s3.list_objects(ws, max_keys=5000)
    if not objects:
        return {"exists": False, "file_count": 0, "total_bytes": 0, "last_modified": None}

    total_bytes = sum(o["size"] for o in objects)
    last_modified = max(o["last_modified"] for o in objects)
    return {
        "exists": True,
        "file_count": len(objects),
        "total_bytes": total_bytes,
        "last_modified": last_modified,
    }


@router.delete("/{project_id}", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def clear_workspace(project_id: str, store: StoreD, s3: S3D):
    """Delete all files in the user's workspace for this project."""
    await _verify_project_access(store, project_id)
    org_id = store.org_id or "local"
    user_id = store.user_id or "local"
    ws = _ws_prefix(org_id, user_id, project_id)
    await s3.delete_prefix(ws)
