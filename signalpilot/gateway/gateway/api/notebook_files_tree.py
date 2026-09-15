"""Request models and manifest-tree helpers for the notebook-editor file plane.

Split out of ``gateway/api/notebook_files.py`` (which owns the routes). The
shapes and semantics are a server-side port of the notebook-server's
GatewayFileSystem: the manifest has no empty directories, so directories
materialize from path prefixes and a ``.gitkeep`` placeholder represents an
empty one.
"""

from __future__ import annotations

import posixpath
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ..workspace_store import WorkspaceStore
from ..workspace_store.store import RevisionNotFound, Upsert
from .workspace_files import _confined

NOTEBOOK_EXTENSIONS = {".py", ".md", ".qmd"}
IGNORE_NAMES = {"__pycache__", ".git", "node_modules", ".venv", "target"}
_DIR_PLACEHOLDER = ".gitkeep"


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


async def _entries(ws: WorkspaceStore, db, *, org_id: str, project_id: str, branch: str) -> list[Any]:
    """All manifest entries at head; [] when the branch has no revisions."""
    try:
        manifest = await ws.load_manifest(db, org_id=org_id, project_id=project_id, branch=branch)
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
            rel = rel[len(strip) :]
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

    dir_infos = [_file_info(d, is_directory=True, last_modified=dirs[d]) for d in sorted(dirs)]
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
            rel = rel[len(strip) :]
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
        parent_children("/".join(parts[:-1])).append(_file_info(full, last_modified=entry.mtime or None))

    def sort_level(children: list[dict[str, Any]]) -> None:
        children.sort(key=lambda i: (not i["isDirectory"], str(i["name"]).lower()))
        for child in children:
            if child["isDirectory"]:
                sort_level(child["children"])

    sort_level(root_children)
    return root_children


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
            return {"success": False, "message": "Source and destination required", "info": None}
        try:
            await ws.copy_file(
                db,
                org_id=org_id,
                project_id=project_id,
                branch=branch,
                source=source,
                destination=destination,
                created_by=user_id,
                move=move,
            )
            return {"success": True, "message": None, "info": _file_info(destination)}
        except FileNotFoundError:
            pass  # not a file — try a directory copy/move below
        except RevisionNotFound:
            return {"success": False, "message": f"File not found: {source}", "info": None}
        # Directory copy/move: one batch of reference upserts (+ deletes).
        entries = _under_prefix(
            await _entries(ws, db, org_id=org_id, project_id=project_id, branch=branch),
            source,
        )
        if not entries:
            return {"success": False, "message": f"File not found: {source}", "info": None}
        upserts = [
            Upsert(
                path=f"{destination}/{e.path[len(source) + 1 :]}",
                sha256=e.sha256,
                size=e.size,
                mode=e.mode,
                mtime=e.mtime,
            )
            for e in entries
        ]
        deletes = [e.path for e in entries] if move else []
        await ws.commit_at_head(
            db,
            org_id=org_id,
            project_id=project_id,
            branch=branch,
            upserts=upserts,
            deletes=deletes,
            created_by=user_id,
            message=f"{verb} {source} -> {destination}",
        )
        return {"success": True, "message": None, "info": _file_info(destination, is_directory=True)}
    except HTTPException:
        raise
    except Exception as exc:
        return {"success": False, "message": str(exc), "info": None}
