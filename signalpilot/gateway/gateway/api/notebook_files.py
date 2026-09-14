"""Notebook-editor file plane, served directly by the gateway.

Compat router for the notebook editor's file tree and file editors: the SAME
request/response JSON shapes as the notebook-server file explorer endpoints
(`signalpilot/_server/api/endpoints/file_explorer.py`, msgspec camelCase),
but implemented directly against the S3-backed WorkspaceStore — no notebook
session, no sandbox, no proxy hop. This is what lets the editor load and
browse/edit project files before any kernel exists.

Mounted under /api/workspace-projects/{project_id}/nb-files/*. Auth, branch
validation, project resolution (404/410 tombstone) and path confinement are
shared with — and identical to — gateway/api/workspace_files.py.

Semantics are a server-side port of the notebook-server's GatewayFileSystem
(signalpilot/_server/files/gateway_file_system.py): the manifest has no empty
directories, so directories materialize from path prefixes and a `.gitkeep`
placeholder file represents an empty one.
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
import posixpath
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..auth import DBSession, OrgID, UserID
from ..security.scope_guard import RequireScope
from ..workspace_store.store import Upsert
from .deps import RequireBillablePlan, StoreD
from .notebook_files_tree import (
    _DIR_PLACEHOLDER,
    IGNORE_NAMES,  # noqa: F401  (re-export)
    NOTEBOOK_EXTENSIONS,  # noqa: F401  (re-export)
    NbFileDeleteRequest,
    NbFileDetailsRequest,
    NbFileListRequest,
    NbFileMoveRequest,
    NbFileSearchRequest,
    NbFileUpdateRequest,
    _build_tree,
    _copy_or_move,
    _entries,
    _file_info,
    _list_one_level,
    _rel,
    _under_prefix,
)
from .workspace_files import (
    WorkspaceStoreD,
    _require_project,
    _valid_branch,
)

router = APIRouter(prefix="/api", dependencies=[RequireBillablePlan])


# Default content for a freshly created, empty notebook (mirrors the shape
# SpConvert emits for an empty app; __generated_with is stamped on first save).
_EMPTY_NOTEBOOK_PY = """import signalpilot as sp

