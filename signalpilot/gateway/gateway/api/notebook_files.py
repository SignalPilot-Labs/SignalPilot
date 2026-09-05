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
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ..auth import DBSession, OrgID, UserID
from ..security.scope_guard import RequireScope
from ..workspace_store import WorkspaceStore
from ..workspace_store.store import RevisionNotFound, Upsert
from .deps import NotebookSessionsGate, StoreD
from .workspace_files import (
    WorkspaceStoreD,
    _confined,
    _require_project,
    _valid_branch,
)

router = APIRouter(prefix="/api", dependencies=[NotebookSessionsGate])

NOTEBOOK_EXTENSIONS = {".py", ".md", ".qmd"}
IGNORE_NAMES = {"__pycache__", ".git", "node_modules", ".venv", "target"}
_DIR_PLACEHOLDER = ".gitkeep"

# Default content for a freshly created, empty notebook (mirrors the shape
# SpConvert emits for an empty app; __generated_with is stamped on first save).
_EMPTY_NOTEBOOK_PY = '''import signalpilot as sp

app = sp.App()


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
'''


# ── Request models (camelCase wire format, matching msgspec rename="camel") ──


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class NbFileListRequest(_CamelModel):
    path: str | None = None
    recursive: bool = False


class NbFileDetailsRequest(_CamelModel):
    path: str


class NbFileDeleteRequest(_CamelModel):
    path: str


class NbFileMoveRequest(_CamelModel):
    path: str
    new_path: str


class NbFileUpdateRequest(_CamelModel):
    path: str
    contents: str


class NbFileSearchRequest(_CamelModel):
    query: str
    path: str | None = None
    include_directories: bool = True
    include_files: bool = True
    depth: int = 3
    limit: int = 100


# ── Helpers ──────────────────────────────────────────────────────────────────


def _rel(path: str | None) -> str:
    """Normalize a client-supplied path to a confined store-relative path.

    The editor in gateway mode only ever holds store-relative paths (the root
    is ""), but be liberal about leading slashes and backslashes; traversal
    outside the project root is rejected exactly like workspace_files."""
    if path is None:
        return ""
    p = str(path).replace("\\", "/").strip().lstrip("/")
    if p in ("", "."):
        return ""
    return _confined(p)


