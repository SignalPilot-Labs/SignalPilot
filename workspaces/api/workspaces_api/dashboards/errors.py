"""Typed exceptions for chart execution failures."""

from __future__ import annotations

from workspaces_api.errors import WorkspacesError


class ChartExecutionFailed(WorkspacesError):
    """Raised when the dbt-proxy returns a database error during chart execution.

    HTTP status: 502.
    Public body: {error_code, correlation_id} only — no internal detail.
    """

    error_code = "chart_execution_failed"

    def __init__(self, correlation_id: str) -> None:
        super().__init__(
            f"chart execution failed cid={correlation_id}",
            correlation_id=correlation_id,
        )


class ChartExecutionTimeout(WorkspacesError):
    """Raised when chart execution exceeds the total deadline.

    HTTP status: 504.
    Public body: {error_code, correlation_id} only — no internal detail.
    """

    error_code = "chart_execution_timeout"

    def __init__(self, correlation_id: str) -> None:
        super().__init__(
            f"chart execution timed out cid={correlation_id}",
            correlation_id=correlation_id,
        )


__all__ = ["ChartExecutionFailed", "ChartExecutionTimeout"]
