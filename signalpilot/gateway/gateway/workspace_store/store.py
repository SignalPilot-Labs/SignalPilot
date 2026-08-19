"""Workspace store operations: CAS commits, reads, snapshots, history.

All methods take an AsyncSession and org_id explicitly; the S3 facade is held
on the instance. Postgres is the lock (revision-row uniqueness), S3 is the
bytes — never the other way around.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayWorkspaceRevision
from .model import FileEntry, Manifest, blob_key, manifest_key, snapshot_key
from .objects import WorkspaceObjectStorage
from .paths import confine_relpath

_MAX_INLINE_UPSERT_BYTES = 8 * 1024 * 1024
_CAS_RETRIES = 3


class RevisionConflict(RuntimeError):
    """The base revision is stale: another writer committed first."""


class RevisionNotFound(LookupError):
    pass


@dataclass(frozen=True)
class Upsert:
    """One file change in a batch commit.

    Either `content` is inline bytes, or `sha256`+`size` reference a blob the
    client already uploaded via a presigned PUT (the >8 MB path).
    """

    path: str
    content: bytes | None = None
    sha256: str | None = None
    size: int | None = None
    mode: int = 0o644
    mtime: float | None = None


class WorkspaceStore:
    def __init__(self, storage: WorkspaceObjectStorage) -> None:
        self.storage = storage

    # ── History ──────────────────────────────────────────────────────────────

    async def head_revision(
        self, db: AsyncSession, *, org_id: str, project_id: str, branch: str
    ) -> int | None:
        result = await db.execute(
            select(func.max(GatewayWorkspaceRevision.revision)).where(
                GatewayWorkspaceRevision.org_id == org_id,
                GatewayWorkspaceRevision.project_id == project_id,
                GatewayWorkspaceRevision.branch == branch,
            )
        )
        return result.scalar_one_or_none()

    async def list_revisions(
        self, db: AsyncSession, *, org_id: str, project_id: str, branch: str, limit: int = 100
    ) -> list[GatewayWorkspaceRevision]:
        result = await db.execute(
            select(GatewayWorkspaceRevision)
            .where(
                GatewayWorkspaceRevision.org_id == org_id,
                GatewayWorkspaceRevision.project_id == project_id,
                GatewayWorkspaceRevision.branch == branch,
            )
            .order_by(GatewayWorkspaceRevision.revision.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def list_branches(
        self, db: AsyncSession, *, org_id: str, project_id: str
    ) -> list[str]:
        result = await db.execute(
            select(GatewayWorkspaceRevision.branch)
            .where(
                GatewayWorkspaceRevision.org_id == org_id,
                GatewayWorkspaceRevision.project_id == project_id,
            )
            .distinct()
        )
        return sorted(result.scalars())

    async def has_revisions(self, db: AsyncSession, *, project_id: str) -> bool:
        """Org-agnostic existence probe for tombstone detection on deleted
        projects (the org row is gone; the revision history is the evidence)."""
        result = await db.execute(
            select(GatewayWorkspaceRevision.id)
            .where(GatewayWorkspaceRevision.project_id == project_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def load_manifest(
        self,
        db: AsyncSession,
        *,
        org_id: str,
        project_id: str,
        branch: str,
        revision: int | None = None,
    ) -> Manifest:
        """Load the manifest at `revision` (None = head). Raises
        RevisionNotFound when the branch has no such revision."""
        query = select(GatewayWorkspaceRevision).where(
            GatewayWorkspaceRevision.org_id == org_id,
            GatewayWorkspaceRevision.project_id == project_id,
            GatewayWorkspaceRevision.branch == branch,
        )
        if revision is None:
            query = query.order_by(GatewayWorkspaceRevision.revision.desc()).limit(1)
        else:
            query = query.where(GatewayWorkspaceRevision.revision == revision)
        row = (await db.execute(query)).scalars().first()
        if row is None:
            raise RevisionNotFound(
                f"No revision {'HEAD' if revision is None else revision} for {project_id}@{branch}"
            )
        data = await self.storage.get_bytes(row.manifest_key)
        if data is None:
            raise RevisionNotFound(f"Manifest object missing for revision {row.revision}")
        return Manifest.from_bytes(data)

    # ── Reads ────────────────────────────────────────────────────────────────

    async def read_file(
        self,
        db: AsyncSession,
        *,
        org_id: str,
        project_id: str,
        branch: str,
        path: str,
        revision: int | None = None,
    ) -> tuple[FileEntry, bytes] | None:
        path = confine_relpath(path)
        try:
            manifest = await self.load_manifest(
                db, org_id=org_id, project_id=project_id, branch=branch, revision=revision
            )
        except RevisionNotFound:
            return None
        entry = manifest.entry(path)
        if entry is None:
            return None
        blob = await self.storage.get_bytes(blob_key(org_id, project_id, entry.sha256))
        if blob is None:
            return None
        return entry, blob

    # ── Commits ──────────────────────────────────────────────────────────────

    async def commit(
        self,
        db: AsyncSession,
        *,
        org_id: str,
        project_id: str,
        branch: str,
        base_revision: int | None,
        upserts: list[Upsert],
        deletes: list[str],
        created_by: str | None = None,
        message: str | None = None,
    ) -> Manifest:
        """Commit a batch atomically. `base_revision` must equal the current
        head (None for the first commit on a branch) or RevisionConflict is
        raised — exactly one racer wins."""
        deletes = [confine_relpath(p) for p in deletes]
        for item in upserts:
            confine_relpath(item.path)

        if base_revision is None:
            parent_entries: dict[str, FileEntry] = {}
            new_revision = 0
        else:
            parent = await self.load_manifest(
                db, org_id=org_id, project_id=project_id, branch=branch, revision=base_revision
            )
            parent_entries = {entry.path: entry for entry in parent.entries}
            new_revision = base_revision + 1

        now = time.time()
        entries = dict(parent_entries)
        for path in deletes:
            entries.pop(path, None)
        for item in upserts:
            path = confine_relpath(item.path)
            if item.content is not None:
                if len(item.content) > _MAX_INLINE_UPSERT_BYTES:
                    raise ValueError(
                        "Inline upsert exceeds 8 MB — upload via presigned PUT and commit by reference"
                    )
                digest = hashlib.sha256(item.content).hexdigest()
                key = blob_key(org_id, project_id, digest)
                if not await self.storage.exists(key):
                    await self.storage.put_bytes(key, item.content)
                size = len(item.content)
            else:
                if not item.sha256 or item.size is None:
                    raise ValueError("Reference upserts need sha256 and size")
                digest = item.sha256
                key = blob_key(org_id, project_id, digest)
                actual = await self.storage.head_size(key)
                if actual is None:
                    raise ValueError(f"Referenced blob {digest[:12]} was never uploaded")
                if actual != item.size:
                    raise ValueError(f"Referenced blob {digest[:12]} size mismatch")
                size = item.size
            entries[path] = FileEntry(
                path=path,
                sha256=digest,
                size=size,
                mode=item.mode,
                mtime=item.mtime if item.mtime is not None else now,
            )

        manifest = Manifest(
            revision=new_revision,
            parent=base_revision,
            created_at=now,
            created_by=created_by,
            message=message,
            entries=tuple(sorted(entries.values(), key=lambda e: e.path)),
        )
        # The nonce makes this commit's manifest key unique, so a racing loser
        # can never overwrite the winner's manifest object.
        nonce = uuid.uuid4().hex[:8]
        key = manifest_key(org_id, project_id, branch, new_revision, nonce)
        await self.storage.put_bytes(key, manifest.to_bytes(), content_type="application/json")

        row = GatewayWorkspaceRevision(
            org_id=org_id,
            project_id=project_id,
            branch=branch,
            revision=new_revision,
            parent_revision=base_revision,
            manifest_key=key,
            file_count=len(manifest.entries),
            total_bytes=sum(entry.size for entry in manifest.entries),
            message=message,
            created_by=created_by,
            created_at=now,
        )
        db.add(row)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise RevisionConflict(
                f"Revision {new_revision} on {project_id}@{branch} was committed by another writer"
            ) from exc
        return manifest

    async def commit_at_head(
        self,
        db: AsyncSession,
        *,
        org_id: str,
        project_id: str,
        branch: str,
        upserts: list[Upsert],
        deletes: list[str],
        created_by: str | None = None,
        message: str | None = None,
    ) -> Manifest:
        """Convenience for single-file API calls that carry no client base:
        re-read head and retry a bounded number of times on CAS conflict."""
        last: RevisionConflict | None = None
        for _ in range(_CAS_RETRIES):
            head = await self.head_revision(db, org_id=org_id, project_id=project_id, branch=branch)
            try:
                return await self.commit(
                    db,
                    org_id=org_id,
                    project_id=project_id,
                    branch=branch,
                    base_revision=head,
                    upserts=upserts,
                    deletes=deletes,
                    created_by=created_by,
                    message=message,
                )
            except RevisionConflict as exc:
                last = exc
        raise last if last is not None else RevisionConflict("CAS retries exhausted")

    async def copy_file(
        self,
        db: AsyncSession,
        *,
        org_id: str,
        project_id: str,
        branch: str,
        source: str,
        destination: str,
        created_by: str | None = None,
        move: bool = False,
    ) -> Manifest:
        """Copy (or move) within the project by manifest edit — the blob is
        shared, no bytes travel."""
        source = confine_relpath(source)
        destination = confine_relpath(destination)
        manifest = await self.load_manifest(db, org_id=org_id, project_id=project_id, branch=branch)
        entry = manifest.entry(source)
        if entry is None:
            raise FileNotFoundError(source)
        upsert = Upsert(
            path=destination, sha256=entry.sha256, size=entry.size, mode=entry.mode
        )
        # commit() verifies referenced blobs by HEAD; the source entry's blob
        # is present by construction.
        return await self.commit_at_head(
            db,
            org_id=org_id,
            project_id=project_id,
            branch=branch,
            upserts=[upsert],
            deletes=[source] if move else [],
            created_by=created_by,
            message=f"{'move' if move else 'copy'} {source} -> {destination}",
        )

    # ── Snapshots ────────────────────────────────────────────────────────────

    async def build_snapshot(
        self,
        db: AsyncSession,
        *,
        org_id: str,
        project_id: str,
        branch: str,
        revision: int | None = None,
    ) -> tuple[int, str]:
        """Materialize (or reuse) the tarball of a revision and return
        (revision, object_key). Presigning is the caller's concern."""
        manifest = await self.load_manifest(
            db, org_id=org_id, project_id=project_id, branch=branch, revision=revision
        )
        key = snapshot_key(org_id, project_id, branch, manifest.revision)
        if await self.storage.exists(key):
            return manifest.revision, key

        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            for entry in manifest.entries:
                blob = await self.storage.get_bytes(blob_key(org_id, project_id, entry.sha256))
                if blob is None:
                    raise RevisionNotFound(f"Blob missing for {entry.path} at revision {manifest.revision}")
                info = tarfile.TarInfo(name=entry.path)
                info.size = len(blob)
                info.mode = entry.mode
                info.mtime = int(entry.mtime)
                tar.addfile(info, io.BytesIO(blob))
        await self.storage.put_bytes(key, buffer.getvalue(), content_type="application/gzip")
        return manifest.revision, key

    # ── Deletion ─────────────────────────────────────────────────────────────

    async def purge_project_objects(self, *, org_id: str, project_id: str) -> int:
        """Delete every S3 object for a project. Revision rows are kept as the
        tombstone/provenance record — blobs prune, history rows never do."""
        from .model import project_prefix

        return await self.storage.delete_prefix(project_prefix(org_id, project_id))

    async def drop_branch_history(
        self, db: AsyncSession, *, org_id: str, project_id: str, branch: str
    ) -> None:
        await db.execute(
            sa_delete(GatewayWorkspaceRevision).where(
                GatewayWorkspaceRevision.org_id == org_id,
                GatewayWorkspaceRevision.project_id == project_id,
                GatewayWorkspaceRevision.branch == branch,
            )
        )
        await db.commit()
