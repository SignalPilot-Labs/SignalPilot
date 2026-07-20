"""Typed terminal actions and state helpers for Slack/Notion intake routing."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.store import analysis_trails
from gateway.string_utils import string_value as _string

IntakeSource = Literal["slack", "notion"]
IntakeOutputMode = Literal["answer", "deliverable"]
IntakeTerminalActionName = Literal[
    "respond_to_user",
    "react_or_ignore",
    "start_notebook_analysis",
    "update_notebook_analysis",
    "update_notion_deliverable",
]
IntakeActionStatus = Literal[
    "posted",
    "ignored",
    "analysis_started",
    "analysis_updated",
    "deliverable_update_started",
    "busy",
    "not_found",
    "failed",
]

TERMINAL_ACTION_NAMES: tuple[IntakeTerminalActionName, ...] = (
    "respond_to_user",
    "react_or_ignore",
    "start_notebook_analysis",
    "update_notebook_analysis",
    "update_notion_deliverable",
)


class IntakeActionValidationError(ValueError):
    """Raised when the model chooses an invalid terminal action."""


@dataclass(frozen=True)
class IntakeTerminalAction:
    name: IntakeTerminalActionName
    arguments: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return _string(self.arguments.get("text")).strip()

    @property
    def prompt(self) -> str:
        return _string(self.arguments.get("prompt")).strip()

    @property
    def output_mode(self) -> IntakeOutputMode:
        mode = _string(self.arguments.get("output_mode")).strip()
        return "deliverable" if mode == "deliverable" else "answer"

    @property
    def reaction_mode(self) -> str:
        return _string(self.arguments.get("mode")).strip()

    @property
    def reaction(self) -> str | None:
        reaction = _string(self.arguments.get("reaction")).strip()
        return reaction or None

    @property
    def deliverable_mode(self) -> str:
        return _string(self.arguments.get("mode")).strip()

    @property
    def render_instruction(self) -> str:
        return _string(self.arguments.get("render_instruction")).strip()

    @property
    def data_instruction(self) -> str | None:
        instruction = _string(self.arguments.get("data_instruction")).strip()
        return instruction or None


@dataclass(frozen=True)
class IntakeActionResult:
    status: IntakeActionStatus
    message: str = ""


@dataclass(frozen=True)
class IntakeAnalysisStatus:
    status: Literal["not_found", "busy", "safe_to_update"]
    trail: Any | None = None

    @property
    def safe_to_update(self) -> bool:
        return self.status == "safe_to_update"


def validate_terminal_action(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    available_terminal_actions: tuple[str, ...] | list[str] | set[str] | None = None,
) -> IntakeTerminalAction:
    if name not in TERMINAL_ACTION_NAMES:
        raise IntakeActionValidationError(f"Unknown terminal action: {name}")
    available = set(available_terminal_actions or TERMINAL_ACTION_NAMES)
    if name not in available:
        raise IntakeActionValidationError(f"Terminal action is not available on this surface: {name}")
    args = dict(arguments or {})

    if name == "respond_to_user":
        if not _string(args.get("text")).strip():
            raise IntakeActionValidationError("respond_to_user requires non-empty text")
    elif name == "react_or_ignore":
        mode = _string(args.get("mode")).strip()
        if mode not in {"react", "ignore"}:
            raise IntakeActionValidationError("react_or_ignore mode must be react or ignore")
        reaction = args.get("reaction")
        if reaction is not None and not _string(reaction).strip():
            raise IntakeActionValidationError("react_or_ignore reaction must be non-empty when provided")
    elif name in {"start_notebook_analysis", "update_notebook_analysis"}:
        if not _string(args.get("prompt")).strip():
            raise IntakeActionValidationError(f"{name} requires non-empty prompt")
        if _string(args.get("output_mode")).strip() not in {"answer", "deliverable"}:
            raise IntakeActionValidationError(f"{name} requires output_mode answer or deliverable")
    elif name == "update_notion_deliverable":
        mode = _string(args.get("mode")).strip()
        if mode not in {"edit_existing", "refresh_data"}:
            raise IntakeActionValidationError("update_notion_deliverable mode must be edit_existing or refresh_data")
        if not _string(args.get("render_instruction")).strip():
            raise IntakeActionValidationError("update_notion_deliverable requires render_instruction")
        if mode == "refresh_data" and not _string(args.get("data_instruction")).strip():
            raise IntakeActionValidationError("update_notion_deliverable refresh_data requires data_instruction")

    return IntakeTerminalAction(name=name, arguments=args)  # type: ignore[arg-type]


async def analysis_status_for_source_thread(
    db: AsyncSession,
    *,
    org_id: str,
    source: IntakeSource,
    source_thread_id: str,
    active_stale_seconds: float,
) -> IntakeAnalysisStatus:
    if not source_thread_id:
        return IntakeAnalysisStatus(status="not_found")
    trail = await analysis_trails.latest_trail_for_source_thread_id(
        db,
        org_id=org_id,
        source=source,
        source_thread_id=source_thread_id,
    )
    if trail is None:
        return IntakeAnalysisStatus(status="not_found")
    if trail.status == "active" and trail.updated_at >= time.time() - active_stale_seconds:
        return IntakeAnalysisStatus(status="busy", trail=trail)
    return IntakeAnalysisStatus(status="safe_to_update", trail=trail)


def analysis_status_payload(status: IntakeAnalysisStatus) -> dict[str, Any]:
    trail = status.trail
    if trail is None:
        return {"status": status.status, "safeToUpdate": False}
    return {
        "status": status.status,
        "safeToUpdate": status.safe_to_update,
        "trailStatus": _string(getattr(trail, "status", "")),
        "requestId": _string(getattr(trail, "request_id", "")),
        "threadId": _string(getattr(trail, "thread_id", "")),
        "notebookPath": _string(getattr(trail, "notebook_path", "")),
        "projectId": _string(getattr(trail, "project_id", "")),
        "branch": _string(getattr(trail, "branch", "")),
        "sourceThreadId": _string(getattr(trail, "source_thread_id", "")),
        "sourceUrl": _string(getattr(trail, "source_url", "")),
        "updatedAt": getattr(trail, "updated_at", None),
    }
