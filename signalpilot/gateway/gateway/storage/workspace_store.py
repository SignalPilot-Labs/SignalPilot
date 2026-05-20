"""Workspace store ABC, key, and result dataclasses.

WorkspaceKey: identifies a notebook workspace by (org_id, user_id, notebook_id).
Validation runs at construction — no un-validated key ever reaches a backend.

WorkspaceStore: abstract interface implemented by S3WorkspaceStore, LocalWorkspaceStore,
and DisabledWorkspaceStore.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

_KEY_FIELD_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Maximum file size for a single PUT (100 MB). Files exceeding this are skipped.
MAX_FILE_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class WorkspaceKey:
    """Identifies a notebook workspace. All fields validated at construction."""

    org_id: str
    user_id: str
    notebook_id: str

    def __post_init__(self) -> None:
        for field_name in ("org_id", "user_id", "notebook_id"):
            value = getattr(self, field_name)
            if not value:
                raise ValueError(f"WorkspaceKey.{field_name} must not be empty")
            if not _KEY_FIELD_RE.match(value):
                raise ValueError(
                    f"WorkspaceKey.{field_name} contains invalid characters: {value!r}. "
                    "Only [a-zA-Z0-9_-] is allowed."
                )


@dataclass(frozen=True)
class HydrateResult:
    """Result of hydrating a workspace from the store into a local directory."""

    manifest_version: str | None
    file_count: int
    bytes_copied: int
    cold_start: bool  # True when no manifest was found (empty workspace)


@dataclass(frozen=True)
class SnapshotResult:
    """Result of snapshotting a local directory into the store."""

    manifest_version: str
    file_count: int
    bytes_uploaded: int
    skipped_paths: tuple[str, ...]  # Paths skipped due to over-size; user-visible (S8)


class WorkspaceStore(ABC):
    """Abstract interface for workspace persistence backends."""

    @abstractmethod
    async def hydrate(self, key: WorkspaceKey, dest: Path) -> HydrateResult:
        """Download the latest snapshot into dest directory.

        Returns HydrateResult with cold_start=True if no manifest exists.
        Raises RuntimeError on any error other than missing manifest (e.g. partial download).
        """
        ...

    @abstractmethod
    async def snapshot(self, key: WorkspaceKey, src: Path) -> SnapshotResult:
        """Upload the contents of src directory as a new snapshot version.

        Data files are written first; the manifest pointer is updated ONLY after
        all data files have been successfully written (atomic commit semantics).
        """
        ...

    @abstractmethod
    async def exists(self, key: WorkspaceKey) -> bool:
        """Return True if a manifest exists for this key (i.e. non-cold-start)."""
        ...
