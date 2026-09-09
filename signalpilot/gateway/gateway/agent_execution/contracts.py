"""Public, bounded agent inputs and outputs."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    task: str = Field(min_length=1, max_length=16000)
    project_id: str = Field(min_length=1, max_length=128)
    branch: str = Field(default="main", min_length=1, max_length=100)
    revision: int = Field(ge=1)
    connection_name: str = Field(min_length=1, max_length=128)
    max_turns: int = Field(default=24, ge=1, le=100)
    timeout_seconds: int = Field(default=1200, ge=30, le=1200)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)


class RuntimeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["completed", "input_required"]
    summary: str = Field(max_length=12000)
    question: str | None = Field(default=None, max_length=2000)
    verification: list[Annotated[str, Field(max_length=2000)]] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def require_question(self):
        if self.status == "input_required" and not (self.question or "").strip():
            raise ValueError("Input-required results must include a question")
        return self


class AgentResult(BaseModel):
    status: Literal["queued", "running", "completed", "input_required", "cancelled", "failed"]
    thread_id: str
    run_id: str
    summary: str = ""
    question: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    output: dict | None = None
    verification: list[str] = Field(default_factory=list)
    error: str | None = None
    events: list[dict] = Field(default_factory=list)
    next_sequence: int = 0
    elapsed_seconds: int = 0
    heartbeat: bool = False
    has_more: bool = False
    next_action: str = ""
