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