def _file_info(
    rel: str,
    *,
    is_directory: bool = False,
    last_modified: float | None = None,
    children: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    name = rel.rstrip("/").rsplit("/", 1)[-1] if rel else ""
    ext = posixpath.splitext(name)[1].lower()
    return {
        "id": rel,
        "path": rel,
        "name": name,
        "isDirectory": is_directory,
        "isSpFile": (not is_directory) and ext in NOTEBOOK_EXTENSIONS,
        "lastModified": last_modified,
        "children": children if children is not None else [],
    }


async def _entries(
    ws: WorkspaceStore, db, *, org_id: str, project_id: str, branch: str
) -> list[Any]:
    """All manifest entries at head; [] when the branch has no revisions."""
    try:
        manifest = await ws.load_manifest(
            db, org_id=org_id, project_id=project_id, branch=branch
        )
    except RevisionNotFound:
        return []
    return list(manifest.entries)


def _under_prefix(entries: list[Any], prefix: str) -> list[Any]:
    if not prefix:
        return list(entries)
    wanted = prefix.rstrip("/") + "/"
    return [e for e in entries if e.path.startswith(wanted)]


def _list_one_level(entries: list[Any], prefix: str) -> list[dict[str, Any]]:
    strip = f"{prefix}/" if prefix else ""
    dirs: dict[str, float | None] = {}
    files: list[dict[str, Any]] = []
    for entry in entries:
        rel = entry.path
        if strip:
            if not rel.startswith(strip):
                continue
            rel = rel[len(strip):]
        if not rel:
            continue
        name = rel.split("/", 1)[0]
        if name in IGNORE_NAMES:
            continue
        child = f"{prefix}/{name}" if prefix else name
        mtime = entry.mtime or None
        if "/" in rel:
            prev = dirs.get(child)
            if child not in dirs or (mtime and mtime > (prev or 0)):
                dirs[child] = mtime
        elif name != _DIR_PLACEHOLDER:
            files.append(_file_info(child, last_modified=mtime))

    dir_infos = [
        _file_info(d, is_directory=True, last_modified=dirs[d]) for d in sorted(dirs)
    ]
    files.sort(key=lambda info: str(info["name"]).lower())
    return dir_infos + files


def _build_tree(entries: list[Any], prefix: str) -> list[dict[str, Any]]:
    """Assemble the full nested subtree under ``prefix`` in one pass, so a
    fully expanded file tree costs ONE round trip (RequestingTree contract)."""
    strip = f"{prefix}/" if prefix else ""
    dir_nodes: dict[str, dict[str, Any]] = {}
    root_children: list[dict[str, Any]] = []

    def parent_children(parent_rel: str) -> list[dict[str, Any]]:
        if not parent_rel:
            return root_children
        node = dir_nodes.get(parent_rel)
        if node is None:
            # Materialize missing ancestor directories bottom-up.
            grand, _, _name = parent_rel.rpartition("/")
            full = f"{prefix}/{parent_rel}" if prefix else parent_rel
            node = _file_info(full, is_directory=True)
            dir_nodes[parent_rel] = node
            parent_children(grand).append(node)
        return node["children"]

    for entry in entries:
        rel = entry.path
        if strip:
            if not rel.startswith(strip):
                continue
            rel = rel[len(strip):]
        if not rel:
            continue
        parts = rel.split("/")
        if any(p in IGNORE_NAMES for p in parts):
            continue
        name = parts[-1]
        if name == _DIR_PLACEHOLDER:
            parent_children("/".join(parts[:-1]))
            continue
        full = f"{prefix}/{rel}" if prefix else rel
        parent_children("/".join(parts[:-1])).append(
            _file_info(full, last_modified=entry.mtime or None)
        )

    def sort_level(children: list[dict[str, Any]]) -> None:
        children.sort(key=lambda i: (not i["isDirectory"], str(i["name"]).lower()))
        for child in children:
            if child["isDirectory"]:
                sort_level(child["children"])

    sort_level(root_children)
    return root_children


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
        return {"file": _file_info("", is_directory=True), "contents": None,
                "mimeType": None, "isBase64": False}
    result = await ws.read_file(
        db, org_id=org_id, project_id=project_id, branch=branch, path=rel
    )
    if result is None:
        entries = await _entries(
            ws, db, org_id=org_id, project_id=project_id, branch=branch
        )
        if _under_prefix(entries, rel):
            return {"file": _file_info(rel, is_directory=True), "contents": None,
                    "mimeType": None, "isBase64": False}
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
            raise ValueError(
                f"Invalid name {name!r}: must not contain path separators "
                "or refer to a parent directory"
            )
        parent = _rel(path)
        rel = f"{parent}/{name}" if parent else name

        if file_type == "directory":
            # The manifest has no empty directories; commit a placeholder.
            await ws.commit_at_head(
                db, org_id=org_id, project_id=project_id, branch=branch,
                upserts=[Upsert(path=f"{rel}/{_DIR_PLACEHOLDER}", content=b"")],
                deletes=[], created_by=user_id, message=f"create {rel}/",
            )
            return {"success": True, "message": None,
                    "info": _file_info(rel, is_directory=True)}

        body = contents or b""
        if file_type == "notebook" and not contents:
            if posixpath.splitext(name)[1].lower() not in (".md", ".qmd"):
                body = _EMPTY_NOTEBOOK_PY.encode("utf-8")
        await ws.commit_at_head(
            db, org_id=org_id, project_id=project_id, branch=branch,
            upserts=[Upsert(path=rel, content=body)], deletes=[],
            created_by=user_id, message=f"create {rel}",
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
        entries = await _entries(
            ws, db, org_id=org_id, project_id=project_id, branch=branch
        )
        by_path = {e.path for e in entries}
        if rel in by_path:
            deletes = [rel]
        else:
            deletes = [e.path for e in _under_prefix(entries, rel)]
            if not deletes:
                return {"success": False, "message": f"File not found: {rel}"}
        await ws.commit_at_head(
            db, org_id=org_id, project_id=project_id, branch=branch,
            upserts=[], deletes=deletes, created_by=user_id,
            message=f"delete {rel}",
        )
        return {"success": True, "message": None}
    except HTTPException:
        raise
    except Exception as exc:
        return {"success": False, "message": str(exc)}


async def _copy_or_move(
    project_id: str,
    body: NbFileMoveRequest,
    org_id: str,
    user_id: str,
    db,
    ws: WorkspaceStore,
    branch: str,
    *,
    move: bool,
):
    verb = "move" if move else "copy"
    try:
        source = _rel(body.path)
        destination = _rel(body.new_path)
        if not source or not destination:
            return {"success": False, "message": "Source and destination required",
                    "info": None}
        try:
            await ws.copy_file(
                db, org_id=org_id, project_id=project_id, branch=branch,
                source=source, destination=destination, created_by=user_id,
                move=move,
            )
            return {"success": True, "message": None, "info": _file_info(destination)}
        except FileNotFoundError:
            pass  # not a file — try a directory copy/move below
        except RevisionNotFound:
            return {"success": False, "message": f"File not found: {source}",
                    "info": None}
        # Directory copy/move: one batch of reference upserts (+ deletes).
        entries = _under_prefix(
            await _entries(ws, db, org_id=org_id, project_id=project_id, branch=branch),
            source,
        )
        if not entries:
            return {"success": False, "message": f"File not found: {source}",
                    "info": None}
        upserts = [
            Upsert(
                path=f"{destination}/{e.path[len(source) + 1:]}",
                sha256=e.sha256, size=e.size, mode=e.mode, mtime=e.mtime,
            )
            for e in entries
        ]
        deletes = [e.path for e in entries] if move else []
        await ws.commit_at_head(
            db, org_id=org_id, project_id=project_id, branch=branch,
            upserts=upserts, deletes=deletes, created_by=user_id,
            message=f"{verb} {source} -> {destination}",
        )
        return {"success": True, "message": None,
                "info": _file_info(destination, is_directory=True)}
    except HTTPException:
        raise
    except Exception as exc:
        return {"success": False, "message": str(exc), "info": None}


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
    return await _copy_or_move(
        project_id, body, org_id, user_id, db, ws, _valid_branch(branch), move=False
    )


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
    return await _copy_or_move(
        project_id, body, org_id, user_id, db, ws, _valid_branch(branch), move=True
    )


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
            db, org_id=org_id, project_id=project_id, branch=branch,
            upserts=[Upsert(path=rel, content=body.contents.encode("utf-8"))],
            deletes=[], created_by=user_id, message=f"put {rel}",
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
    entries = await _entries(
        ws, db, org_id=org_id, project_id=project_id, branch=branch
    )
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
            0
            if str(info["name"]).lower() == needle
            else 1
            if str(info["name"]).lower().startswith(needle)
            else 2,
            str(info["name"]),
        )
    )
    results = results[: body.limit]
    return {"files": results, "query": body.query, "totalFound": len(results)}
