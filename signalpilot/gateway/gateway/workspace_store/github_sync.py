"""GitHub ⇄ workspace-store bridge — the three-tier model's bottom seam.

Three tiers (spec §4.3 REVISED / §4.5, notebook-vercel-s3-redesign.md):

    browser  = unsaved editor buffers
    S3       = the saved working copy per branch (WorkspaceStore revisions)
    GitHub   = the canonical repository — pulled FROM on connect/fetch,
               stored BACK on push/sync

This module drives both directions against the project's bare repo
(`gateway/git/repos.py`) using git plumbing only — no working-tree checkouts:

- ``import_repo_to_revisions``: bare-repo tree at a branch head → next S3
  revision (idempotent: identical content produces no new revision).
- ``export_revision_to_git``: an S3 revision's manifest → exactly one commit
  on the bare-repo branch (temp-index ``update-index``/``write-tree``/
  ``commit-tree``), recorded as ``export_commit_sha`` on the revision row,
  then pushed to GitHub through ``git/sync.push_branch`` (which excludes
  agent branches — they never reach GitHub).

Export failures never corrupt or block the S3 side: revision rows are only
annotated after a successful local commit (and the push, if one is due),
and every S3 write happens through WorkspaceStore's CAS commit.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayWorkspaceRevision
from ..git import sync as git_sync
from ..git.repos import (
    _run_git,
    branch_head_sha,
    get_head_ref,
    repo_exists,
    repo_path,
)
from .model import FileEntry, Manifest, blob_key
from .objects import WorkspaceObjectStorage
from .store import RevisionNotFound, Upsert, WorkspaceStore

logger = logging.getLogger(__name__)

_GIT_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "SignalPilot",
    "GIT_AUTHOR_EMAIL": "local@signalpilot.dev",
    "GIT_COMMITTER_NAME": "SignalPilot",
    "GIT_COMMITTER_EMAIL": "local@signalpilot.dev",
}

_EXECUTABLE_GIT_MODE = "100755"
_REGULAR_GIT_MODE = "100644"


class GitHubImportError(RuntimeError):
    """The bare repo could not be read into a workspace revision."""


class GitHubExportError(RuntimeError):
    """The revision could not be committed/pushed to git. S3 revisions are
    untouched when this raises — editing is never blocked by export."""


@dataclass(frozen=True)
class ImportResult:
    imported: bool
    revision: int | None
    commit_sha: str | None


@dataclass(frozen=True)
class ExportResult:
    revision: int
    commit_sha: str
    pushed: bool
    push_skipped_reason: str | None = None


# ── Byte-safe plumbing (repos._run_git is text-mode; file content is bytes) ──


def _run_git_bytes(
    *args: str,
    cwd: Path | str,
    input_bytes: bytes | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> tuple[int, bytes, bytes]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        timeout=timeout,
        input=input_bytes,
        env={**os.environ, **env} if env else None,
    )
    return result.returncode, result.stdout, result.stderr


def _read_repo_tree(rp: Path, ref: str) -> dict[str, tuple[bytes, int]]:
    """Read every blob reachable from `ref` in the bare repo.

    Returns {path: (content, mode)} with mode collapsed to 0o755/0o644.
    Plumbing only — no checkout, no temp clone.
    """
    rc, out, err = _run_git_bytes("ls-tree", "-r", "-z", ref, cwd=rp)
    if rc != 0:
        raise GitHubImportError(f"git ls-tree {ref} failed: {err.decode(errors='replace').strip()}")

    files: dict[str, tuple[bytes, int]] = {}
    for record in out.split(b"\x00"):
        if not record:
            continue
        meta, _, raw_path = record.partition(b"\t")
        parts = meta.split(b" ")
        if len(parts) != 3:
            continue
        git_mode, obj_type, sha = (p.decode() for p in parts)
        if obj_type != "blob":
            continue  # submodules (commit) have no bytes to import
        path = raw_path.decode("utf-8")
        rc, blob, err = _run_git_bytes("cat-file", "blob", sha, cwd=rp)
        if rc != 0:
            raise GitHubImportError(
                f"git cat-file blob {sha} failed: {err.decode(errors='replace').strip()}"
            )
        mode = 0o755 if git_mode == _EXECUTABLE_GIT_MODE else 0o644
        files[path] = (blob, mode)
    return files


# ── Pull: GitHub (bare repo) → S3 revisions ──────────────────────────────────


async def import_repo_to_revisions(
    db: AsyncSession,
    storage: WorkspaceObjectStorage,
    *,
    org_id: str,
    project_id: str,
    branch: str | None = None,
) -> ImportResult:
    """Commit the bare repo's tree at the branch head as the next S3 revision.

    Runs when a GitHub repo is connected (pull) and when inbound GitHub
    changes arrive (fetch/sync). Idempotent: when the repo tree's content
    already matches the head revision, no new revision is created.
    """
    if not repo_exists(project_id):
        raise GitHubImportError(f"No bare repo for project {project_id}")
    rp = repo_path(project_id)

    if branch is None:
        branch = get_head_ref(project_id) or "main"

    commit_sha = branch_head_sha(project_id, branch)
    if commit_sha is None:
        raise GitHubImportError(f"Branch {branch!r} not found in bare repo for {project_id}")

    repo_files = _read_repo_tree(rp, f"refs/heads/{branch}")

    store = WorkspaceStore(storage)
    head = await store.head_revision(db, org_id=org_id, project_id=project_id, branch=branch)
    parent_entries: dict[str, FileEntry] = {}
    if head is not None:
        parent = await store.load_manifest(
            db, org_id=org_id, project_id=project_id, branch=branch, revision=head
        )
        parent_entries = {entry.path: entry for entry in parent.entries}

    upserts: list[Upsert] = []
    for path, (content, mode) in sorted(repo_files.items()):
        existing = parent_entries.get(path)
        digest = hashlib.sha256(content).hexdigest()
        if existing is not None and existing.sha256 == digest and existing.mode == mode:
            continue
        upserts.append(Upsert(path=path, content=content, mode=mode))
    deletes = [path for path in parent_entries if path not in repo_files]

    if not upserts and not deletes:
        # Tree content already matches the head revision — nothing to import.
        # (Covers the empty-scaffold case too: no files, no history, no-op.)
        if head is None and not repo_files:
            return ImportResult(imported=False, revision=None, commit_sha=commit_sha)
        return ImportResult(imported=False, revision=head, commit_sha=commit_sha)

    manifest = await store.commit(
        db,
        org_id=org_id,
        project_id=project_id,
        branch=branch,
        base_revision=head,
        upserts=upserts,
        deletes=deletes,
        created_by="github-import",
        message=f"Import from GitHub {branch}@{commit_sha[:12]}",
    )
    logger.info(
        "Imported %s@%s (%s) into workspace revision %s (%d upserts, %d deletes)",
        project_id, branch, commit_sha[:12], manifest.revision, len(upserts), len(deletes),
    )
    return ImportResult(imported=True, revision=manifest.revision, commit_sha=commit_sha)


# ── Store: S3 revision → git commit → GitHub ─────────────────────────────────


def _write_manifest_tree(rp: Path, entries: list[tuple[FileEntry, bytes]]) -> str:
    """Materialize manifest entries as a git tree using a temp index.

    hash-object -w each blob, stage via update-index --cacheinfo, write-tree.
    No worktree is ever created.
    """
    with tempfile.TemporaryDirectory(prefix="sp-export-") as tmp:
        index_env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        for entry, content in entries:
            rc, out, err = _run_git_bytes(
                "hash-object", "-w", "--stdin", cwd=rp, input_bytes=content
            )
            if rc != 0:
                raise GitHubExportError(
                    f"git hash-object failed for {entry.path}: {err.decode(errors='replace').strip()}"
                )
            blob_sha = out.decode().strip()
            git_mode = _EXECUTABLE_GIT_MODE if entry.mode & 0o111 else _REGULAR_GIT_MODE
            rc, _, err = _run_git(
                "update-index", "--add", "--cacheinfo",
                f"{git_mode},{blob_sha},{entry.path}",
                cwd=rp, env=index_env,
            )
            if rc != 0:
                raise GitHubExportError(f"git update-index failed for {entry.path}: {err.strip()}")
        rc, out, err = _run_git("write-tree", cwd=rp, env=index_env)
        if rc != 0 or not out.strip():
            raise GitHubExportError(f"git write-tree failed: {err.strip()}")
        return out.strip()


async def _resolve_remote_url(db: AsyncSession, *, org_id: str, project_id: str) -> str | None:
    """Look up the linked GitHub remote for a project, or None when unlinked."""
    from ..store import github as gh_store

    link = await gh_store.get_repo_link_for_project(db, org_id=org_id, project_id=project_id)
    if not link:
        return None
    installation = await gh_store.get_installation(
        db, org_id=org_id, installation_id=link.installation_id
    )
    if not installation:
        return None
    token = await gh_store.get_valid_token(db, installation)
    return f"https://x-access-token:{token}@github.com/{link.repo_full_name}.git"


async def export_revision_to_git(
    db: AsyncSession,
    storage: WorkspaceObjectStorage,
    *,
    org_id: str,
    project_id: str,
    branch: str,
    revision: int | None = None,
    remote_url: str | None = None,
) -> ExportResult:
    """Materialize a revision's manifest as a commit on the bare-repo branch,
    record export_commit_sha, and push to GitHub.

    - One revision ↔ at most one export commit: an already-exported revision
      returns the recorded sha without committing or pushing again.
    - Agent branches never reach GitHub (git/sync exclusion is reused).
    - A push failure raises GitHubExportError; revisions stay intact and
      un-annotated, so a retry converges (the local commit is reused).
    """
    if not repo_exists(project_id):
        raise GitHubExportError(f"No bare repo for project {project_id}")
    rp = repo_path(project_id)

    store = WorkspaceStore(storage)
    manifest = await store.load_manifest(
        db, org_id=org_id, project_id=project_id, branch=branch, revision=revision
    )

    row = (
        await db.execute(
            select(GatewayWorkspaceRevision).where(
                GatewayWorkspaceRevision.org_id == org_id,
                GatewayWorkspaceRevision.project_id == project_id,
                GatewayWorkspaceRevision.branch == branch,
                GatewayWorkspaceRevision.revision == manifest.revision,
            )
        )
    ).scalars().first()
    if row is None:
        raise RevisionNotFound(
            f"No revision row {manifest.revision} for {project_id}@{branch}"
        )

    # Re-export of an already-exported revision is a no-op.
    if row.export_commit_sha:
        return ExportResult(
            revision=manifest.revision,
            commit_sha=row.export_commit_sha,
            pushed=False,
            push_skipped_reason="already exported",
        )

    # Pull blobs and build the tree without touching any working tree.
    contents: list[tuple[FileEntry, bytes]] = []
    for entry in manifest.entries:
        blob = await storage.get_bytes(blob_key(org_id, project_id, entry.sha256))
        if blob is None:
            raise GitHubExportError(
                f"Blob missing for {entry.path} at revision {manifest.revision}"
            )
        contents.append((entry, blob))
    tree_sha = _write_manifest_tree(rp, contents)

    parent = branch_head_sha(project_id, branch)
    commit_sha: str
    if parent is not None:
        rc, out, _ = _run_git("rev-parse", f"{parent}^{{tree}}", cwd=rp)
        if rc == 0 and out.strip() == tree_sha:
            # The branch head already carries exactly this content (e.g. the
            # revision was itself imported from git) — reuse it, no new commit.
            commit_sha = parent
        else:
            commit_sha = _commit_tree(rp, tree_sha, parent, manifest)
    else:
        commit_sha = _commit_tree(rp, tree_sha, None, manifest)

    if commit_sha != parent:
        rc, _, err = _run_git("update-ref", f"refs/heads/{branch}", commit_sha, cwd=rp)
        if rc != 0:
            raise GitHubExportError(f"git update-ref {branch} failed: {err.strip()}")

    # Push to GitHub — sync.push_branch owns the agent-branch exclusion.
    pushed = False
    push_skipped_reason: str | None = None
    if remote_url is None:
        remote_url = await _resolve_remote_url(db, org_id=org_id, project_id=project_id)
    if remote_url is None:
        push_skipped_reason = "no GitHub remote linked"
    else:
        result = git_sync.push_branch(project_id, remote_url, branch)
        if result.get("error"):
            raise GitHubExportError(
                f"Push of {branch} failed: {result['error']}"
            )
        if result.get("skipped"):
            push_skipped_reason = str(result.get("reason") or "skipped")
        else:
            pushed = True

    await db.execute(
        update(GatewayWorkspaceRevision)
        .where(GatewayWorkspaceRevision.id == row.id)
        .values(export_commit_sha=commit_sha)
    )
    await db.commit()

    logger.info(
        "Exported %s@%s revision %s as commit %s (pushed=%s%s)",
        project_id, branch, manifest.revision, commit_sha[:12], pushed,
        f", {push_skipped_reason}" if push_skipped_reason else "",
    )
    return ExportResult(
        revision=manifest.revision,
        commit_sha=commit_sha,
        pushed=pushed,
        push_skipped_reason=push_skipped_reason,
    )


def _commit_tree(rp: Path, tree_sha: str, parent: str | None, manifest: Manifest) -> str:
    message = manifest.message or f"Workspace revision {manifest.revision}"
    args = ["commit-tree", tree_sha]
    if parent is not None:
        args += ["-p", parent]
    args += ["-m", f"{message}\n\nsp-workspace-revision: {manifest.revision}"]
    rc, out, err = _run_git(*args, cwd=rp, env=_GIT_IDENTITY_ENV)
    if rc != 0 or not out.strip():
        raise GitHubExportError(f"git commit-tree failed: {err.strip()}")
    return out.strip()
