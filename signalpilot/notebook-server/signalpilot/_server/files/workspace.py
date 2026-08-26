"""Workspace filesystem selection — the single construction site.

Notebook Runtime v2: when ``SP_WORKSPACE_MODE=s3`` (set by the gateway's
Vercel notebook backend) all workspace file access goes through the gateway
Workspace Files API backed by S3. Reads pull on demand; every save is a
write-through commit (a new revision). Disk is never the truth.

In any other mode the server behaves as a plain local editor over
:class:`OSFileSystem` (``sp edit ./``).

``PROJECTS_ROOT`` is the disposable scratch area where *execution* may
materialize files on demand (frozen standalone-chat checkouts, analysis
artifacts). Nothing under it is durable.
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from signalpilot._server.files.file_system import FileSystem

S3_WORKSPACE_MODE = "s3"

# Disposable materialization root for execution scratch. Never the truth.
PROJECTS_ROOT = Path.home() / ".sp" / "projects"

_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")

_branch_lock = threading.Lock()
_current_branch: str | None = None


def validate_branch(branch: str) -> None:
    """Reject branch names the gateway would refuse (also blocks injection)."""
    if not branch or branch.startswith("-") or ".." in branch or not _BRANCH_RE.match(branch):
        raise ValueError(f"Invalid branch name: {branch!r}")


def workspace_mode() -> str:
    return os.environ.get("SP_WORKSPACE_MODE", "").strip().lower()


def is_s3_workspace() -> bool:
    return workspace_mode() == S3_WORKSPACE_MODE


def is_read_only_workspace() -> bool:
    """Whether this session may commit revisions.

    Set by the gateway backend (SP_PROJECT_READ_ONLY=1) for viewer sessions.
    Enforced at the GatewayFileSystem mutation funnel so every write path —
    saves, batch ops, renames — fails closed with one error.
    """
    return os.environ.get("SP_PROJECT_READ_ONLY", "").strip() in {"1", "true", "yes", "on"}


def current_branch() -> str:
    """The branch this session is working on (initially ``SP_BRANCH``)."""
    global _current_branch
    with _branch_lock:
        if _current_branch is None:
            _current_branch = os.environ.get("SP_BRANCH", "").strip() or "main"
        return _current_branch


def set_current_branch(branch: str) -> None:
    """Switch the session's working branch.

    S3 holds every branch, so switching is nothing more than constructing
    the next :class:`GatewayFileSystem` against a different branch name.
    """
    global _current_branch
    validate_branch(branch)
    with _branch_lock:
        _current_branch = branch


def create_file_system(
    *,
    branch: str | None = None,
    root: str | None = None,
) -> FileSystem:
    """THE construction site for workspace file systems.

    ``SP_WORKSPACE_MODE=s3`` → :class:`GatewayFileSystem` against
    ``SP_GATEWAY_URL`` / ``SP_PROJECT_ID`` with the session JWT.
    Anything else → :class:`OSFileSystem` (optionally rooted at ``root``).
    """
    if is_s3_workspace():
        from signalpilot._server.auth.session_token import load_session_jwt
        from signalpilot._server.files.gateway_file_system import (
            GatewayFileSystem,
        )

        project_id = os.environ.get("SP_PROJECT_ID", "").strip()
        if not project_id:
            raise RuntimeError("SP_WORKSPACE_MODE=s3 requires SP_PROJECT_ID")
        gateway_url = (
            os.environ.get("SP_GATEWAY_URL", "").strip()
            or "http://localhost:3300"
        )
        token = load_session_jwt() or os.environ.get("SP_API_KEY", "")
        return GatewayFileSystem(
            gateway_url=gateway_url,
            token=token,
            project_id=project_id,
            branch=branch or current_branch(),
        )

    from signalpilot._server.files.os_file_system import OSFileSystem

    return OSFileSystem(root=root)


# ── Session-file read-through / write-through (S3 mode) ─────────────────────
#
# The marimo session machinery (AppFileManager, session cache, kernels) opens
# notebooks from disk paths. In S3 mode the workspace directory is a
# read-through cache: opening a notebook materializes its bytes (and the
# __sp__ session sidecar that powers reconnect) on demand, and every save
# writes through as a new revision. Disk is never the truth.


def _session_rel(path: str | Path, root: Path) -> str | None:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        candidate = Path(path)
        if not candidate.is_absolute():
            return candidate.as_posix()
        return None


def _sidecar_rel(rel: str) -> str:
    name = rel.rsplit("/", 1)[-1]
    parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
    prefix = f"{parent}/" if parent else ""
    return f"{prefix}__sp__/session/{name}.json"


def materialize_for_session(path: str | Path, *, root: str | Path | None = None) -> Path | None:
    """Read-through: pull one notebook (and its session sidecar) from the S3
    workspace into the local cache directory. Returns the local path, or None
    when the file does not exist in the workspace (or S3 mode is off)."""
    if not is_s3_workspace():
        return None
    base = Path(root) if root is not None else Path(os.getcwd())
    rel = _session_rel(path, base)
    if rel is None:
        return None

    fs = create_file_system()
    content = fs.read_bytes(rel)
    if content is None:
        return None
    local = base / rel
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(content)

    sidecar = fs.read_bytes(_sidecar_rel(rel))
    if sidecar is not None:
        sidecar_local = base / _sidecar_rel(rel)
        sidecar_local.parent.mkdir(parents=True, exist_ok=True)
        sidecar_local.write_bytes(sidecar)
    return local


def write_through_paths(
    paths: list[str],
    *,
    root: str | Path | None = None,
    message: str | None = None,
) -> None:
    """Write-through several local files as one committed revision.

    Used by generators (dbt scaffold) whose output must be durable, not a
    cache-only tree that evaporates with the sandbox. No-op outside S3 mode.
    """
    if not is_s3_workspace():
        return
    base = Path(root) if root is not None else Path(os.getcwd())
    files: dict[str, bytes] = {}
    for path in paths:
        rel = _session_rel(path, base)
        if rel is None:
            continue
        local = base / rel
        if local.is_file():
            files[rel] = local.read_bytes()
    if files:
        create_file_system().write_many(files, message=message)


def rename_through_session_file(
    old_path: str | Path,
    new_path: str | Path,
    *,
    root: str | Path | None = None,
) -> None:
    """Write-through a rename: commit the file at its new path and remove the
    old one from the workspace store. No-op outside S3 mode."""
    if not is_s3_workspace():
        return
    base = Path(root) if root is not None else Path(os.getcwd())
    old_rel = _session_rel(old_path, base)
    new_rel = _session_rel(new_path, base)
    if new_rel is not None:
        write_through_session_file(new_path, root=base)
    if old_rel is not None and old_rel != new_rel:
        fs = create_file_system()
        try:
            fs.delete_file_or_directory(old_rel)
        except Exception:
            # The old path may never have been committed (new unsaved file).
            pass
        sidecar = _sidecar_rel(old_rel)
        try:
            fs.delete_file_or_directory(sidecar)
        except Exception:
            pass


def write_through_session_file(path: str | Path, *, root: str | Path | None = None) -> None:
    """Write-through: push one locally written file to the S3 workspace.
    A save either commits (durable revision) or raises — no silent loss."""
    if not is_s3_workspace():
        return
    base = Path(root) if root is not None else Path(os.getcwd())
    rel = _session_rel(path, base)
    if rel is None:
        return
    local = base / rel
    if not local.is_file():
        return
    create_file_system().write_bytes(rel, local.read_bytes())
