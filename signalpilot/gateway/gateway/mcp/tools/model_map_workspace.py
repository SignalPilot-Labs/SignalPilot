"""Resolve a dbt `project_dir` for the project-reading MCP tools.

map_columns and find_column_producers read model SQL and YML from disk. In a
chat session the agent's project lives in its sandbox, which the gateway
cannot read. The session JWT pins the project and branch, and the sandbox
checkout is the workspace snapshot of that branch, so the gateway extracts
the same snapshot into a local cache and reads the same files there.

The agent's sandbox path only selects the dbt directory inside the snapshot:
the longest path suffix that names a directory with a dbt_project.yml.
"""

from __future__ import annotations

import asyncio
import io
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from gateway.mcp.context import (
    _store_session,
    mcp_branch_var,
    mcp_org_id_var,
    mcp_project_id_var,
)
from gateway.mcp.tools.model_map import _PROJECT_DIR_MAX_LEN, _validated_project_dir

_CACHE_ROOT = Path(tempfile.gettempdir()) / "sp-model-map"
_locks: dict[tuple[str, str, int], asyncio.Lock] = {}


def _extract(tarball: bytes, destination: Path) -> None:
    """Extract into a sibling temp dir, then rename, so a reader never sees a
    half-written tree. Older revisions of the same project are removed."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(tempfile.mkdtemp(dir=destination.parent, prefix=".partial-"))
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:*") as tar:
            for member in tar.getmembers():
                name = member.name.replace("\\", "/")
                if name.startswith(("/", "../")) or "/../" in name or member.islnk() or member.issym():
                    raise ValueError(f"Unsafe member in snapshot tarball: {member.name!r}")
            tar.extractall(partial, filter="data")
        partial.rename(destination)
    finally:
        shutil.rmtree(partial, ignore_errors=True)
    for sibling in destination.parent.iterdir():
        if sibling != destination and not sibling.name.startswith(".partial-"):
            shutil.rmtree(sibling, ignore_errors=True)


async def _snapshot_directory(org_id: str, project_id: str, branch: str) -> Path | None:
    """Local extracted copy of the branch head snapshot, cached per revision."""
    from gateway.workspace_store import workspace_object_storage
    from gateway.workspace_store.store import WorkspaceStore

    storage = workspace_object_storage()
    if not storage.enabled:
        return None
    async with _store_session() as store:
        revision, key = await WorkspaceStore(storage).build_snapshot(
            store.session, org_id=org_id, project_id=project_id, branch=branch
        )
    safe_branch = "".join(c if c.isalnum() or c in "-_." else "_" for c in branch)
    destination = _CACHE_ROOT / org_id / project_id / safe_branch / f"rev-{revision}"
    lock = _locks.setdefault((project_id, safe_branch, revision), asyncio.Lock())
    async with lock:
        if not destination.is_dir():
            tarball = await storage.get_bytes(key)
            if tarball is None:
                return None
            await asyncio.to_thread(_extract, tarball, destination)
    return destination


def _dbt_directory(snapshot: Path, project_dir: str) -> Path | None:
    parts = [p for p in PurePosixPath(project_dir.replace("\\", "/")).parts if p not in ("/", "..", ".")]
    for start in range(len(parts)):
        candidate = snapshot.joinpath(*parts[start:])
        if (candidate / "dbt_project.yml").is_file():
            return candidate
    if (snapshot / "dbt_project.yml").is_file():
        return snapshot
    found = [p.parent for p in snapshot.glob("*/dbt_project.yml")]
    return found[0] if len(found) == 1 else None


async def resolve_project_dir(project_dir: str) -> tuple[Path | None, str | None]:
    """(directory, None) to read, or (None, error). Paths the gateway can
    read are validated as before; a session pinned to a project falls back
    to that project's snapshot."""
    work_dir, err = _validated_project_dir(project_dir)
    if err is None:
        return work_dir, None
    project_id = mcp_project_id_var.get(None)
    org_id = mcp_org_id_var.get(None)
    if not project_id or not org_id or not project_dir or len(project_dir) > _PROJECT_DIR_MAX_LEN:
        return None, err
    branch = mcp_branch_var.get(None) or "main"
    try:
        snapshot = await _snapshot_directory(org_id, project_id, branch)
    except Exception:
        return None, err
    if snapshot is None:
        return None, err
    dbt_dir = _dbt_directory(snapshot, project_dir)
    if dbt_dir is None:
        return None, f"Error: no dbt_project.yml found for project_dir '{project_dir}' in the project snapshot."
    return dbt_dir, None
