"""Disabled workspace store — no-op backend.

Used when SP_WORKSPACE_BACKEND=disabled (the default). Workspaces are ephemeral:
data is lost on pod restart. Only valid in local/dev mode — cloud mode hard-fails
at startup with this backend (S11).
"""

from __future__ import annotations

import logging
from pathlib import Path

from .workspace_store import HydrateResult, SnapshotResult, WorkspaceKey, WorkspaceStore

logger = logging.getLogger(__name__)

_DISABLED_VERSION = "disabled"


class DisabledWorkspaceStore(WorkspaceStore):
    """No-op workspace store. All ops are safe no-ops; workspaces are ephemeral."""

    async def exists(self, key: WorkspaceKey) -> bool:
        return False

    async def hydrate(self, key: WorkspaceKey, dest: Path) -> HydrateResult:
        return HydrateResult(
            manifest_version=None,
            file_count=0,
            bytes_copied=0,
            cold_start=True,
        )

    async def snapshot(self, key: WorkspaceKey, src: Path) -> SnapshotResult:
        return SnapshotResult(
            manifest_version=_DISABLED_VERSION,
            file_count=0,
            bytes_uploaded=0,
            skipped_paths=(),
        )
