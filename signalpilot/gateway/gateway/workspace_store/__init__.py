"""S3-backed workspace object store — the durable truth for project files.

Layout (bucket SP_WORKSPACE_S3_BUCKET):

    orgs/{sha256(org_id)[:24]}/projects/{project_id}/
        blobs/{sha256}                              # content-addressed, immutable
        branches/{branch}/manifests/{rev:012d}-{nonce}.json
        branches/{branch}/snapshots/{rev:012d}.tgz

A revision is an atomic manifest write; the commit point is a Postgres row
insert with a UNIQUE (project_id, branch, revision) constraint, so revision
numbers are strictly monotonic per branch and a stale base loses the race with
an integrity error, never a silent overwrite. Manifest object keys carry a
per-commit nonce so a losing racer can never clobber the winner's manifest.

Blobs are shared across branches and revisions: identical content stores once.
Manifests are immutable: deletion is a new revision, old links keep resolving.
"""

from .github_sync import (
    ExportResult,
    GitHubExportError,
    GitHubImportError,
    ImportResult,
    export_revision_to_git,
    import_repo_to_revisions,
)
from .lease import LeaseHeld, acquire_lease, release_lease, renew_lease
from .model import FileEntry, Manifest, blob_key, manifest_key, snapshot_key
from .objects import WorkspaceObjectStorage, workspace_object_storage
from .paths import WorkspacePathError, confine_relpath
from .store import RevisionConflict, WorkspaceStore

__all__ = [
    "ExportResult",
    "FileEntry",
    "GitHubExportError",
    "GitHubImportError",
    "ImportResult",
    "LeaseHeld",
    "Manifest",
    "RevisionConflict",
    "WorkspaceObjectStorage",
    "WorkspacePathError",
    "WorkspaceStore",
    "acquire_lease",
    "blob_key",
    "confine_relpath",
    "export_revision_to_git",
    "import_repo_to_revisions",
    "manifest_key",
    "release_lease",
    "renew_lease",
    "snapshot_key",
    "workspace_object_storage",
]
