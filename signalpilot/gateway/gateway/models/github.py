"""Pydantic models for GitHub App endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class GitHubInstallationInfo(BaseModel):
    id: str
    org_id: str
    github_installation_id: int
    github_account_login: str
    github_account_type: str
    permissions: dict | None = None
    status: str
    created_at: float
    updated_at: float


class GitHubRepoInfo(BaseModel):
    id: int
    full_name: str
    name: str
    private: bool
    default_branch: str
    description: str | None = None
    html_url: str


class GitHubRepoLinkCreate(BaseModel):
    project_id: str
    installation_id: str
    repo_full_name: str
    repo_id: int
    default_branch: str = "main"


class GitHubRepoLinkInfo(BaseModel):
    id: str
    org_id: str
    project_id: str
    installation_id: str
    repo_full_name: str
    repo_id: int
    default_branch: str
    status: str
    last_sync_at: float | None = None
    created_at: float
    updated_at: float


class GitCredentialsResponse(BaseModel):
    source: str
    clone_url: str | None = None
    default_branch: str = "main"
    expires_at: float | None = None
