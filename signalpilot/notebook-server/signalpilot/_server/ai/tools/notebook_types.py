from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from signalpilot._types.ids import CellId_t, SessionId

# helper classes
StatusValue = Literal["success", "error", "warning"]


@dataclass
class SuccessResult:
    status: StatusValue = "success"
    auth_required: bool = False
    next_steps: list[str] | None = None
    action_url: str | None = None
    message: str | None = None
    meta: dict[str, Any] | None = None


@dataclass
class EmptyArgs:
    pass


@dataclass
class ToolGuidelines:
    """Structured guidance for AI assistants on when and how to use a tool."""

    when_to_use: list[str] | None = None
    avoid_if: list[str] | None = None
    prerequisites: list[str] | None = None
    side_effects: list[str] | None = None
    additional_info: str | None = None


@dataclass
class SpNotebookInfo:
    name: str
    path: str
    session_id: SessionId


@dataclass
class SpCellErrors:
    cell_id: CellId_t
    errors: list[SpErrorDetail] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)


@dataclass
class SpErrorDetail:
    type: str
    message: str
    traceback: list[str]


@dataclass
class SpCellConsoleOutputs:
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)


@dataclass
class ListSessionsResult:
    sessions: list[SpNotebookInfo] = field(default_factory=list)


@dataclass
class CodeExecutionResult:
    success: bool
    output: str | None = None
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    error: str | None = None