app = sp.App()


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
"""


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post(
    "/workspace-projects/{project_id}/nb-files/list_files",
    dependencies=[RequireScope("read")],
)
async def list_files(
    project_id: str,
    body: NbFileListRequest,
    org_id: OrgID,
    _user: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
    branch: str = Query("main"),
):
    await _require_project(store, ws, db, project_id)
    branch = _valid_branch(branch)
    prefix = _rel(body.path)
    entries = _under_prefix(
        await _entries(ws, db, org_id=org_id, project_id=project_id, branch=branch),
        prefix,
    )
    files = _build_tree(entries, prefix) if body.recursive else _list_one_level(entries, prefix)
    return {"files": files, "root": body.path or ""}


@router.post(
    "/workspace-projects/{project_id}/nb-files/file_details",
    dependencies=[RequireScope("read")],
)
async def file_details(
    project_id: str,
    body: NbFileDetailsRequest,
    org_id: OrgID,
    _user: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
    branch: str = Query("main"),
):
    await _require_project(store, ws, db, project_id)
    branch = _valid_branch(branch)
    rel = _rel(body.path)
    if not rel:
        return {"file": _file_info("", is_directory=True), "contents": None, "mimeType": None, "isBase64": False}
    result = await ws.read_file(db, org_id=org_id, project_id=project_id, branch=branch, path=rel)
    if result is None:
        entries = await _entries(ws, db, org_id=org_id, project_id=project_id, branch=branch)
        if _under_prefix(entries, rel):
            return {"file": _file_info(rel, is_directory=True), "contents": None, "mimeType": None, "isBase64": False}
        raise HTTPException(status_code=404, detail=f"File not found: {rel}")
    entry, raw = result
    is_base64 = False
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = base64.b64encode(raw).decode("utf-8")
        is_base64 = True
    return {
        "file": _file_info(rel, last_modified=entry.mtime or None),
        "contents": text,
        "mimeType": mimetypes.guess_type(rel)[0] or "text/plain",
        "isBase64": is_base64,
    }


@router.post(
    "/workspace-projects/{project_id}/nb-files/create",
    dependencies=[RequireScope("write")],
)
async def create_file_or_directory(
    project_id: str,
    request: Request,
    org_id: OrgID,
    user_id: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
    branch: str = Query("main"),
):
    await _require_project(store, ws, db, project_id)
    branch = _valid_branch(branch)
    try:
        content_type = request.headers.get("content-type", "")
        contents: bytes | None
        if content_type.startswith("multipart/"):
            form = await request.form()
            path = str(form.get("path") or "")
            file_type = str(form.get("type") or "file")
            name = str(form.get("name") or "")
            upload = form.get("file")
            if upload is None:
                contents = None
            elif hasattr(upload, "read"):
                contents = await upload.read()  # type: ignore[union-attr]
            else:
                contents = str(upload).encode("utf-8")
        else:
            data = await request.json()
            path = str(data.get("path") or "")
            file_type = str(data.get("type") or "file")
            name = str(data.get("name") or "")
            b64 = data.get("contents")
            try:
                contents = base64.b64decode(b64) if b64 else None
            except (binascii.Error, ValueError):
                raise ValueError("Invalid base64 contents")

        if file_type not in ("file", "directory", "notebook"):
            raise ValueError(f"Invalid type {file_type!r}")
        if not name.strip():
            raise ValueError("Cannot create file or directory with empty name")
        if "/" in name or "\\" in name or "\x00" in name or name in (".", ".."):
            raise ValueError(f"Invalid name {name!r}: must not contain path separators or refer to a parent directory")
        parent = _rel(path)
        rel = f"{parent}/{name}" if parent else name

        if file_type == "directory":
            # The manifest has no empty directories; commit a placeholder.
            await ws.commit_at_head(
                db,
                org_id=org_id,
                project_id=project_id,
                branch=branch,
                upserts=[Upsert(path=f"{rel}/{_DIR_PLACEHOLDER}", content=b"")],
                deletes=[],
                created_by=user_id,
                message=f"create {rel}/",
            )
            return {"success": True, "message": None, "info": _file_info(rel, is_directory=True)}

        body = contents or b""
        if file_type == "notebook" and not contents:
            if posixpath.splitext(name)[1].lower() not in (".md", ".qmd"):
                body = _EMPTY_NOTEBOOK_PY.encode("utf-8")
        await ws.commit_at_head(
            db,
            org_id=org_id,
            project_id=project_id,
            branch=branch,
            upserts=[Upsert(path=rel, content=body)],
            deletes=[],
            created_by=user_id,
            message=f"create {rel}",
        )
        return {"success": True, "message": None, "info": _file_info(rel)}
    except HTTPException:
        raise
    except Exception as exc:  # match notebook-server: 200 + success:false
        return {"success": False, "message": str(exc), "info": None}


@router.post(
    "/workspace-projects/{project_id}/nb-files/delete",
    dependencies=[RequireScope("write")],
)
async def delete_file_or_directory(
    project_id: str,
    body: NbFileDeleteRequest,
    org_id: OrgID,
    user_id: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
    branch: str = Query("main"),
):
    await _require_project(store, ws, db, project_id)
    branch = _valid_branch(branch)
    try:
        rel = _rel(body.path)
        if not rel:
            return {"success": False, "message": "Cannot delete the project root"}
        entries = await _entries(ws, db, org_id=org_id, project_id=project_id, branch=branch)
        by_path = {e.path for e in entries}
        if rel in by_path:
            deletes = [rel]
        else:
            deletes = [e.path for e in _under_prefix(entries, rel)]
            if not deletes:
                return {"success": False, "message": f"File not found: {rel}"}
        await ws.commit_at_head(
            db,
            org_id=org_id,
            project_id=project_id,
            branch=branch,
            upserts=[],
            deletes=deletes,
            created_by=user_id,
            message=f"delete {rel}",
        )
        return {"success": True, "message": None}
    except HTTPException:
        raise
    except Exception as exc:
        return {"success": False, "message": str(exc)}


@router.post(
    "/workspace-projects/{project_id}/nb-files/copy",
    dependencies=[RequireScope("write")],
)
async def copy_file_or_directory(
    project_id: str,
    body: NbFileMoveRequest,
    org_id: OrgID,
    user_id: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
    branch: str = Query("main"),
):
    await _require_project(store, ws, db, project_id)
    return await _copy_or_move(project_id, body, org_id, user_id, db, ws, _valid_branch(branch), move=False)


@router.post(
    "/workspace-projects/{project_id}/nb-files/move",
    dependencies=[RequireScope("write")],
)
async def move_file_or_directory(
    project_id: str,
    body: NbFileMoveRequest,
    org_id: OrgID,
    user_id: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
    branch: str = Query("main"),
):
    await _require_project(store, ws, db, project_id)
    return await _copy_or_move(project_id, body, org_id, user_id, db, ws, _valid_branch(branch), move=True)


@router.post(
    "/workspace-projects/{project_id}/nb-files/update",
    dependencies=[RequireScope("write")],
)
async def update_file(
    project_id: str,
    body: NbFileUpdateRequest,
    org_id: OrgID,
    user_id: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
    branch: str = Query("main"),
):
    await _require_project(store, ws, db, project_id)
    branch = _valid_branch(branch)
    try:
        rel = _rel(body.path)
        if not rel:
            return {"success": False, "message": "A file path is required", "info": None}
        await ws.commit_at_head(
            db,
            org_id=org_id,
            project_id=project_id,
            branch=branch,
            upserts=[Upsert(path=rel, content=body.contents.encode("utf-8"))],
            deletes=[],
            created_by=user_id,
            message=f"put {rel}",
        )
        return {"success": True, "message": None, "info": _file_info(rel)}
    except HTTPException:
        raise
    except Exception as exc:
        return {"success": False, "message": str(exc), "info": None}


@router.post(
    "/workspace-projects/{project_id}/nb-files/search",
    dependencies=[RequireScope("read")],
)
async def search_files(
    project_id: str,
    body: NbFileSearchRequest,
    org_id: OrgID,
    _user: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
    branch: str = Query("main"),
):
    await _require_project(store, ws, db, project_id)
    branch = _valid_branch(branch)
    query = body.query.strip()
    if not query:
        return {"files": [], "query": body.query, "totalFound": 0}
    entries = await _entries(ws, db, org_id=org_id, project_id=project_id, branch=branch)
    prefix_rel = _rel(body.path)
    prefix = f"{prefix_rel}/" if prefix_rel else ""
    needle = query.lower()
    results: list[dict[str, Any]] = []
    seen_dirs: set[str] = set()
    for entry in entries:
        rel = entry.path
        if prefix and not rel.startswith(prefix):
            continue
        if needle not in rel.lower():
            continue
        if body.include_files and needle in rel.rsplit("/", 1)[-1].lower():
            results.append(_file_info(rel, last_modified=entry.mtime or None))
        if body.include_directories:
            parts = rel.split("/")[:-1]
            for i, part in enumerate(parts):
                if needle in part.lower():
                    dir_path = "/".join(parts[: i + 1])
                    if dir_path not in seen_dirs:
                        seen_dirs.add(dir_path)
                        results.append(_file_info(dir_path, is_directory=True))
    results.sort(
        key=lambda info: (
            0 if str(info["name"]).lower() == needle else 1 if str(info["name"]).lower().startswith(needle) else 2,
            str(info["name"]),
        )
    )
    results = results[: body.limit]
    return {"files": results, "query": body.query, "totalFound": len(results)}
