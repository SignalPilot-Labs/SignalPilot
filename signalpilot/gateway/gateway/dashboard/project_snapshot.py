"""Durable dashboard project snapshots backed by the workspace object store.

Dashboard versions historically pinned a git commit from the gateway-local
bare-repository cache.  Cloud gateways are replaceable, so that cache is not a
durable authority.  Workspace revisions are.  This module gives an immutable
workspace revision a 40-character reference that fits the existing dashboard
lineage contract and can be resolved without a local git repository.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import tarfile
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayWorkspaceRevision
from gateway.workspace_store.model import Manifest
from gateway.workspace_store.objects import WorkspaceObjectStorage
from gateway.workspace_store.store import RevisionNotFound, WorkspaceStore

_SNAPSHOT_REF_DOMAIN = b"signalpilot-dashboard-workspace-snapshot-v1\0"
_REVISION_HEX_LENGTH = 8
_MAX_DATABASE_REVISION = 0x7FFFFFFF
_hydrate_locks: dict[tuple[str, str], asyncio.Lock] = {}
logger = logging.getLogger(__name__)


def workspace_snapshot_ref(manifest: Manifest) -> str:
    """Return a stable 40-character reference for one immutable manifest."""
    if manifest.revision < 0 or manifest.revision > 0xFFFFFFFF:
        raise ValueError("Workspace revision is outside the dashboard snapshot range")
    digest = hashlib.sha256(_SNAPSHOT_REF_DOMAIN + manifest.to_bytes()).hexdigest()
    return f"{manifest.revision:0{_REVISION_HEX_LENGTH}x}{digest[:32]}"


async def resolve_branch_snapshot(
    db: AsyncSession,
    storage: WorkspaceObjectStorage,
    *,
    org_id: str,
    project_id: str,
    branch: str,
) -> str | None:
    """Resolve the branch's durable workspace head, if one exists."""
    if not storage.enabled:
        return None
    try:
        manifest = await WorkspaceStore(storage).load_manifest(
            db,
            org_id=org_id,
            project_id=project_id,
            branch=branch,
        )
    except RevisionNotFound:
        return None
    return workspace_snapshot_ref(manifest)


async def hydrate_github_mirror(
    db: AsyncSession,
    *,
    org_id: str,
    project_id: str,
) -> bool:
    """Lazily restore one replaceable local GitHub mirror."""
    from gateway.git.repos import clone_from_remote
    from gateway.store import github as github_store

    lock = _hydrate_locks.setdefault((org_id, project_id), asyncio.Lock())
    async with lock:
        link = await github_store.get_repo_link_for_project(db, org_id=org_id, project_id=project_id)
        if link is None:
            return False
        installation = await github_store.get_installation(
            db,
            org_id=org_id,
            installation_id=link.installation_id,
        )
        if installation is None:
            return False
        try:
            token = await github_store.get_valid_token(db, installation)
            remote_url = f"https://x-access-token:{token}@github.com/{link.repo_full_name}.git"
            await asyncio.to_thread(clone_from_remote, project_id, remote_url)
            return True
        except Exception as exc:
            logger.warning("Dashboard GitHub mirror recovery failed for project %s: %s", project_id, type(exc).__name__)
            return False


async def ensure_branch_snapshot(
    db: AsyncSession,
    storage: WorkspaceObjectStorage,
    *,
    org_id: str,
    project_id: str,
    branch: str,
) -> str | None:
    """Return a durable branch snapshot, importing or hydrating when needed."""
    durable = await resolve_branch_snapshot(
        db,
        storage,
        org_id=org_id,
        project_id=project_id,
        branch=branch,
    )
    if durable or not storage.enabled:
        return durable

    from gateway.git.repos import branch_head_sha
    from gateway.workspace_store.github_sync import import_repo_to_revisions

    if branch_head_sha(project_id, branch) is None and not await hydrate_github_mirror(
        db,
        org_id=org_id,
        project_id=project_id,
    ):
        return None
    try:
        await import_repo_to_revisions(
            db,
            storage,
            org_id=org_id,
            project_id=project_id,
            branch=branch,
        )
    except Exception as exc:
        logger.warning("Dashboard workspace import failed for project %s: %s", project_id, type(exc).__name__)
        return None
    return await resolve_branch_snapshot(
        db,
        storage,
        org_id=org_id,
        project_id=project_id,
        branch=branch,
    )


def _snapshot_revision(snapshot_ref: str) -> int | None:
    if len(snapshot_ref) != 40 or any(ch not in "0123456789abcdef" for ch in snapshot_ref.lower()):
        return None
    try:
        revision = int(snapshot_ref[:_REVISION_HEX_LENGTH], 16)
    except ValueError:
        return None
    return revision if revision <= _MAX_DATABASE_REVISION else None


async def materialize_workspace_snapshot(
    db: AsyncSession,
    storage: WorkspaceObjectStorage,
    *,
    org_id: str,
    project_id: str,
    snapshot_ref: str,
    destination: Path,
) -> bool:
    """Extract a pinned workspace snapshot and return whether it resolved.

    Revision numbers are branch-local, so all rows at the encoded revision are
    checked and the manifest digest selects the exact immutable snapshot.
    Legacy Git SHAs exported from a workspace revision resolve through the
    existing export mapping as well.
    """
    revision = _snapshot_revision(snapshot_ref)
    if not storage.enabled:
        return False

    snapshot_match = GatewayWorkspaceRevision.export_commit_sha == snapshot_ref
    if revision is not None:
        snapshot_match = or_(
            GatewayWorkspaceRevision.revision == revision,
            snapshot_match,
        )
    rows = list(
        (
            await db.execute(
                select(GatewayWorkspaceRevision).where(
                    GatewayWorkspaceRevision.org_id == org_id,
                    GatewayWorkspaceRevision.project_id == project_id,
                    snapshot_match,
                )
            )
        ).scalars()
    )
    workspace = WorkspaceStore(storage)
    for row in rows:
        manifest_bytes = await storage.get_bytes(row.manifest_key)
        if manifest_bytes is None:
            continue
        manifest = Manifest.from_bytes(manifest_bytes)
        if workspace_snapshot_ref(manifest) != snapshot_ref and row.export_commit_sha != snapshot_ref:
            continue

        _, key = await workspace.build_snapshot(
            db,
            org_id=org_id,
            project_id=project_id,
            branch=row.branch,
            revision=row.revision,
        )
        archive_bytes = await storage.get_bytes(key)
        if archive_bytes is None:
            raise RevisionNotFound(f"Snapshot object missing for revision {row.revision}")
        destination.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            archive.extractall(destination, filter="data")
        return True
    return False
