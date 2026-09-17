"""Per-run execution ownership for the standalone chat /execute route.

The gateway worker can re-claim a run whose lease expired and POST /execute
again with the SAME run id while the previous attempt is still alive in this
process. Without ownership tracking the old attempt keeps running and, when
it finally ends, closes every kernel it knew and deletes the shared scratch
directory the new attempt is using.

This module makes /execute idempotent per run id:

- ``take_over_run`` stops the previous attempt's agent, marks its record
  superseded, and hands its live notebook sessions and scratch to the new
  attempt so the resumed model's session ids stay valid.
- A superseded attempt's cleanup skips kernel close and scratch removal.
  Only the newest attempt owns cleanup.
- ``release_run`` drops the registry entry only when the finishing attempt
  still owns it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from signalpilot import _loggers
from signalpilot._server.api.endpoints.standalone_chat_runtime import (
    _ANALYSIS_SESSIONS_BY_RUN,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from signalpilot._server.ai.standalone_chat_tools import (
        StandaloneNotebookLifecycle,
    )

__all__ = [
    "RunExecution",
    "make_lifecycle_event",
    "release_run",
    "run_execution_lock",
    "supersede_run",
    "take_over_run",
]

LOGGER = _loggers.sp_logger()


@dataclass
class RunExecution:
    """One /execute attempt's ownership record for a run id."""

    run_id: str
    sequence: int
    superseded: bool = False
    # The attempt's current notebook lifecycle (replaced on a clean retry).
    lifecycle: Any | None = None
    # The scratch directory the attempt's notebooks live in.
    working_scratch: Path | None = None
    attempt: int = 0
    sessions_snapshot: dict[str, str] = field(default_factory=dict)

    @property
    def sessions(self) -> dict[str, str]:
        if self.lifecycle is not None:
            return dict(self.lifecycle.sessions)
        return dict(self.sessions_snapshot)


_RUN_EXECUTIONS: dict[str, RunExecution] = {}
_RUN_LOCKS: dict[str, asyncio.Lock] = {}


def run_execution_lock(run_id: str) -> asyncio.Lock:
    """The per-run lock that serializes attempt handover."""
    lock = _RUN_LOCKS.get(run_id)
    if lock is None:
        lock = asyncio.Lock()
        _RUN_LOCKS[run_id] = lock
    return lock


def supersede_run(
    run_id: str,
    *,
    stop_agent_fn: Callable[[str], bool],
    reason: str,
) -> RunExecution | None:
    """Stop the run's live agent and mark its attempt superseded.

    The superseded attempt's cleanup then leaves kernels and scratch alone.
    Returns the superseded record, or None when no attempt is active.
    """
    previous = _RUN_EXECUTIONS.get(run_id)
    if previous is None:
        return None
    if not previous.superseded:
        stopped = stop_agent_fn(f"standalone-{run_id}")
        previous.superseded = True
        # Freeze the session map now: the old lifecycle may still mutate.
        previous.sessions_snapshot = previous.sessions
        LOGGER.info(
            "Standalone chat attempt superseded run_id=%s sequence=%s "
            "agent_stopped=%s sessions=%s reason=%s",
            run_id,
            previous.sequence,
            stopped,
            sorted(previous.sessions_snapshot),
            reason,
        )
    return previous


def take_over_run(
    run_id: str,
    *,
    stop_agent_fn: Callable[[str], bool],
) -> tuple[RunExecution, tuple[Path, dict[str, str]] | None]:
    """Register a new /execute attempt for ``run_id``.

    Call under ``run_execution_lock(run_id)``. Any previous attempt is
    superseded first. Returns the new record plus the previous attempt's
    (scratch, sessions) when it had live notebooks to inherit.
    """
    previous = supersede_run(
        run_id, stop_agent_fn=stop_agent_fn, reason="re-execute"
    )
    record = RunExecution(
        run_id=run_id,
        sequence=(previous.sequence + 1) if previous is not None else 1,
    )
    _RUN_EXECUTIONS[run_id] = record
    inherited: tuple[Path, dict[str, str]] | None = None
    if (
        previous is not None
        and previous.working_scratch is not None
        and previous.sessions_snapshot
    ):
        inherited = (previous.working_scratch, dict(previous.sessions_snapshot))
    return record, inherited


def release_run(record: RunExecution) -> bool:
    """Drop the registry entry if ``record`` is still the run's owner."""
    current = _RUN_EXECUTIONS.get(record.run_id)
    if current is not record:
        return False
    _RUN_EXECUTIONS.pop(record.run_id, None)
    _RUN_LOCKS.pop(record.run_id, None)
    return True


def make_lifecycle_event(
    *,
    run_id: str,
    runtime_app: Any,
    lifecycle: StandaloneNotebookLifecycle,
    attempt: int,
    session_resolver: Callable[[Any, str], Any],
) -> Callable[..., Any]:
    """Build the event sink that records every started kernel of a run."""

    async def lifecycle_event(
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if event_type != "notebook_started":
            return
        started_session = (
            str(payload.get("session_id") or "") or lifecycle.session_id
        )
        if not started_session:
            return
        _ANALYSIS_SESSIONS_BY_RUN.setdefault(run_id, set()).add(
            started_session
        )
        runtime_session = session_resolver(runtime_app, started_session)
        runtime_session._signalpilot_chat_run_id = run_id
        runtime_session._signalpilot_chat_session_id = started_session
        runtime_session._signalpilot_chat_attempt = attempt

    return lifecycle_event
