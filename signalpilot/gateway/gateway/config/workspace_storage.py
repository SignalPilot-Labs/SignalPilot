"""Workspace persistence settings for the gateway.

Controls the backend used for notebook workspace sync (SP_WORKSPACE_BACKEND).

Backends:
    "s3"       — production; requires SP_WORKSPACE_S3_BUCKET + SP_WORKSPACE_S3_REGION.
    "local"    — local dev; requires SP_WORKSPACE_LOCAL_ROOT.
    "disabled" — default; workspaces are ephemeral. Hard-fails in cloud mode (S11).

Cross-field validators run at settings instantiation. Bad config → ValueError
at startup (fail-fast). No layered fallbacks.

Note: this file is named workspace_storage.py (not storage.py) because
config/storage.py already exists for unrelated crypto settings.
"""

from __future__ import annotations

import os
import re
import tempfile
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ._base import _GatewaySettingsBase

_PREFIX_RE = re.compile(r"^[a-z0-9][a-z0-9/_-]*[a-z0-9]$")

_SNAPSHOT_INTERVAL_MIN = 30
_SNAPSHOT_INTERVAL_MAX = 3600
_SHUTDOWN_DRAIN_MAX = 120


class WorkspaceStorageSettings(_GatewaySettingsBase):
    """Workspace persistence configuration.

    All fields are optional at the class level; cross-field validators enforce
    required combinations (e.g. s3 backend needs bucket + region).
    """

    sp_workspace_backend: Literal["s3", "local", "disabled"] = Field(
        "disabled", alias="SP_WORKSPACE_BACKEND"
    )

    # S3 backend settings
    sp_workspace_s3_bucket: str | None = Field(None, alias="SP_WORKSPACE_S3_BUCKET")
    sp_workspace_s3_region: str | None = Field(None, alias="SP_WORKSPACE_S3_REGION")
    sp_workspace_s3_endpoint_url: str | None = Field(None, alias="SP_WORKSPACE_S3_ENDPOINT_URL")
    sp_workspace_s3_prefix_root: str = Field("workspaces/v1", alias="SP_WORKSPACE_S3_PREFIX_ROOT")

    # Local backend settings
    sp_workspace_local_root: str | None = Field(None, alias="SP_WORKSPACE_LOCAL_ROOT")

    # Operational settings
    sp_workspace_snapshot_interval_seconds: int = Field(
        60, alias="SP_WORKSPACE_SNAPSHOT_INTERVAL_SECONDS"
    )
    sp_workspace_max_file_bytes: int = Field(
        100 * 1024 * 1024, alias="SP_WORKSPACE_MAX_FILE_BYTES"
    )
    sp_workspace_hydrate_timeout_seconds: int = Field(
        60, alias="SP_WORKSPACE_HYDRATE_TIMEOUT_SECONDS"
    )
    sp_workspace_shutdown_drain_seconds: int = Field(
        30, alias="SP_WORKSPACE_SHUTDOWN_DRAIN_SECONDS"
    )
    sp_workspace_tmp_root: str | None = Field(None, alias="SP_WORKSPACE_TMP_ROOT")

    @field_validator("sp_workspace_s3_prefix_root", mode="after")
    @classmethod
    def _validate_prefix_root(cls, v: str) -> str:
        if not _PREFIX_RE.match(v):
            raise ValueError(
                f"SP_WORKSPACE_S3_PREFIX_ROOT must match ^[a-z0-9][a-z0-9/_-]*[a-z0-9]$ "
                f"and must not contain '..'. Got: {v!r}"
            )
        if ".." in v.split("/"):
            raise ValueError(
                f"SP_WORKSPACE_S3_PREFIX_ROOT must not contain '..'. Got: {v!r}"
            )
        return v

    @field_validator("sp_workspace_snapshot_interval_seconds", mode="after")
    @classmethod
    def _validate_interval(cls, v: int) -> int:
        if not (_SNAPSHOT_INTERVAL_MIN <= v <= _SNAPSHOT_INTERVAL_MAX):
            raise ValueError(
                f"SP_WORKSPACE_SNAPSHOT_INTERVAL_SECONDS must be between "
                f"{_SNAPSHOT_INTERVAL_MIN} and {_SNAPSHOT_INTERVAL_MAX}. Got: {v}"
            )
        return v

    @field_validator("sp_workspace_shutdown_drain_seconds", mode="after")
    @classmethod
    def _validate_drain(cls, v: int) -> int:
        if not (0 <= v <= _SHUTDOWN_DRAIN_MAX):
            raise ValueError(
                f"SP_WORKSPACE_SHUTDOWN_DRAIN_SECONDS must be between 0 and "
                f"{_SHUTDOWN_DRAIN_MAX}. Got: {v}"
            )
        return v

    @model_validator(mode="after")
    def _cross_field_validate(self) -> "WorkspaceStorageSettings":
        backend = self.sp_workspace_backend

        if backend == "s3":
            if not self.sp_workspace_s3_bucket:
                raise ValueError(
                    "SP_WORKSPACE_BACKEND=s3 requires SP_WORKSPACE_S3_BUCKET to be set."
                )
            if not self.sp_workspace_s3_region:
                raise ValueError(
                    "SP_WORKSPACE_BACKEND=s3 requires SP_WORKSPACE_S3_REGION to be set."
                )

        if backend == "local" and not self.sp_workspace_local_root:
            raise ValueError(
                "SP_WORKSPACE_BACKEND=local requires SP_WORKSPACE_LOCAL_ROOT to be set."
            )

        if backend == "disabled":
            # S11: disabled + cloud mode → hard-fail
            deployment_mode = os.environ.get("SP_DEPLOYMENT_MODE", "").lower()
            if deployment_mode == "cloud":
                raise ValueError(
                    "disabled backend forbidden in cloud mode. "
                    "Set SP_WORKSPACE_BACKEND to 's3' or 'local'."
                )

        return self

    def effective_tmp_root(self) -> str:
        """Return the tmp root path. Falls back to tempfile.gettempdir() if not set."""
        return self.sp_workspace_tmp_root or tempfile.gettempdir()


@lru_cache(maxsize=1)
def get_workspace_storage_settings() -> WorkspaceStorageSettings:
    """Return cached WorkspaceStorageSettings. Fails fast on bad config."""
    return WorkspaceStorageSettings()
