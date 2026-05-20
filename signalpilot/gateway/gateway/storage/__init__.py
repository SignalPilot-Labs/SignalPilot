"""Workspace storage — re-exports for external callers.

Public surface:
    WorkspaceStore   — abstract backend interface
    WorkspaceKey     — (org_id, user_id, notebook_id); validates at construction
    HydrateResult    — result of hydrate()
    SnapshotResult   — result of snapshot()
    get_workspace_store — factory singleton
"""

from .factory import get_workspace_store
from .workspace_store import HydrateResult, SnapshotResult, WorkspaceKey, WorkspaceStore

__all__ = [
    "WorkspaceStore",
    "WorkspaceKey",
    "HydrateResult",
    "SnapshotResult",
    "get_workspace_store",
]
