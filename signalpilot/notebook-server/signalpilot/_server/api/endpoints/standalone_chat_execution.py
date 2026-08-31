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
from signalpilot._server.api.endpoints.standalone_chat_gateway import (
    StandaloneGatewayClient,
)
from signalpilot._server.api.endpoints.standalone_chat_prompt import (
    STANDALONE_DISALLOWED_MCP_TOOLS,
    _allowed_tools_for_features,
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
    _start_analysis_kernel,
    _with_recorded_notebook_errors,
    adopt_keepalive_analysis_session,
    register_keepalive_analysis_session,
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

    from starlette.requests import Request
    from starlette.responses import StreamingResponse

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
    (
        prompt,
        history,
        notebook_analysis_enabled,
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
        notebook_analysis_enabled=notebook_analysis_enabled,
    )
    load_result = gateway.load_result
    load_report_catalog = gateway.load_report_catalog
    load_report_context = gateway.load_report_context
    check_published_artifact = gateway.check_published_artifact

    auth_config_override = _runtime_auth_override(body)
    session_id = SessionId(f"standalone-{run_id}")
    # Multi-turn continuity: adopt the conversation's kept-alive kernel and
    # notebook from the previous turn when it is still running — the agent
    # reuses the SAME session id across turns and the live notebook panel
    # stays attached. Falls back to a fresh notebook when the kernel is gone.
    # scope.get: unit tests build bare Requests without an app.
    adopted = adopt_keepalive_analysis_session(
        request.scope.get("app"),
        conversation_id,
        scoped_token=scoped_token,
    )
    adopted_session_id = adopted[0] if adopted else None
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
    if adopted is not None:
        # Continue in the previous turn's notebook document.
        analysis_notebook_path = adopted[1]
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
        # Set on the success path: the kernel + notebook survive the run for
        # the live notebook panel, so the scratch dir must survive too.
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
            for attempt in (1, 2):
                collector = StandaloneArtifactCollector()
                lifecycle = StandaloneNotebookLifecycle()
                current_lifecycle = lifecycle

                async def lifecycle_event(
                    event_type: str,
                    payload: dict[str, Any],
                    lifecycle: StandaloneNotebookLifecycle = lifecycle,
                    attempt: int = attempt,
                ) -> None:
                    del payload
                    if (
                        event_type != "notebook_started"
                        or not lifecycle.session_id
                    ):
                        return
                    _ANALYSIS_SESSIONS_BY_RUN[run_id] = lifecycle.session_id
                    runtime_session = _analysis_session(
                        request.app, lifecycle.session_id
                    )
                    runtime_session._signalpilot_chat_run_id = run_id
                    runtime_session._signalpilot_chat_session_id = (
                        lifecycle.session_id
                    )
                    runtime_session._signalpilot_chat_attempt = attempt

                if (
                    recovery_failure is None
                    and attempt == 1
                    and adopted_session_id
                ):
                    # Adopted kernel from the previous turn: pre-seed the
                    # lifecycle so the notebook tools authorize the session
                    # immediately, and re-announce it so the live notebook
                    # panel (re)attaches for this run.
                    lifecycle.session_id = adopted_session_id
                    adopted_session = _analysis_session(
                        request.app, adopted_session_id
                    )
                    adopted_session._signalpilot_chat_runtime = True
                    adopted_session._signalpilot_chat_redactions = (
                        scoped_token,
                    )
                    await lifecycle_event("notebook_started", {})
                    yield (
                        json.dumps(
                            {
                                "type": "notebook_started",
                                "session_id": lifecycle.session_id,
                                "notebook_path": str(analysis_notebook_path),
                            }
                        )
                        + "\n"
                    ).encode("utf-8")

                if recovery_failure is not None:
                    try:
                        lifecycle.session_id = _start_analysis_kernel(
                            request.app, analysis_notebook_path
                        )
                    except Exception:
                        LOGGER.exception(
                            "Clean notebook kernel start failed run_id=%s attempt=%s",
                            run_id,
                            attempt,
                        )
                        yield (
                            json.dumps(
                                {
                                    "type": "error",
                                    "content": "The failed notebook kernel could not be restarted safely.",
                                    "is_error": True,
                                }
                            )
                            + "\n"
                        ).encode("utf-8")
                        return
                    clean_session = _analysis_session(
                        request.app, lifecycle.session_id
                    )
                    clean_session._signalpilot_chat_runtime = True
                    clean_session._signalpilot_chat_redactions = (
                        scoped_token,
                    )
                    await lifecycle_event(
                        "notebook_started", {}
                    )
                    # Tell the gateway (and through it the browser's live
                    # notebook panel) that a replacement kernel session now
                    # owns the analysis notebook. The normal path announces
                    # this via the start_analysis_notebook tool result; the
                    # recovery path has no tool call, so it must be explicit.
                    yield (
                        json.dumps(
                            {
                                "type": "notebook_started",
                                "session_id": lifecycle.session_id,
                                "notebook_path": str(analysis_notebook_path),
                            }
                        )
                        + "\n"
                    ).encode("utf-8")

                artifact_server = build_standalone_chat_mcp_server(
                    collector,
                    result_loader=load_result,
                    project_directory=project_directory,
                    scratch_directory=scratch,
                    notebook_mcp_app=(
                        request.app if notebook_analysis_enabled else None
                    ),
                    analysis_notebook_path=analysis_notebook_path,
                    event_sink=lifecycle_event,
                    notebook_lifecycle=lifecycle,
                    runtime_redactions=(scoped_token,),
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
                    attempt_prompt = (
                        f"{prompt}\n\n<notebook_recovery>\n"
                        f"{_recovery_context(recovery_failure)}\n"
                        "The clean notebook kernel is already running. Use "
                        f"session_id `{lifecycle.session_id}`; do not create a "
                        "different session. Plan each database query before "
                        "executing it.\n"
                        "</notebook_recovery>"
                    )
                elif attempt == 1 and adopted_session_id:
                    attempt_prompt = (
                        f"{prompt}\n\n<notebook_continuity>\n"
                        "The analysis notebook from the previous turn is "
                        "still running with its cells and variables. Use "
                        f"session_id `{adopted_session_id}` with the notebook "
                        "tools to add or edit cells. Do not start a new "
                        "notebook. If a gateway call from a notebook cell "
                        "fails with an authorization error, run the setup "
                        "cell again; it reads a refreshed token.\n"
                        "</notebook_continuity>"
                    )

                final_text = ""
                streamed_text = ""
                text_blocks: list[str] = []
                tool_names_by_id: dict[str, str] = {}
                agent_cost_usd: float | None = None
                agent_usage: dict[str, Any] | None = None
                successful_run_cells = False
                agent_failed = False
                async for event in run_notebook_agent(
                    attempt_prompt,
                    session_id,
                    model=str(
                        body.get("model")
                        or os.getenv("SIGNALPILOT_ANALYSIS_AGENT_MODEL")
                        or "claude-sonnet-4-5-20250929"
                    ),
                    max_turns=MAX_ANALYSIS_AGENT_TURNS,
                    new_chat=False,
                    message_history=history,
                    system_prompt_override=system_prompt,
                    mcp_config=mcp_config,
                    thread_id=f"standalone:{run_id}",
                    notebook_mcp_app=(
                        request.app if notebook_analysis_enabled else None
                    ),
                    cwd=str(project_directory),
                    # Expose the normal SignalPilot workflow. Xata branch
                    # control stays denied because this run is already pinned
                    # to a frozen project branch and database connection.
                    disallow_file_edits=False,
                    additional_disallowed_tools=(
                        STANDALONE_DISALLOWED_MCP_TOOLS
                    ),
                    allowed_tools=_allowed_tools_for_features(
                        notebook_analysis_enabled=notebook_analysis_enabled
                    ),
                    additional_mcp_servers={
                        "standalone-chat": artifact_server
                    },
                    persist_session_mapping=False,
                    auth_config_override=auth_config_override,
                    chat_session_id_override=agent_session.session_id,
                    resume_session_override=resume_agent_session,
                    agent_env_overrides={
                        "CLAUDE_CONFIG_DIR": str(agent_session.config_dir),
                    },
                    notebook_session_authorizer=(
                        lambda candidate, lifecycle=lifecycle: (
                            lifecycle.session_id == candidate
                        )
                    ),
                ):
                    if event.type in {
                        "thinking",
                        "block_start",
                    }:
                        # `thinking` is the authoritative block that repeats the
                        # already-streamed thinking_delta content — forwarding
                        # both would duplicate it in the transcript.
                        continue
                    subagent_parent = getattr(
                        event, "parent_tool_call_id", ""
                    )
                    if event.type == "thinking_delta":
                        yield (
                            json.dumps(
                                {
                                    "type": "thinking_delta",
                                    "content": event.content,
                                    **(
                                        {"parent_tool_call_id": subagent_parent}
                                        if subagent_parent
                                        else {}
                                    ),
                                }
                            )
                            + "\n"
                        ).encode("utf-8")
                        continue
                    if event.type == "text_delta":
                        # Subagent narration must NOT enter the run's own
                        # narration or answer fallback — it is grouped under
                        # its Agent spawn in the UX instead.
                        if not subagent_parent:
                            streamed_text += event.content
                        # Forward narration live so the gateway records it in
                        # sequence with tool events — the chat UI interleaves
                        # text with the tool chains it narrates. The accepted
                        # ANSWER still ships only via the validated final
                        # event; a rejected run never emits final.
                        yield (
                            json.dumps(
                                {
                                    "type": "text_delta",
                                    "content": event.content,
                                    **(
                                        {"parent_tool_call_id": subagent_parent}
                                        if subagent_parent
                                        else {}
                                    ),
                                }
                            )
                            + "\n"
                        ).encode("utf-8")
                        continue
                    if event.type == "text":
                        # A run interleaves narration and the closing summary
                        # as separate text blocks. Overwriting would keep only
                        # the LAST block, which silently dropped the rest of
                        # the answer whenever the closing block did not arrive
                        # complete. Accumulate every block instead. Subagent
                        # text never joins the answer: its report reaches the
                        # transcript through the Agent tool result.
                        if event.content.strip() and not subagent_parent:
                            text_blocks.append(event.content)
                            final_text = "\n\n".join(text_blocks)
                        continue
                    if event.type == "error":
                        agent_failed = True
                        yield (
                            json.dumps(
                                {
                                    "type": "error",
                                    "content": "The analysis agent failed before validation.",
                                    "is_error": True,
                                }
                            )
                            + "\n"
                        ).encode("utf-8")
                        break
                    if event.type == "done":
                        # Per-turn accounting from the SDK's ResultMessage;
                        # forwarded on the final event so the gateway can
                        # persist cost and token usage per run.
                        if event.cost_usd is not None:
                            agent_cost_usd = event.cost_usd
                        if getattr(event, "usage", None):
                            agent_usage = event.usage
                    if event.type == "tool_use" and event.tool_call_id:
                        tool_names_by_id[event.tool_call_id] = event.tool_name
                    if event.type == "tool_result":
                        completed_tool = tool_names_by_id.get(
                            event.tool_call_id, ""
                        )
                        if (
                            completed_tool.endswith("run_cells")
                            and not event.is_error
                        ):
                            successful_run_cells = True
                    payload = {
                        "type": event.type,
                        "content": event.content,
                        "tool_name": event.tool_name,
                        "tool_input": event.tool_input,
                        "tool_call_id": event.tool_call_id,
                        "is_error": event.is_error,
                    }
                    if subagent_parent:
                        payload["parent_tool_call_id"] = subagent_parent
                    yield (json.dumps(payload, default=str) + "\n").encode(
                        "utf-8"
                    )
                await save_agent_session()
                resume_agent_session = True
                if agent_failed:
                    return

                if project_directory is not None and not await asyncio.to_thread(
                    _project_is_unchanged, project_directory, project_baseline_digest
                ):
                    yield (
                        json.dumps(
                            {
                                "type": "error",
                                "content": "The frozen project workspace changed; the run was rejected.",
                                "is_error": True,
                            }
                        )
                        + "\n"
                    ).encode("utf-8")
                    return

                notebook_failure: dict[str, Any] | None = None
                if lifecycle.session_id:
                    notebook_failure = _notebook_failure(
                        request.app, lifecycle.session_id
                    )
                    if (
                        recovery_failure is not None
                        and lifecycle.session_id
                        == previous_notebook_session_id
                    ):
                        notebook_failure = {
                            "error": {
                                "type": "NotebookSessionReuseError",
                                "variable": None,
                                "cell_ids": [],
                            }
                        }
                    elif not successful_run_cells:
                        notebook_failure = {
                            "error": {
                                "type": "NotebookEvidenceNotValidatedError",
                                "variable": None,
                                "cell_ids": [],
                            }
                        }
                    if notebook_failure is not None:
                        notebook_failure = _with_recorded_notebook_errors(
                            _analysis_session(
                                request.app, lifecycle.session_id
                            ),
                            notebook_failure,
                        )
                elif recovery_failure is not None:
                    notebook_failure = {
                        "error": {
                            "type": "NotebookNotRestartedError",
                            "variable": None,
                            "cell_ids": [],
                        }
                    }

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
                            request.app, lifecycle.session_id
                        )
                        _ANALYSIS_SESSIONS_BY_RUN.pop(run_id, None)
                        lifecycle.session_id = None
                        if not kernel_closed:
                            yield (
                                json.dumps(
                                    {
                                        "type": "error",
                                        "content": "The failed notebook kernel could not be reset safely.",
                                        "is_error": True,
                                    }
                                )
                                + "\n"
                            ).encode("utf-8")
                            return
                        clear_chat_session(
                            f"standalone:{run_id}", persist=False
                        )
                        analysis_notebook_path.write_text(
                            seeded_notebook_source, encoding="utf-8"
                        )
                        recovery_failure = notebook_failure
                        yield (
                            json.dumps(
                                {
                                    "type": "progress",
                                    "content": "Restarting analysis in a clean notebook",
                                    "is_error": False,
                                }
                            )
                            + "\n"
                        ).encode("utf-8")
                        continue
                    yield (
                        json.dumps(
                            {
                                "type": "error",
                                "content": "Notebook validation failed after one clean retry; the answer was rejected.",
                                "is_error": True,
                            }
                        )
                        + "\n"
                    ).encode("utf-8")
                    return

                archive_id = None
                kernel_stopped = False
                if lifecycle.session_id:
                    try:
                        archive_id = await _archive_analysis_notebook(
                            app=request.app,
                            session_id=lifecycle.session_id,
                            run_id=run_id,
                            gateway_api_url=gateway_api_url,
                            scoped_token=scoped_token,
                        )
                    except Exception as exc:
                        LOGGER.error(
                            "Standalone notebook archive failed run_id=%s "
                            "session_id=%s attempt=%s error_type=%s",
                            run_id,
                            lifecycle.session_id,
                            attempt,
                            type(exc).__name__,
                        )
                        yield (
                            json.dumps(
                                {
                                    "type": "error",
                                    "content": "The validated notebook could not be archived; the answer was rejected.",
                                    "is_error": True,
                                }
                            )
                            + "\n"
                        ).encode("utf-8")
                        return
                    # Keep the kernel and notebook ALIVE after a successful
                    # run: the chat page's live notebook panel stays attached
                    # (or attaches late) and renders the real outputs. The
                    # next run in this conversation — or the sandbox's own
                    # lifecycle — closes it.
                    register_keepalive_analysis_session(
                        conversation_id=conversation_id,
                        session_id=lifecycle.session_id,
                        # The notebook may live in an ADOPTED scratch from an
                        # earlier turn — register the directory that actually
                        # contains it.
                        scratch=analysis_notebook_path.parent,
                    )
                    if analysis_notebook_path.parent != scratch:
                        # Adopted turn: this run's unused seeded scratch still
                        # holds a token copy — remove it.
                        try:
                            (scratch / ".gateway-token").unlink(missing_ok=True)
                        except OSError:
                            pass
                    keep_workspace = True
                    kernel_stopped = False
                    _ANALYSIS_SESSIONS_BY_RUN.pop(run_id, None)
                    lifecycle.session_id = None
                accepted_text = (final_text or streamed_text).strip()
                complete_artifacts = [
                    artifact
                    for artifact in collector.artifacts
                    if _collected_artifact_is_complete(artifact)
                ]
                if (
                    complete_artifacts
                    and collector.report_action_outcome is None
                ):
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
                        "catalog_scan_complete": (
                            collector.report_catalog_scan_complete
                        ),
                    }
                final_payload = {
                    "type": "final",
                    "content": accepted_text,
                    "artifacts": collector.artifacts,
                }
                if agent_cost_usd is not None:
                    final_payload["cost_usd"] = agent_cost_usd
                if agent_usage is not None:
                    final_payload["usage"] = agent_usage
                if collector.report_proposal is not None:
                    final_payload["report_proposal"] = (
                        collector.report_proposal
                    )
                if collector.report_action_outcome is not None:
                    final_payload["report_action_outcome"] = (
                        collector.report_action_outcome
                    )
                if archive_id is not None:
                    final_payload["archive_id"] = archive_id
                    final_payload["kernel_stopped"] = kernel_stopped
                yield (json.dumps(final_payload, default=str) + "\n").encode(
                    "utf-8"
                )
                return
        finally:
            await save_agent_session()
            if current_lifecycle and current_lifecycle.session_id:
                try:
                    _close_analysis_kernel(
                        request.app, current_lifecycle.session_id
                    )
                except Exception:
                    pass
            _ANALYSIS_SESSIONS_BY_RUN.pop(run_id, None)
            clear_chat_session(f"standalone:{run_id}", persist=False)
            if not keep_workspace:
                shutil.rmtree(scratch, ignore_errors=True)
            if remove_project_directory:
                shutil.rmtree(project_directory, ignore_errors=True)

    return stream_response(stream())
