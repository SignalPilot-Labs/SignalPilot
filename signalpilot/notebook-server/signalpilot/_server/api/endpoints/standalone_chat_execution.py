"""Streaming execution and cancellation routes for standalone chat."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from typing import TYPE_CHECKING, Any

from starlette.authentication import requires

from signalpilot import _loggers
from signalpilot._server.ai.claude_agent import (
    clear_chat_session,
    run_notebook_agent,
)
from signalpilot._server.ai.claude_session_archive import (
    persist_claude_session,
    prepare_claude_session,
)
from signalpilot._server.ai.standalone_chat_tools import (
    StandaloneArtifactCollector,
    StandaloneNotebookLifecycle,
    _collected_artifact_is_complete,
    build_standalone_chat_mcp_server,
)
from signalpilot._server.api.endpoints.standalone_chat_finalize import (
    _notebook_edit_requires_successful_run,
    archive_run_notebooks,
    build_final_payload,
    continuity_injection,
    evaluate_notebook_failure,
    recovery_injection,
    resolve_report_outcome,
)
from signalpilot._server.api.endpoints.standalone_chat_gateway import (
    StandaloneGatewayClient,
)
from signalpilot._server.api.endpoints.standalone_chat_prompt import (
    STANDALONE_ALLOWED_TOOLS,
    STANDALONE_DISALLOWED_MCP_TOOLS,
    _execution_prompt_values,
)
from signalpilot._server.api.endpoints.standalone_chat_response import (
    stream_response,
)
from signalpilot._server.api.endpoints.standalone_chat_runtime import (
    _ANALYSIS_SESSIONS_BY_RUN,
    _analysis_session,
    _archive_analysis_notebook,
    _close_analysis_kernel,
    _log_notebook_failure,
    _notebook_failure,
    _project_is_unchanged,
    _recovery_context,
    _runtime_auth_override,
    _seed_notebook_file,
    _start_analysis_kernel,
    _with_recorded_notebook_errors,
    adopt_keepalive_analysis_session,
    register_keepalive_analysis_session,
)
from signalpilot._server.api.endpoints.standalone_chat_stream import (
    AgentRunState,
    _ndjson,
    announce_adopted_sessions,
    forward_agent_events,
    start_recovery_analysis,
)
from signalpilot._server.api.endpoints.standalone_chat_workspace import (
    prepare_execution_workspace,
)
from signalpilot._server.auth.standalone_chat import (
    authorize_execution,
    gateway_mcp_config,
)
from signalpilot._server.router import APIRouter
from signalpilot._types.ids import SessionId

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from starlette.requests import Request
    from starlette.responses import StreamingResponse

__all__ = [
    "MAX_ANALYSIS_AGENT_TURNS",
    "_collected_artifact_is_complete",
    "_notebook_edit_requires_successful_run",
    "execute",
    "router",
]

router = APIRouter()
LOGGER = _loggers.sp_logger()
MAX_ANALYSIS_AGENT_TURNS = 200


@router.post("/execute")
@requires("edit")
async def execute(*, request: Request) -> StreamingResponse:
    body = await request.json()
    authorization = authorize_execution(body)
    scope = authorization.scope
    run_id = scope.run_id
    conversation_id = str(
        body.get("conversation_id")
        or uuid.uuid5(uuid.NAMESPACE_URL, f"signalpilot:standalone:{run_id}")
    )
    project_id = scope.project_id
    branch = scope.branch
    connection_name = scope.connection_name
    commit_sha = scope.commit_sha
    mcp_config = gateway_mcp_config(authorization)
    runtime_app = request.scope.get("app")
    (
        prompt,
        history,
        is_improvement_run,
        sandbox_runtime_enabled,
        system_prompt,
    ) = _execution_prompt_values(
        body,
        project_id=project_id,
        branch=branch,
        commit_sha=commit_sha,
        connection_name=connection_name,
    )
    scoped_token = authorization.gateway_token
    gateway_api_url = str(
        os.getenv("SP_GATEWAY_INTERNAL_URL")
        or os.getenv("SP_GATEWAY_URL")
        or "http://gateway:3300"
    ).rstrip("/")
    if gateway_api_url.endswith("/mcp"):
        gateway_api_url = gateway_api_url.removesuffix("/mcp")

    gateway = StandaloneGatewayClient(
        gateway_url=gateway_api_url,
        token=scoped_token,
        run_id=run_id,
    )
    load_result = gateway.load_result
    load_report_catalog = gateway.load_report_catalog
    load_report_context = gateway.load_report_context
    check_published_artifact = gateway.check_published_artifact

    auth_config_override = _runtime_auth_override(body)
    agent_model = str(
        body.get("model")
        or os.getenv("SIGNALPILOT_ANALYSIS_AGENT_MODEL")
        or "claude-sonnet-4-5-20250929"
    )
    session_id = SessionId(f"standalone-{run_id}")

    def seed_notebook(scratch_dir: Path, notebook_name: str) -> Path:
        # One shared scratch per conversation holds every named notebook.
        return _seed_notebook_file(
            scratch=scratch_dir,
            name=notebook_name,
            run_id=run_id,
            project_id=project_id,
            connection_name=connection_name,
            gateway_url=gateway_api_url,
        )

    # Multi-turn continuity: adopt the conversation's kept-alive kernels and
    # notebooks from the previous turn when they are still running — the agent
    # reuses the SAME session ids across turns and the live notebook panel
    # stays attached. Falls back to a fresh notebook when no kernel survives.
    # scope.get: unit tests build bare Requests without an app.
    adopted = adopt_keepalive_analysis_session(
        request.scope.get("app"),
        conversation_id,
        scoped_token=scoped_token,
    )
    adopted_sessions: dict[str, str] = dict(adopted[1]) if adopted else {}
    (
        scratch,
        analysis_notebook_path,
        seeded_notebook_source,
        project_directory,
        remove_project_directory,
        project_baseline_digest,
    ) = await prepare_execution_workspace(
        run_id=run_id,
        conversation_id=conversation_id,
        project_id=project_id,
        branch=branch,
        connection_name=connection_name,
        gateway_url=gateway_api_url,
        gateway_token=scoped_token,
    )
    # The agent writes user-facing files here. The env override below points
    # SP_CHAT_ARTIFACTS_DIRECTORY at it.
    (scratch / "artifacts").mkdir(exist_ok=True)
    if adopted is not None:
        # Continue in the previous turn's shared scratch and notebooks.
        analysis_notebook_path = adopted[0] / "analysis.py"
        if not analysis_notebook_path.is_file():
            # The analysis kernel died between turns while a named notebook
            # survived. Reseed the analysis file so the agent can restart it.
            seed_notebook(adopted[0], "analysis")
    try:
        agent_session = await prepare_claude_session(
            conversation_id=conversation_id,
            cwd=project_directory,
            transfer=body.get("agent_session"),
        )
    except Exception:
        LOGGER.warning(
            "Claude session restore failed; using database context run_id=%s",
            run_id,
            exc_info=True,
        )
        agent_session = await prepare_claude_session(
            conversation_id=conversation_id,
            cwd=project_directory,
            transfer=None,
        )

    async def stream() -> AsyncGenerator[bytes, None]:
        current_lifecycle: StandaloneNotebookLifecycle | None = None
        # Set on the success path: the kernels + notebooks survive the run
        # for the live notebook panel, so the scratch dir must survive too.
        keep_workspace = False
        resume_agent_session = agent_session.resume

        async def save_agent_session() -> None:
            try:
                await persist_claude_session(agent_session)
            except Exception:
                LOGGER.warning(
                    "Claude session persistence failed run_id=%s",
                    run_id,
                    exc_info=True,
                )

        try:
            recovery_failure: dict[str, Any] | None = None
            previous_notebook_session_id: str | None = None
            # Non-analysis kernels survive a recovery restart untouched.
            carryover_sessions: dict[str, str] = {}
            for attempt in (1, 2):
                collector = StandaloneArtifactCollector()
                lifecycle = StandaloneNotebookLifecycle()
                lifecycle.sessions.update(carryover_sessions)
                current_lifecycle = lifecycle

                async def lifecycle_event(
                    event_type: str,
                    payload: dict[str, Any],
                    lifecycle: StandaloneNotebookLifecycle = lifecycle,
                    attempt: int = attempt,
                ) -> None:
                    if event_type != "notebook_started":
                        return
                    started_session = (
                        str(payload.get("session_id") or "")
                        or lifecycle.session_id
                    )
                    if not started_session:
                        return
                    _ANALYSIS_SESSIONS_BY_RUN.setdefault(run_id, set()).add(
                        started_session
                    )
                    runtime_session = _analysis_session(
                        runtime_app, started_session
                    )
                    runtime_session._signalpilot_chat_run_id = run_id
                    runtime_session._signalpilot_chat_session_id = (
                        started_session
                    )
                    runtime_session._signalpilot_chat_attempt = attempt

                if (
                    recovery_failure is None
                    and attempt == 1
                    and adopted_sessions
                ):
                    # Adopted kernels from the previous turn: pre-seed the
                    # lifecycle so the notebook tools authorize each session
                    # immediately, and re-announce every one so the live
                    # notebook panel (re)attaches for this run.
                    lifecycle.sessions.update(adopted_sessions)
                    async for chunk in announce_adopted_sessions(
                        runtime_app,
                        adopted_sessions=adopted_sessions,
                        scratch=analysis_notebook_path.parent,
                        scoped_token=scoped_token,
                        session_resolver=_analysis_session,
                        lifecycle_event=lifecycle_event,
                    ):
                        yield chunk

                if recovery_failure is not None:
                    async for chunk in start_recovery_analysis(
                        runtime_app,
                        lifecycle=lifecycle,
                        notebook_path=analysis_notebook_path,
                        run_id=run_id,
                        attempt=attempt,
                        scoped_token=scoped_token,
                        start_fn=_start_analysis_kernel,
                        session_resolver=_analysis_session,
                        lifecycle_event=lifecycle_event,
                    ):
                        yield chunk
                    if not lifecycle.session_id:
                        # The clean kernel did not start; the error already
                        # streamed.
                        return

                artifact_server = build_standalone_chat_mcp_server(
                    collector,
                    result_loader=load_result,
                    project_directory=project_directory,
                    scratch_directory=scratch,
                    notebook_mcp_app=runtime_app,
                    analysis_notebook_path=analysis_notebook_path,
                    event_sink=lifecycle_event,
                    notebook_lifecycle=lifecycle,
                    runtime_redactions=(scoped_token,),
                    notebook_seeder=(
                        lambda notebook_name: seed_notebook(
                            analysis_notebook_path.parent, notebook_name
                        )
                    ),
                    report_catalog_loader=load_report_catalog,
                    report_context_loader=load_report_context,
                    published_artifact_checker=check_published_artifact,
                    attached_report_id=str(
                        (
                            (body.get("warm_context") or {}).get(
                                "report_reference"
                            )
                            or {}
                        ).get("report_id")
                        or ""
                    )
                    or None,
                )
                attempt_prompt = prompt
                if recovery_failure is not None:
                    attempt_prompt = recovery_injection(
                        prompt,
                        recovery_failure,
                        lifecycle.sessions,
                        _recovery_context,
                    )
                elif attempt == 1 and adopted_sessions:
                    attempt_prompt = continuity_injection(
                        prompt, adopted_sessions
                    )

                state = AgentRunState()
                async for chunk in forward_agent_events(
                    run_notebook_agent(
                        attempt_prompt,
                        session_id,
                        model=agent_model,
                        max_turns=MAX_ANALYSIS_AGENT_TURNS,
                        new_chat=False,
                        message_history=history,
                        system_prompt_override=system_prompt,
                        mcp_config=mcp_config,
                        thread_id=f"standalone:{run_id}",
                        notebook_mcp_app=runtime_app,
                        cwd=str(project_directory),
                        # Expose the normal SignalPilot workflow. Xata branch
                        # control stays denied because this run is already
                        # pinned to a frozen project branch and database
                        # connection.
                        disallow_file_edits=False,
                        additional_disallowed_tools=(
                            STANDALONE_DISALLOWED_MCP_TOOLS
                        ),
                        allowed_tools=list(STANDALONE_ALLOWED_TOOLS),
                        additional_mcp_servers={
                            "standalone-chat": artifact_server
                        },
                        persist_session_mapping=False,
                        auth_config_override=auth_config_override,
                        chat_session_id_override=agent_session.session_id,
                        resume_session_override=resume_agent_session,
                        agent_env_overrides={
                            "CLAUDE_CONFIG_DIR": str(
                                agent_session.config_dir
                            ),
                            # The system prompt directs every scratch file
                            # here. Without this the agent's shell resolves
                            # the path to an empty string and files land
                            # outside the mirrored scratch root, invisible to
                            # the artifacts panel.
                            "SP_CHAT_SCRATCH_DIRECTORY": str(scratch),
                            "SP_CHAT_ARTIFACTS_DIRECTORY": str(
                                scratch / "artifacts"
                            ),
                        },
                        notebook_session_authorizer=(
                            lambda candidate, lifecycle=lifecycle: (
                                candidate in lifecycle.sessions.values()
                            )
                        ),
                    ),
                    state=state,
                    agent_model=agent_model,
                    auth_config_override=auth_config_override,
                    resume_agent_session=resume_agent_session,
                    max_turns=MAX_ANALYSIS_AGENT_TURNS,
                    analysis_session=lambda lifecycle=lifecycle: (
                        lifecycle.session_id
                    ),
                ):
                    yield chunk
                await save_agent_session()
                resume_agent_session = True
                if state.agent_failed:
                    return

                if (
                    project_directory is not None
                    and not await asyncio.to_thread(
                        _project_is_unchanged,
                        project_directory,
                        project_baseline_digest,
                    )
                ):
                    yield _ndjson(
                        {
                            "type": "error",
                            "content": "The frozen project workspace changed; the run was rejected.",
                            "is_error": True,
                        }
                    )
                    return

                notebook_failure = evaluate_notebook_failure(
                    runtime_app,
                    analysis_session_id=lifecycle.session_id,
                    recovery_failure=recovery_failure,
                    previous_notebook_session_id=(
                        previous_notebook_session_id
                    ),
                    notebook_cells_edited=state.notebook_cells_edited(
                        lifecycle.session_id
                    ),
                    successful_run_cells=state.successful_run_cells(
                        lifecycle.session_id
                    ),
                    notebook_failure_fn=_notebook_failure,
                    session_resolver=_analysis_session,
                    record_errors_fn=_with_recorded_notebook_errors,
                )

                if notebook_failure is not None:
                    active_session_id = str(lifecycle.session_id or "")
                    _log_notebook_failure(
                        run_id=run_id,
                        session_id=active_session_id,
                        attempt=attempt,
                        failure=notebook_failure,
                    )
                    if attempt == 1 and lifecycle.session_id:
                        previous_notebook_session_id = lifecycle.session_id
                        kernel_closed = _close_analysis_kernel(
                            runtime_app, lifecycle.session_id
                        )
                        _ANALYSIS_SESSIONS_BY_RUN.get(
                            run_id, set()
                        ).discard(previous_notebook_session_id)
                        lifecycle.session_id = None
                        # Only the analysis notebook restarts; every other
                        # named kernel survives into the retry.
                        carryover_sessions = dict(lifecycle.sessions)
                        if not kernel_closed:
                            yield _ndjson(
                                {
                                    "type": "error",
                                    "content": "The failed notebook kernel could not be reset safely.",
                                    "is_error": True,
                                }
                            )
                            return
                        clear_chat_session(
                            f"standalone:{run_id}", persist=False
                        )
                        # Reseed IN PLACE. On an adopted turn the notebook
                        # lives in the previous scratch; the cached fresh
                        # source would embed the wrong token and env paths.
                        seed_notebook(
                            analysis_notebook_path.parent, "analysis"
                        )
                        recovery_failure = notebook_failure
                        yield _ndjson(
                            {
                                "type": "progress",
                                "content": "Restarting analysis in a clean notebook",
                                "is_error": False,
                            }
                        )
                        continue
                    yield _ndjson(
                        {
                            "type": "error",
                            "content": "Notebook validation failed after one clean retry; the answer was rejected.",
                            "is_error": True,
                        }
                    )
                    return

                archive_id = None
                kernel_stopped = False
                if lifecycle.sessions:
                    # Archive EVERY started notebook, analysis first. Only
                    # the analysis archive failure fails the run.
                    archive_id, archive_error = await archive_run_notebooks(
                        runtime_app,
                        sessions=lifecycle.sessions,
                        run_id=run_id,
                        attempt=attempt,
                        gateway_api_url=gateway_api_url,
                        scoped_token=scoped_token,
                        archive_fn=_archive_analysis_notebook,
                    )
                    if archive_error is not None:
                        yield _ndjson(archive_error)
                        return
                    # Keep the kernels and notebooks ALIVE after a successful
                    # run: the chat page's live notebook panel stays attached
                    # (or attaches late) and renders the real outputs. The
                    # next run in this conversation — or the sandbox's own
                    # lifecycle — closes them.
                    register_keepalive_analysis_session(
                        conversation_id=conversation_id,
                        sessions=dict(lifecycle.sessions),
                        # The notebooks may live in an ADOPTED scratch from
                        # an earlier turn — register the directory that
                        # actually contains them.
                        scratch=analysis_notebook_path.parent,
                    )
                    if analysis_notebook_path.parent != scratch:
                        # Adopted turn: this run's unused seeded scratch
                        # still holds a token copy — remove it.
                        try:
                            (scratch / ".gateway-token").unlink(
                                missing_ok=True
                            )
                        except OSError:
                            pass
                    keep_workspace = True
                    kernel_stopped = False
                    _ANALYSIS_SESSIONS_BY_RUN.pop(run_id, None)
                    lifecycle.sessions.clear()
                accepted_text = (state.final_text or state.streamed_text).strip()
                resolve_report_outcome(collector, run_id=run_id)
                final_payload = build_final_payload(
                    collector,
                    accepted_text=accepted_text,
                    agent_cost_usd=state.agent_cost_usd,
                    agent_usage=state.agent_usage,
                    archive_id=archive_id,
                    kernel_stopped=kernel_stopped,
                )
                yield (json.dumps(final_payload, default=str) + "\n").encode(
                    "utf-8"
                )
                return
        finally:
            await save_agent_session()
            if current_lifecycle:
                # Close every kernel the run still owns.
                for open_session in list(
                    current_lifecycle.sessions.values()
                ):
                    try:
                        _close_analysis_kernel(runtime_app, open_session)
                    except Exception:
                        pass
            _ANALYSIS_SESSIONS_BY_RUN.pop(run_id, None)
            clear_chat_session(f"standalone:{run_id}", persist=False)
            if not keep_workspace:
                shutil.rmtree(scratch, ignore_errors=True)
            if remove_project_directory:
                shutil.rmtree(project_directory, ignore_errors=True)

    return stream_response(stream())
