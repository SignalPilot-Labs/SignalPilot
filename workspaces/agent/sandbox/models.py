"""Sandbox-side shared data models."""

from dataclasses import dataclass


@dataclass
class RepoState:
    """Per-sandbox repo state. Created only by `/repo/bootstrap`.

    One sandbox container serves exactly one run, which owns exactly one
    working branch. `working_branch` is set at bootstrap time and never
    changes for the lifetime of the sandbox.
    """

    repo: str
    base_branch: str
    working_branch: str


@dataclass
class CmdResult:
    """Result of a subprocess invocation from a sandbox handler."""

    stdout: str
    stderr: str
    exit_code: int


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Shared context extracted from SDK hook_input for tool call logging.

    Built once per hook invocation by Session._resolve_tool_context and
    passed to log_tool_call so callers don't juggle positional args.
    """

    tool_name: str
    tool_use_id: str
    agent_id: str | None
    session_id: str | None
    role: str
    duration_ms: int | None
