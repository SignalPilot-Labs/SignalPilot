"""Pydantic models for GitHub App endpoints."""

from __future__ import annotations

from pydantic import BaseModel

from .workspace import WorkspaceProjectInfo


class GitHubInstallationInfo(BaseModel):
    id: str
    org_id: str
    github_installation_id: int
    github_account_login: str
    github_account_type: str
    permissions: dict | None = None
    status: str
    authorized_repository_count: int = 0
    repositories: list[str] = []
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


class GitHubRepoImportRequest(BaseModel):
    installation_id: str
    repo_full_name: str
    repo_id: int
    default_branch: str = "main"


class GitHubRepoImportResult(BaseModel):
    project: WorkspaceProjectInfo
    link: GitHubRepoLinkInfo
    created: bool


class GitCredentialsResponse(BaseModel):
    source: str
    clone_url: str | None = None
    default_branch: str = "main"
    expires_at: float | None = None


class AgentPullRequestCreate(BaseModel):
    """Open a pull request for a branch the chat agent already pushed."""

    project_id: str
    github_branch: str
    title: str
    body: str = ""
    draft: bool = False
    base_branch: str | None = None
    conversation_id: str | None = None


class AgentPullRequestUpdate(BaseModel):
    title: str | None = None
    body: str | None = None


class AgentPullRequestCommentCreate(BaseModel):
    body: str


class AgentPullRequestCommentInfo(BaseModel):
    pr_url: str | None = None
    pr_number: int | None = None
    comment_url: str | None = None


class AgentPullRequestInfo(BaseModel):
    """Status is one of pushed (branch on GitHub, no PR yet), open, merged, closed, error."""

    id: str
    org_id: str
    project_id: str
    conversation_id: str | None = None
    repo_full_name: str
    source_branch: str
    github_branch: str
    base_branch: str
    pr_number: int | None = None
    pr_url: str | None = None
    title: str
    status: str
    error_message: str | None = None
    export_commit_sha: str | None = None
    last_pushed_sha: str | None = None
    last_pushed_at: float | None = None
    draft: bool = False
    created_by: str
    created_at: float
    updated_at: float
