"""Small MCP envelopes around shared Chats requests and events."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class AgentLaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    task: str = Field(min_length=1, max_length=16000)
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    branch: str | None = Field(default=None, min_length=1, max_length=100)
    connection_name: str | None = Field(default=None, min_length=1, max_length=128)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)


class AgentResult(BaseModel):
    artifacts: list[dict] = Field(default_factory=list)
    artifact_scope: str = "current_chat_manifest"
    status: Literal["queued", "running", "completed", "input_required", "cancelled", "failed"]
    thread_id: str
    run_id: str
    chat_url: str
    summary: str = ""
    question: str | None = None
    error: str | None = None
    error_code: str | None = None
    error_type: str | None = None
    error_stage: str | None = None
    diagnostic: dict | None = None
    diagnostic_context: dict | None = None
    full_trace: str | None = None
    raw_error: str | None = None
    stderr: str | None = None
    raw_error_truncated: bool = False
    stderr_truncated: bool = False
    events: list[dict] = Field(default_factory=list)
    next_sequence: int = 0
    elapsed_seconds: int = 0
    heartbeat: bool = False
    has_more: bool = False
    next_action: str = ""
    usage: dict | None = None
    cost_usd: float | None = None


class AgentContextResult(BaseModel):
    artifacts: list[dict] = Field(default_factory=list)
    artifact_scope: str = "current_chat_manifest"
    thread_id: str
    chat_url: str
    messages: list[dict] = Field(default_factory=list)
    next_message_sequence: int = 0
    has_more: bool = False
