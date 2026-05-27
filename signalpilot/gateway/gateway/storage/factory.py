"""Workspace store factory — returns the configured backend singleton.

Backend selection (SP_WORKSPACE_BACKEND):
    "s3"       → S3WorkspaceStore (production)
    "local"    → LocalWorkspaceStore (local dev / tests)
    "disabled" → DisabledWorkspaceStore (default; ephemeral)

Anything else → ValueError at startup (fail-fast).

get_workspace_store() is an lru_cache singleton. Config is read from
WorkspaceStorageSettings at first call.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from .workspace_store import WorkspaceStore

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_workspace_store() -> WorkspaceStore:
    """Return the configured WorkspaceStore singleton. Fails fast on bad config."""
    from ..config.workspace_storage import get_workspace_storage_settings

    settings = get_workspace_storage_settings()
    backend = settings.sp_workspace_backend

    if backend == "s3":
        from .s3_store import S3WorkspaceStore

        if not settings.sp_workspace_s3_bucket or not settings.sp_workspace_s3_region:
            raise ValueError(
                "SP_WORKSPACE_BACKEND=s3 requires SP_WORKSPACE_S3_BUCKET and "
                "SP_WORKSPACE_S3_REGION to be set."
            )
        return S3WorkspaceStore(
            bucket=settings.sp_workspace_s3_bucket,
            prefix_root=settings.sp_workspace_s3_prefix_root,
            region=settings.sp_workspace_s3_region,
            endpoint_url=settings.sp_workspace_s3_endpoint_url,
        )

    if backend == "local":
        from pathlib import Path

        from .local_store import LocalWorkspaceStore

        if not settings.sp_workspace_local_root:
            raise ValueError(
                "SP_WORKSPACE_BACKEND=local requires SP_WORKSPACE_LOCAL_ROOT to be set."
            )
        return LocalWorkspaceStore(root=Path(settings.sp_workspace_local_root))

    if backend == "disabled":
        from .disabled_store import DisabledWorkspaceStore

        logger.warning("SP_WORKSPACE_BACKEND=disabled — workspaces are ephemeral")
        return DisabledWorkspaceStore()

    raise ValueError(
        f"Unknown SP_WORKSPACE_BACKEND value: {backend!r}. "
        "Must be one of: 's3', 'local', 'disabled'."
    )
