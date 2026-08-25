"""dbt execution scratch for the S3 workspace (Notebook Runtime v2).

dbt is a subprocess: it needs real files. The S3 workspace has none locally,
so dbt commands materialize the branch snapshot into disposable scratch and
run there. The gateway resolves WHICH directory inside the project is the dbt
project — the org-level `dbt_project_dir` setting wins, manifest auto-detect
(shallowest, then alphabetical) otherwise.

Scratch is cached per (project, branch, revision): a new save produces a new
revision and therefore a fresh tree; older revisions of the same branch are
pruned. `target/` artifacts (manifest, run_results) live in the scratch tree
between commands at the same revision. Disk is never the truth.
"""

from __future__ import annotations

import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

import httpx

from signalpilot import _loggers
from signalpilot._server.files.workspace import (
    PROJECTS_ROOT,
    current_branch,
    is_s3_workspace,
)

LOGGER = _loggers.sp_logger()

_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


class DbtMaterializeError(RuntimeError):
    pass


def _gateway() -> tuple[str, str, str]:
    from signalpilot._server.auth.session_token import load_session_jwt

    project_id = os.environ.get("SP_PROJECT_ID", "").strip()
    if not project_id:
        raise DbtMaterializeError("SP_WORKSPACE_MODE=s3 requires SP_PROJECT_ID")
    gateway_url = os.environ.get("SP_GATEWAY_URL", "").strip() or "http://localhost:3300"
    token = load_session_jwt() or os.environ.get("SP_API_KEY", "")
    if not token:
        raise DbtMaterializeError("No gateway credential available for dbt materialization")
    return gateway_url.rstrip("/"), project_id, token


def _safe_segment(value: str) -> str:
    cleaned = _SEGMENT_RE.sub("-", value.strip()).strip("-.")
    return cleaned or "x"


def resolve_dbt_project_dir(*, branch: str | None = None) -> str | None:
    """The org-level answer to 'which directory holds the dbt project'.

    Explicit project setting wins over auto-detect — both live gateway-side
    so every member of the org compiles the same project.
    """
    gateway_url, project_id, token = _gateway()
    response = httpx.get(
        f"{gateway_url}/api/workspace-projects/{project_id}/dbt-project-dir",
        params={"branch": branch or current_branch()},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
    )
    response.raise_for_status()
    return response.json().get("dbt_project_dir")


def materialized_dbt_start_dir(*, branch: str | None = None) -> str | None:
    """Materialize the branch head into scratch; return the dbt project dir
    inside it (None when the workspace has no dbt project or no revisions)."""
    if not is_s3_workspace():
        return None
    branch = branch or current_branch()
    gateway_url, project_id, token = _gateway()

    # First-time snapshot builds for a revision run gateway-side and can take
    # tens of seconds on large projects; do not starve them.
    snapshot = httpx.get(
        f"{gateway_url}/api/workspace-projects/{project_id}/snapshot",
        params={"branch": branch},
        headers={"Authorization": f"Bearer {token}"},
        timeout=300.0,
    )
    if snapshot.status_code == 404:
        return None  # branch has no revisions yet
    snapshot.raise_for_status()
    payload = snapshot.json()
    revision = int(payload["revision"])
    url = payload["url"]

    branch_root = PROJECTS_ROOT / ".dbt-exec" / project_id / _safe_segment(branch)
    tree = branch_root / f"rev-{revision:012d}"
    if not tree.is_dir():
        _extract_snapshot(url, tree)
        _prune_stale_revisions(branch_root, keep=tree.name)

    configured = resolve_dbt_project_dir(branch=branch)
    if configured is None:
        return None
    target = (tree / configured).resolve() if configured else tree.resolve()
    if not target.is_relative_to(tree.resolve()):
        raise DbtMaterializeError(f"dbt project dir escapes the workspace: {configured!r}")
    return str(target)


def _extract_snapshot(snapshot_url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="dbt-mat-", dir=str(dest.parent)))
    try:
        with tempfile.TemporaryFile() as spool:
            with httpx.stream("GET", snapshot_url, timeout=120.0) as tarball:
                tarball.raise_for_status()
                for chunk in tarball.iter_bytes():
                    spool.write(chunk)
            spool.seek(0)
            with tarfile.open(fileobj=spool, mode="r:*") as tar:
                for member in tar.getmembers():
                    name = member.name.replace("\\", "/")
                    if (
                        name.startswith(("/", "../"))
                        or "/../" in name
                        or member.islnk()
                        or member.issym()
                    ):
                        raise DbtMaterializeError(
                            f"Unsafe member in snapshot tarball: {member.name!r}"
                        )
                tar.extractall(staging)  # noqa: S202 — members validated above
        # Atomic-ish publish: concurrent dbt calls either see the old tree or
        # the complete new one, never a half-extracted directory.
        if not dest.exists():
            staging.replace(dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _prune_stale_revisions(branch_root: Path, *, keep: str) -> None:
    try:
        for entry in branch_root.iterdir():
            if entry.name != keep and entry.is_dir() and entry.name.startswith("rev-"):
                shutil.rmtree(entry, ignore_errors=True)
    except OSError:
        LOGGER.debug("Could not prune stale dbt scratch under %s", branch_root, exc_info=True)
