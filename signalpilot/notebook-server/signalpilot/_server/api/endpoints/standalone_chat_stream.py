"""Agent event forwarding for the standalone chat execution stream."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Callable


def _ndjson(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload) + "\n").encode("utf-8")


@dataclass
class AgentRunState:
    """Mutable per-attempt bookkeeping shared with the execution route."""

    final_text: str = ""
    streamed_text: str = ""
    text_blocks: list[str] = field(default_factory=list)
    tool_names_by_id: dict[str, str] = field(default_factory=dict)
    tool_sessions_by_id: dict[str, str] = field(default_factory=dict)
    # Per kernel session id. The empty key holds results the tool input did
    # not attribute; it counts toward the analysis notebook's gate.
    edited_sessions: set[str] = field(default_factory=set)
    ran_sessions: set[str] = field(default_factory=set)
    agent_cost_usd: float | None = None
    agent_usage: dict[str, Any] | None = None
    agent_failed: bool = False

    def notebook_cells_edited(self, analysis_session_id: str | None) -> bool:
        return (
            bool(
                analysis_session_id
                and analysis_session_id in self.edited_sessions
            )
            or "" in self.edited_sessions
        )

    def successful_run_cells(self, analysis_session_id: str | None) -> bool:
        return (
            bool(
                analysis_session_id
                and analysis_session_id in self.ran_sessions
            )
            or "" in self.ran_sessions
        )


def _agent_error_payload(
    event: Any,
    *,
    agent_model: str,
    auth_config_override: dict[str, str] | None,
    resume_agent_session: bool,
    max_turns: int,
) -> dict[str, Any]:
    """Diagnostic error event for a failed agent run."""
    sdk_diagnostics = dict(event.diagnostic_context or {})
    return {
        "type": "error",
        # The gateway is the public trust boundary: it sanitizes this
        # diagnostic before persisting or displaying it. Do not discard the
        # SDK's root cause here or every failure becomes impossible for the
        # user to diagnose.
        "content": event.content,
        "full_trace": event.full_trace or event.content,
        "diagnostic_context": {
            **sdk_diagnostics,
            "model": agent_model,
            "auth_mode": (
                auth_config_override.get("type")
                if auth_config_override
                else "runtime_default"
            ),
            "credential_present": bool(
                auth_config_override and auth_config_override.get("token")
            ),
            "resume_requested": resume_agent_session,
            "max_turns": max_turns,
            # Report presence only. Values are never included in an
            # author-visible event.
            "environment": {
                "CLAUDE_CONFIG_DIR": "configured",
                "CLAUDE_CODE_OAUTH_TOKEN": (
                    "configured"
                    if auth_config_override
                    and auth_config_override.get("type") == "oauth"
                    else "cleared"
                ),
                "ANTHROPIC_API_KEY": (
                    "configured"
                    if auth_config_override
                    and auth_config_override.get("type") == "api_key"
                    else "cleared"
                ),
                "SP_GATEWAY_URL": (
                    "configured"
                    if (
                        os.getenv("SP_GATEWAY_INTERNAL_URL")
                        or os.getenv("SP_GATEWAY_URL")
                    )
                    else "defaulted"
                ),
            },
        },
        "is_error": True,
    }


async def announce_adopted_sessions(
    runtime_app: Any,
    *,
    adopted_sessions: dict[str, str],
    scratch: Any,
    scoped_token: str,
    session_resolver: Callable[[Any, str], Any],
    lifecycle_event: Callable[..., Any],
) -> AsyncGenerator[bytes, None]:
    """Re-announce every adopted kernel, analysis first."""
    from signalpilot._server.api.endpoints.standalone_chat_finalize import (
        ordered_notebook_names,
    )

    for notebook_name in ordered_notebook_names(adopted_sessions):
        adopted_kernel = adopted_sessions[notebook_name]
        adopted_session = session_resolver(runtime_app, adopted_kernel)
        adopted_session._signalpilot_chat_runtime = True
        adopted_session._signalpilot_chat_redactions = (scoped_token,)
        await lifecycle_event(
            "notebook_started",
            {"notebook": notebook_name, "session_id": adopted_kernel},
        )
        yield _ndjson(
            {
                "type": "notebook_started",
                "session_id": adopted_kernel,
                "notebook_path": str(scratch / f"{notebook_name}.py"),
                "notebook": notebook_name,
            }
        )


async def start_recovery_analysis(
    runtime_app: Any,
    *,
    lifecycle: Any,
    notebook_path: Any,
    run_id: str,
    attempt: int,
    scoped_token: str,
    start_fn: Callable[[Any, Any], str],
    session_resolver: Callable[[Any, str], Any],
    lifecycle_event: Callable[..., Any],
) -> AsyncGenerator[bytes, None]:
    """Start the clean analysis kernel for the recovery attempt."""
    import traceback

    from signalpilot import _loggers

    try:
        lifecycle.session_id = start_fn(runtime_app, notebook_path)
    except Exception as exc:
        _loggers.sp_logger().exception(
            "Clean notebook kernel start failed run_id=%s attempt=%s",
            run_id,
            attempt,
        )
        yield _ndjson(
            {
                "type": "error",
                "content": str(exc) if str(exc) else repr(exc),
                "full_trace": traceback.format_exc(),
                "diagnostic_context": {
                    "error_type": type(exc).__name__,
                    "operation": "start_recovery_notebook_kernel",
                },
                "is_error": True,
            }
        )
        return
    clean_session = session_resolver(runtime_app, lifecycle.session_id)
    clean_session._signalpilot_chat_runtime = True
    clean_session._signalpilot_chat_redactions = (scoped_token,)
    await lifecycle_event("notebook_started", {})
    # Tell the gateway (and through it the browser's live notebook panel)
    # that a replacement kernel session now owns the analysis notebook. The
    # normal path announces this via the start_analysis_notebook tool
    # result; the recovery path has no tool call, so it must be explicit.
    yield _ndjson(
        {
            "type": "notebook_started",
            "session_id": lifecycle.session_id,
            "notebook_path": str(notebook_path),
            "notebook": "analysis",
        }
    )


async def forward_agent_events(
    events: AsyncIterator[Any],
    *,
    state: AgentRunState,
    agent_model: str,
    auth_config_override: dict[str, str] | None,
    resume_agent_session: bool,
    max_turns: int,
    analysis_session: Callable[[], str | None],
) -> AsyncGenerator[bytes, None]:
    """Forward SDK events as NDJSON and record run state on the way."""
    async for event in events:
        if event.type in {
            "thinking",
            "block_start",
        }:
            # `thinking` is the authoritative block that repeats the already
            # streamed thinking_delta content. Forwarding both would
            # duplicate it in the transcript.
            continue
        subagent_parent = getattr(event, "parent_tool_call_id", "")
        if event.type == "thinking_delta":
            yield _ndjson(
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
            continue
        if event.type == "text_delta":
            # Subagent narration must NOT enter the run's own narration or
            # answer fallback. It is grouped under its Agent spawn in the UX
            # instead.
            if not subagent_parent:
                state.streamed_text += event.content
            # Forward narration live so the gateway records it in sequence
            # with tool events. The accepted ANSWER still ships only via the
            # validated final event; a rejected run never emits final.
            yield _ndjson(
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
            continue
        if event.type == "text":
            # A run interleaves narration and the closing summary as
            # separate text blocks. Accumulate every block; keeping only the
            # last one silently dropped answers. Subagent text never joins
            # the answer: its report reaches the transcript through the
            # Agent tool result.
            if event.content.strip() and not subagent_parent:
                state.text_blocks.append(event.content)
                state.final_text = "\n\n".join(state.text_blocks)
            continue
        if event.type == "error":
            state.agent_failed = True
            yield _ndjson(
                _agent_error_payload(
                    event,
                    agent_model=agent_model,
                    auth_config_override=auth_config_override,
                    resume_agent_session=resume_agent_session,
                    max_turns=max_turns,
                )
            )
            break
        if event.type == "done":
            # Per-turn accounting from the SDK's ResultMessage; forwarded on
            # the final event so the gateway can persist cost and token
            # usage per run.
            if event.cost_usd is not None:
                state.agent_cost_usd = event.cost_usd
            if getattr(event, "usage", None):
                state.agent_usage = event.usage
        if event.type == "tool_use" and event.tool_call_id:
            state.tool_names_by_id[event.tool_call_id] = event.tool_name
            tool_input = (
                event.tool_input if isinstance(event.tool_input, dict) else {}
            )
            input_session = str(tool_input.get("session_id") or "")
            if input_session:
                state.tool_sessions_by_id[event.tool_call_id] = input_session
        if event.type == "tool_result":
            completed_tool = state.tool_names_by_id.get(
                event.tool_call_id, ""
            )
            # Attribute evidence to the tool call's kernel session. Fall
            # back to the analysis session so the single-notebook flow keeps
            # its exact gate behavior.
            target_session = (
                state.tool_sessions_by_id.get(event.tool_call_id)
                or analysis_session()
                or ""
            )
            if (
                completed_tool.endswith("edit_notebook")
                and not event.is_error
            ):
                state.edited_sessions.add(target_session)
            if (
                completed_tool.endswith("run_cells")
                and not event.is_error
            ):
                state.ran_sessions.add(target_session)
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
        yield (json.dumps(payload, default=str) + "\n").encode("utf-8")
