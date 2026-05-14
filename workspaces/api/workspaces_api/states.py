"""Run state machine — single source of truth for RunState and legal transitions."""

from __future__ import annotations

from enum import Enum

from workspaces_api.errors import IllegalTransition


class RunState(str, Enum):
    queued = "queued"
    running = "running"
    awaiting_approval = "awaiting_approval"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


_LEGAL_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.queued: {RunState.running, RunState.failed},
    RunState.running: {
        RunState.awaiting_approval,
        RunState.succeeded,
        RunState.failed,
        RunState.cancelled,
    },
    RunState.awaiting_approval: {RunState.running, RunState.cancelled},
    RunState.succeeded: set(),
    RunState.failed: set(),
    RunState.cancelled: set(),
}


def transition(current: RunState, target: RunState) -> RunState:
    """Validate and return the target state, raising IllegalTransition if not allowed.

    Args:
        current: The current run state.
        target: The desired next run state.

    Returns:
        The target state if the transition is legal.

    Raises:
        IllegalTransition: If the transition from current to target is not permitted.
    """
    allowed = _LEGAL_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise IllegalTransition(
            f"Cannot transition run from '{current.value}' to '{target.value}'."
        )
    return target
