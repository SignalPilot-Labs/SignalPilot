"""File browser endpoint — browse for local DB files under a confined root."""

from __future__ import annotations

import os
import posixpath
from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException, Query

from ..security.scope_guard import RequireScope
from .deps import StoreD, get_sandbox_client_with_store

router = APIRouter(prefix="/api")

# The sandbox manager reaches the host filesystem, so the browse root bounds what
# this endpoint can enumerate. Default matches the sandbox manager's own host mount.
# Read as Class B (os.environ) so deployments and tests can point it elsewhere
# without a cached settings object.
_DEFAULT_BROWSE_ROOT = "/host-data"


def _browse_root() -> PurePosixPath:
    raw = (
        os.environ.get("SP_FILE_BROWSE_ROOT")
        or os.environ.get("SP_DATA_DIR")
        or _DEFAULT_BROWSE_ROOT
    ).strip()
    return PurePosixPath(posixpath.normpath(raw.replace("\\", "/") or _DEFAULT_BROWSE_ROOT))


def _confined_path(path: str | None) -> str | None:
    """Resolve a caller-supplied path inside the browse root, or reject it.

    No path means "let the sandbox manager pick its own default", which it
    confines on its side — forwarding a root that may not exist there would
    turn the default listing into an error.
    """
    root = _browse_root()
    if not path or not path.strip():
        return None

    candidate = path.strip().replace("\\", "/")
    if "\x00" in candidate or ".." in PurePosixPath(candidate).parts:
        raise HTTPException(status_code=400, detail="Invalid path")

    joined = candidate if candidate.startswith("/") else posixpath.join(str(root), candidate)
    resolved = PurePosixPath(posixpath.normpath(joined))
    if resolved != root and root not in resolved.parents:
        raise HTTPException(status_code=400, detail="Path is outside the permitted browse root")
    return str(resolved)


def _safe_pattern(pattern: str) -> str:
    if "/" in pattern or "\\" in pattern or ".." in pattern or "\x00" in pattern:
        raise HTTPException(status_code=400, detail="Invalid pattern")
    return pattern


@router.get("/files/browse", dependencies=[RequireScope("write")])
async def browse_files(
    store: StoreD,
    path: str | None = Query(default=None, max_length=4096, description="Directory to browse"),
    pattern: str = Query(default="*.duckdb", max_length=256, description="File glob pattern"),
):
    """Browse for database files under the configured browse root.

    Proxies to the sandbox manager which has host filesystem access. Returns
    files matching the pattern and subdirectories.
    """
    safe_path = _confined_path(path)
    safe_pattern = _safe_pattern(pattern)
    client = await get_sandbox_client_with_store(store)
    return await client.browse_files(path=safe_path, pattern=safe_pattern)
