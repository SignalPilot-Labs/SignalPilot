"""Manifest model and object-key layout for the workspace store."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

_BRANCH_KEY_RE = re.compile(r"[^a-zA-Z0-9._/-]+")


def org_prefix(org_id: str) -> str:
    digest = hashlib.sha256(org_id.encode("utf-8")).hexdigest()[:24]
    return f"orgs/{digest}"


def project_prefix(org_id: str, project_id: str) -> str:
    return f"{org_prefix(org_id)}/projects/{project_id}"


def _branch_part(branch: str) -> str:
    # Branch names already pass git ref validation upstream; this only makes
    # them key-safe ('/' is preserved so agent branches keep their hierarchy).
    cleaned = _BRANCH_KEY_RE.sub("-", branch.strip()).strip("/-.")
    if not cleaned:
        raise ValueError("Branch name produces an empty object-key segment")
    return cleaned


def blob_key(org_id: str, project_id: str, sha256: str) -> str:
    return f"{project_prefix(org_id, project_id)}/blobs/{sha256}"


def manifest_key(org_id: str, project_id: str, branch: str, revision: int, nonce: str) -> str:
    return (
        f"{project_prefix(org_id, project_id)}/branches/{_branch_part(branch)}"
        f"/manifests/{revision:012d}-{nonce}.json"
    )


def snapshot_key(org_id: str, project_id: str, branch: str, revision: int) -> str:
    return (
        f"{project_prefix(org_id, project_id)}/branches/{_branch_part(branch)}"
        f"/snapshots/{revision:012d}.tgz"
    )


# dbt map artifacts (note: `manifests/` above means workspace *file* manifests;
# dbt artifacts get their own `dbt/` segment). Nested under the project prefix
# so delete_prefix on project deletion covers them.


def dbt_manifest_key(org_id: str, project_id: str, branch: str, revision: int) -> str:
    return (
        f"{project_prefix(org_id, project_id)}/branches/{_branch_part(branch)}"
        f"/dbt/{revision:012d}-manifest.json.gz"
    )


def dbt_graph_key(org_id: str, project_id: str, branch: str, revision: int) -> str:
    return (
        f"{project_prefix(org_id, project_id)}/branches/{_branch_part(branch)}"
        f"/dbt/{revision:012d}-graph.json.gz"
    )


def dbt_sql_key(org_id: str, project_id: str, branch: str, revision: int) -> str:
    return (
        f"{project_prefix(org_id, project_id)}/branches/{_branch_part(branch)}"
        f"/dbt/{revision:012d}-sql.json.gz"
    )


@dataclass(frozen=True)
class FileEntry:
    path: str
    sha256: str
    size: int
    mode: int = 0o644
    mtime: float = 0.0

    def to_json(self) -> dict:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
            "mode": self.mode,
            "mtime": self.mtime,
        }

    @classmethod
    def from_json(cls, data: dict) -> FileEntry:
        return cls(
            path=str(data["path"]),
            sha256=str(data["sha256"]),
            size=int(data["size"]),
            mode=int(data.get("mode", 0o644)),
            mtime=float(data.get("mtime", 0.0)),
        )


@dataclass(frozen=True)
class Manifest:
    revision: int
    parent: int | None
    created_at: float
    created_by: str | None = None
    message: str | None = None
    entries: tuple[FileEntry, ...] = field(default_factory=tuple)

    def entry(self, path: str) -> FileEntry | None:
        for candidate in self.entries:
            if candidate.path == path:
                return candidate
        return None

    def paths(self) -> list[str]:
        return [entry.path for entry in self.entries]

    def to_bytes(self) -> bytes:
        payload = {
            "revision": self.revision,
            "parent": self.parent,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "message": self.message,
            "entries": [entry.to_json() for entry in sorted(self.entries, key=lambda e: e.path)],
        }
        return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> Manifest:
        payload = json.loads(data.decode("utf-8"))
        return cls(
            revision=int(payload["revision"]),
            parent=payload.get("parent"),
            created_at=float(payload["created_at"]),
            created_by=payload.get("created_by"),
            message=payload.get("message"),
            entries=tuple(FileEntry.from_json(item) for item in payload.get("entries", [])),
        )
