"""Data models for the sandbox manager."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExecutionResult:
    """Result of a code execution in a sandbox."""

    success: bool
    output: str
    error: str | None
    execution_ms: float
    vm_id: str


@dataclass
class CellResult:
    """Result of a single cell execution in a kernel session."""

    success: bool
    output: str
    error: str | None
    execution_ms: float
    cell_id: str | None = None
    outputs: list[dict] | None = None
    execution_count: int = 0


@dataclass
class SessionInfo:
    """Summary of a kernel session."""

    id: str
    status: str
    created_at: float
    last_active: float
    cell_count: int = 0
