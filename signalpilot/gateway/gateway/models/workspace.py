"""Pydantic models for workspace projects, chat, and agent runs."""

from __future__ import annotations

import time

from pydantic import BaseModel, Field


# ─── Workspace Projects ─────────────────────────────────────────────────────


class WorkspaceProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    display_name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    source: str = Field(default="managed", pattern=r"^(managed|github|dbt-cloud)$")
    connection_name: str | None = None
    git_remote: str | None = Field(None, max_length=500)
    tags: list[str] = Field(default_factory=list)
    settings: dict | None = None


class WorkspaceProjectUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=2000)
    connection_name: str | None = None
    tags: list[str] | None = None
    settings: dict | None = None
    status: str | None = Field(None, pattern=r"^(active|archived)$")


class WorkspaceProjectInfo(BaseModel):
    id: str
    org_id: str
    name: str
    display_name: str
    description: str | None = None
    source: str = "managed"
    connection_name: str | None = None
    s3_prefix: str
    status: str = "active"
    tags: list[str] | None = None
    settings: dict | None = None
    file_count: int = 0
    total_bytes: int = 0
    default_branch: str = "main"
    protected_branches: list[str] | None = None
    git_remote: str | None = None
    created_by: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class FileInfo(BaseModel):
    key: str
    size: int
    last_modified: float


# ─── Branches ────────────────────────────────────────────────────────────────


class BranchCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    from_branch: str = "main"


class BranchInfo(BaseModel):
    id: str
    project_id: str
    org_id: str
    name: str
    created_from: str | None = None
    is_protected: bool = False
    is_default: bool = False
    status: str = "active"
    file_count: int = 0
    total_bytes: int = 0
    created_by: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class UserSessionInfo(BaseModel):
    user_id: str
    project_id: str
    active_branch: str = "main"
    updated_at: float = Field(default_factory=time.time)


class UserSessionUpdate(BaseModel):
    branch: str = Field(..., min_length=1, max_length=100)


# ─── Chat ────────────────────────────────────────────────────────────────────


class ConversationCreate(BaseModel):
    project_id: str | None = None
    title: str | None = Field(None, max_length=200)
    model: str | None = Field(None, max_length=50)


class ConversationInfo(BaseModel):
    id: str
    org_id: str
    user_id: str
    project_id: str | None = None
    title: str | None = None
    agent_session_id: str | None = None
    model: str | None = None
    message_count: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class ChatMessageCreate(BaseModel):
    role: str = Field(..., pattern=r"^(user|assistant|system|tool_call|tool_result)$")
    content: str = Field(..., min_length=1, max_length=500_000)
    metadata_json: dict | None = None


class ChatMessageInfo(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    metadata_json: dict | None = None
    sequence: int
    created_at: float


# ─── Agent Runs ──────────────────────────────────────────────────────────────


class AgentRunCreate(BaseModel):
    project_id: str | None = None
    conversation_id: str | None = None
    agent_type: str = Field(..., max_length=40)
    input_json: dict | None = None
    metadata_json: dict | None = None


class AgentRunUpdate(BaseModel):
    status: str | None = Field(None, pattern=r"^(running|completed|failed|cancelled)$")
    output_json: dict | None = None
    error_message: str | None = Field(None, max_length=10_000)
    completed_at: float | None = None
    duration_ms: float | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    metadata_json: dict | None = None


class AgentRunInfo(BaseModel):
    id: str
    org_id: str
    user_id: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    agent_type: str
    status: str = "pending"
    input_json: dict | None = None
    output_json: dict | None = None
    error_message: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    duration_ms: float | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    metadata_json: dict | None = None
    created_at: float = Field(default_factory=time.time)
