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
