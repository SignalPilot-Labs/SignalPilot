"""dbt project models."""

from __future__ import annotations

import time
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ._helpers import _validate_string_list


class ProjectSource(str, Enum):  # noqa: UP042 — (str,Enum) keeps str(X.A)=='X.A'; StrEnum returns 'A' and breaks f-string/log output
    """How the dbt project was created or imported."""

    new = "new"
    local = "local"
    github = "github"
    dbt_cloud = "dbt-cloud"


class ProjectStorage(str, Enum):  # noqa: UP042 — (str,Enum) keeps str(X.A)=='X.A'; StrEnum returns 'A' and breaks f-string/log output
    """Whether the project files are managed by SignalPilot or externally linked."""

    managed = "managed"
    linked = "linked"


class ProjectStatus(str, Enum):  # noqa: UP042 — (str,Enum) keeps str(X.A)=='X.A'; StrEnum returns 'A' and breaks f-string/log output
    """Lifecycle status of a dbt project."""

    active = "active"
    error = "error"
    archived = "archived"


class ProjectCreate(BaseModel):
    """Payload for creating a new dbt project."""

    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    connection_name: str = Field(..., min_length=1, max_length=64)
    source: ProjectSource = ProjectSource.new
    # For source="local"
    local_path: str | None = Field(default=None, max_length=4096)
    link_mode: Literal["link", "copy"] = "link"
    # For source="github"
    git_url: str | None = Field(default=None, max_length=2048)
    git_branch: str | None = Field(default=None, max_length=256)
    # For source="dbt-cloud"
    dbt_cloud_token: str | None = None
    dbt_cloud_account_id: str | None = None
    dbt_cloud_project_id: str | None = None
    description: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        return _validate_string_list(v, 64, "tags")


class ProjectUpdate(BaseModel):
    """Partial update for an existing dbt project."""

    connection_name: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = Field(default=None, max_length=50)
    git_remote: str | None = Field(default=None, max_length=2048)
    git_branch: str | None = Field(default=None, max_length=256)
    status: ProjectStatus | None = None
    last_scanned_at: float | None = None
    model_count: int | None = None

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return _validate_string_list(v, 64, "tags")


class ProjectInfo(BaseModel):
    """Persisted metadata for a dbt project."""

    id: str
    name: str
    connection_name: str
    project_dir: str
    storage: ProjectStorage
    source: ProjectSource
    db_type: str
    dbt_version: str = "1.9"
    model_count: int = 0
    status: ProjectStatus = ProjectStatus.active
    created_at: float = Field(default_factory=time.time)
    last_scanned_at: float | None = None
    git_remote: str | None = None
    git_branch: str | None = None
    dbt_cloud_account_id: str | None = None
    dbt_cloud_project_id: str | None = None
    description: str = ""
    tags: list[str] = Field(default_factory=list)
