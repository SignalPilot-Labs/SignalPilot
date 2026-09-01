"""Validation and finalization helpers for standalone chat runs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from signalpilot import _loggers
from signalpilot._server.ai.standalone_chat_tools import (
    _collected_artifact_is_complete,
)

if TYPE_CHECKING:
    from collections.abc import Callable

LOGGER = _loggers.sp_logger()


def _notebook_edit_requires_successful_run(
    *, notebook_cells_edited: bool, successful_run_cells: bool
) -> bool:
    """Require execution evidence only after the agent changed notebook cells."""
    return notebook_cells_edited and not successful_run_cells


def ordered_notebook_names(sessions: dict[str, str]) -> list[str]:
    """Deterministic notebook order with the analysis notebook first."""
    names = ["analysis"] if "analysis" in sessions else []
    names.extend(sorted(name for name in sessions if name != "analysis"))
    return names


def notebook_session_lines(sessions: dict[str, str]) -> str:
    """Prompt-injection enumeration of name to session id pairs."""
    return "\n".join(
        f"- {name}: `{sessions[name]}`"
        for name in ordered_notebook_names(sessions)
    )


def continuity_injection(
    prompt: str, adopted_sessions: dict[str, str]
) -> str:
    """Prompt injection for adopted kernels from the previous turn."""
    analysis_id = adopted_sessions.get("analysis")
    if set(adopted_sessions) == {"analysis"}:
        return (
            f"{prompt}\n\n<notebook_continuity>\n"
            "The analysis notebook from the previous turn is "
            "still running with its cells and variables. Use "
            f"session_id `{analysis_id}` with the notebook "
            "tools to add or edit cells. Do not start a new "
            "notebook. If a gateway call from a notebook cell "
            "fails with an authorization error, run the setup "
            "cell again; it reads a refreshed token.\n"
            "</notebook_continuity>"
        )
    lines = [
        f"{prompt}\n\n<notebook_continuity>",
        "These notebooks from the previous turn are still running with "
        "their cells and variables. Use these session ids with the "
        "notebook tools:",
        notebook_session_lines(adopted_sessions),
        "Do not start these notebooks again.",
    ]
    if analysis_id is None:
        lines.append(
            "The analysis notebook is not running. Start it with "
            "start_analysis_notebook when you need it."
        )
    lines.append(
        "If a gateway call from a notebook cell fails with an "
        "authorization error, run the setup cell again; it reads a "
        "refreshed token.\n</notebook_continuity>"
    )
    return "\n".join(lines)


def recovery_injection(
    prompt: str,
    recovery_failure: dict[str, Any],
    sessions: dict[str, str],
    recovery_context_fn: Callable[[dict[str, Any]], str],
) -> str:
    """Prompt injection after the analysis notebook restarts clean."""
    text = (
        f"{prompt}\n\n<notebook_recovery>\n"
        f"{recovery_context_fn(recovery_failure)}\n"
        "The clean notebook kernel is already running. Use "
        f"session_id `{sessions.get('analysis')}`; do not create a "
        "different session. Plan each database query before "
        "executing it.\n"
    )
    survivors = {
        name: session_id
        for name, session_id in sessions.items()
        if name != "analysis"
    }
    if survivors:
        text += (
            "These named notebooks survived the restart and are still "
            "running. Use these session ids with the notebook tools:\n"
            f"{notebook_session_lines(survivors)}\n"
        )
    return text + "</notebook_recovery>"


def evaluate_notebook_failure(
    runtime_app: Any,
    *,
    analysis_session_id: str | None,
    recovery_failure: dict[str, Any] | None,
    previous_notebook_session_id: str | None,
    notebook_cells_edited: bool,
    successful_run_cells: bool,
    notebook_failure_fn: Callable[[Any, str], dict[str, Any] | None],
    session_resolver: Callable[[Any, str], Any],
    record_errors_fn: Callable[[Any, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any] | None:
    """Run-level validation gate. Only the analysis notebook is subject
    to the evidence-validation and abandonment-reject rules."""
    if analysis_session_id:
        notebook_failure = notebook_failure_fn(
            runtime_app, analysis_session_id
        )
        if (
            recovery_failure is not None
            and analysis_session_id == previous_notebook_session_id
        ):
            notebook_failure = {
                "error": {
                    "type": "NotebookSessionReuseError",
                    "variable": None,
                    "cell_ids": [],
                }
            }
        elif _notebook_edit_requires_successful_run(
            notebook_cells_edited=notebook_cells_edited,
            successful_run_cells=successful_run_cells,
        ):
            notebook_failure = {
                "error": {
                    "type": "NotebookEvidenceNotValidatedError",
                    "variable": None,
                    "cell_ids": [],
                }
            }
        if notebook_failure is not None:
            notebook_failure = record_errors_fn(
                session_resolver(runtime_app, analysis_session_id),
                notebook_failure,
            )
        return notebook_failure
    if recovery_failure is not None:
        return {
            "error": {
                "type": "NotebookNotRestartedError",
                "variable": None,
                "cell_ids": [],
            }
        }
    return None


async def archive_run_notebooks(
    runtime_app: Any,
    *,
    sessions: dict[str, str],
    run_id: str,
    attempt: int,
    gateway_api_url: str,
    scoped_token: str,
    archive_fn: Callable[..., Any],
) -> tuple[str | None, dict[str, Any] | None]:
    """Archive every started notebook, analysis first.

    Returns (analysis_archive_id, error_payload). Only the ANALYSIS archive
    failure produces an error payload; a named notebook's failure logs and
    continues.
    """
    import traceback

    archive_id: str | None = None
    for notebook_name in ordered_notebook_names(sessions):
        archive_session = sessions[notebook_name]
        try:
            named_archive_id = await archive_fn(
                app=runtime_app,
                session_id=archive_session,
                run_id=run_id,
                gateway_api_url=gateway_api_url,
                scoped_token=scoped_token,
                notebook_name=notebook_name,
            )
        except Exception as exc:
            LOGGER.error(
                "Standalone notebook archive failed run_id=%s notebook=%s "
                "session_id=%s attempt=%s error_type=%s",
                run_id,
                notebook_name,
                archive_session,
                attempt,
                type(exc).__name__,
            )
            if notebook_name != "analysis":
                continue
            return archive_id, {
                "type": "error",
                "content": str(exc) if str(exc) else repr(exc),
                "full_trace": traceback.format_exc(),
                "diagnostic_context": {
                    "error_type": type(exc).__name__,
                    "operation": "archive_analysis_notebook",
                },
                "is_error": True,
            }
        if notebook_name == "analysis":
            archive_id = named_archive_id
    return archive_id, None


def resolve_report_outcome(collector: Any, *, run_id: str) -> None:
    """Backfill a no_suggestion outcome when the agent skipped the decision."""
    complete_artifacts = [
        artifact
        for artifact in collector.artifacts
        if _collected_artifact_is_complete(artifact)
    ]
    if not complete_artifacts or collector.report_action_outcome is not None:
        return
    artifact = complete_artifacts[-1]
    LOGGER.warning(
        "Completed standalone artifact had no report action outcome "
        "run_id=%s kind=%s filename=%s",
        run_id,
        artifact.get("kind"),
        artifact.get("filename"),
    )
    collector.report_action_outcome = {
        "action": "no_suggestion",
        "artifact_kind": artifact.get("kind"),
        "artifact_filename": artifact.get("filename"),
        "title": artifact.get("filename"),
        "reason": (
            "The analysis agent completed without recording the required "
            "catalog-backed report decision."
        ),
        "source": "completion_check",
        "catalog_revision": collector.report_catalog_revision,
        "catalog_scan_complete": collector.report_catalog_scan_complete,
    }


def build_final_payload(
    collector: Any,
    *,
    accepted_text: str,
    agent_cost_usd: float | None,
    agent_usage: dict[str, Any] | None,
    archive_id: str | None,
    kernel_stopped: bool,
) -> dict[str, Any]:
    final_payload: dict[str, Any] = {
        "type": "final",
        "content": accepted_text,
        "artifacts": collector.artifacts,
    }
    if agent_cost_usd is not None:
        final_payload["cost_usd"] = agent_cost_usd
    if agent_usage is not None:
        final_payload["usage"] = agent_usage
    if collector.report_proposal is not None:
        final_payload["report_proposal"] = collector.report_proposal
    if collector.report_action_outcome is not None:
        final_payload["report_action_outcome"] = (
            collector.report_action_outcome
        )
    if archive_id is not None:
        final_payload["archive_id"] = archive_id
        final_payload["kernel_stopped"] = kernel_stopped
    return final_payload
