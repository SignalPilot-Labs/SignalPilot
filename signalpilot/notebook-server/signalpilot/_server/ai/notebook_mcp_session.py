"""Session handlers for the notebook MCP server.

``_handle_start_notebook_session`` opens a headless kernel session for a
notebook file. ``_invoke_backend_tool`` runs one of the dataclass-typed
backend tools and, for ``get_active_notebooks``, keeps only the sessions
the run's session authorizer accepts.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any

from signalpilot import _loggers
from signalpilot._server.ai.chat_runtime_output import (
    compact_chat_runtime_output,
    redact_chat_runtime_text,
)
from signalpilot._server.ai.notebook_mcp_edit import (
    _local_server_url,
    _server_headers,
)
from signalpilot._server.ai.notebook_mcp_graph import (
    NotebookToolError,
    _graph_error_payload,
)
from signalpilot._server.ai.tools.exceptions import ToolExecutionError

if TYPE_CHECKING:
    from collections.abc import Callable

    from signalpilot._server.ai.tools.base import ToolBase, ToolContext

LOGGER = _loggers.sp_logger()

ACTIVE_NOTEBOOKS_TOOL = "get_active_notebooks"


def _handle_start_notebook_session(
    context: ToolContext, arguments: dict[str, Any]
) -> list[Any]:
    """Start a kernel session for a notebook file."""
    from mcp.types import TextContent

    file_path = arguments.get("file_path", "")
    auto_run = arguments.get("auto_run", False)

    if not file_path:
        raise NotebookToolError(
            _graph_error_payload(
                error_type="InvalidRequest",
                cell_ids=[],
                message="file_path is required",
            )
        )

    import os

    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)

    if not os.path.exists(file_path):
        raise NotebookToolError(
            _graph_error_payload(
                error_type="NotebookFileNotFound",
                cell_ids=[],
                message="The requested notebook file does not exist",
            )
        )

    try:
        sm = context.session_manager

        # Check if a session already exists for this file
        for sid, sess in sm.sessions.items():
            sess_path = sess.app_file_manager.path
            if sess_path and os.path.normpath(
                str(sess_path)
            ) == os.path.normpath(file_path):
                LOGGER.info(
                    f"[start_session] Existing session {sid} for {file_path}"
                )
                cell_data = list(
                    sess.app_file_manager.app.cell_manager.cell_data()
                )
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "session_id": str(sid),
                                "status": "already_running",
                                "file": file_path,
                                "cells": len(cell_data),
                            }
                        ),
                    )
                ]

        # Create a headless consumer for the session
        from signalpilot._session.consumer import SessionConsumer
        from signalpilot._session.model import ConnectionState
        from signalpilot._types.ids import ConsumerId, SessionId

        new_session_id = SessionId(f"s_{uuid.uuid4().hex[:6]}")
        consumer_id = ConsumerId(str(new_session_id))

        class HeadlessConsumer(SessionConsumer):
            """Minimal consumer for agent-managed sessions."""

            def __init__(self, cid: ConsumerId) -> None:
                self._consumer_id = cid
                self._state = ConnectionState.OPEN

            @property
            def consumer_id(self) -> ConsumerId:
                return self._consumer_id

            def notify(self, notification: Any) -> None:
                pass  # Discard: the agent reads state via MCP tools

            def connection_state(self) -> ConnectionState:
                return self._state

            def on_attach(self, session: Any, event_bus: Any) -> None:
                pass

            def on_detach(self) -> None:
                self._state = ConnectionState.CLOSED

        consumer = HeadlessConsumer(consumer_id)

        session = sm.create_session(
            session_id=new_session_id,
            session_consumer=consumer,
            query_params={},
            file_key=file_path,
            auto_instantiate=True,
        )

        LOGGER.info(
            f"[start_session] Created session {new_session_id} for {file_path}"
        )

        # Wait for kernel to be ready, then instantiate via HTTP
        import time

        import requests as _requests

        hdrs = _server_headers(context, str(new_session_id))

        # Wait for kernel process to be alive
        for attempt in range(10):
            km = getattr(session, "_kernel_manager", None)
            if km and km.is_alive():
                LOGGER.info(
                    f"[start_session] Kernel alive after {attempt * 0.5}s"
                )
                break
            time.sleep(0.5)
        else:
            LOGGER.warning("[start_session] Kernel not alive after 5s")

        # Instantiate with retry
        instantiate_ok = False
        for attempt in range(5):
            try:
                resp = _requests.post(
                    _local_server_url(context, "/api/kernel/instantiate"),
                    headers=hdrs,
                    json={"objectIds": [], "values": [], "autoRun": auto_run},
                    timeout=15,
                )
                LOGGER.info(
                    f"[start_session] Instantiate attempt {attempt + 1}: HTTP {resp.status_code} {resp.text[:100]}"
                )
                if resp.status_code == 200:
                    instantiate_ok = True
                    break
            except Exception as e:
                LOGGER.warning(
                    f"[start_session] Instantiate attempt {attempt + 1} failed: {e}"
                )
            time.sleep(1.0)

        if not instantiate_ok:
            LOGGER.error("[start_session] All instantiate attempts failed")
            sm.close_session(new_session_id)
            raise RuntimeError("Kernel instantiate failed")

        cell_data = list(session.app_file_manager.app.cell_manager.cell_data())
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "session_id": str(new_session_id),
                        "status": "started",
                        "file": file_path,
                        "cells": len(cell_data),
                        "cell_ids": [str(cd.cell_id) for cd in cell_data],
                        "auto_run": auto_run,
                    }
                ),
            )
        ]

    except Exception as e:
        LOGGER.error(f"[start_session] Failed: {e}")
        raise NotebookToolError(
            _graph_error_payload(
                error_type="NotebookStartError",
                cell_ids=[],
                message=type(e).__name__,
            )
        ) from e


def _filter_active_notebooks(
    result: Any, session_authorizer: Callable[[str], bool] | None
) -> Any:
    """Keep only the run's own sessions in a get_active_notebooks result.

    An empty list is a valid answer. The summary count follows the filter.
    """
    if session_authorizer is None:
        return result
    data = getattr(result, "data", None)
    notebooks = getattr(data, "notebooks", None)
    if not isinstance(notebooks, list):
        return result
    kept = [
        info
        for info in notebooks
        if session_authorizer(str(getattr(info, "session_id", "") or ""))
    ]
    data.notebooks = kept
    summary = getattr(data, "summary", None)
    if summary is not None and hasattr(summary, "total_notebooks"):
        summary.total_notebooks = len(kept)
    return result


async def _invoke_backend_tool(
    tool_instances: dict[str, ToolBase[Any, Any]],
    name: str,
    arguments: dict[str, Any],
    *,
    session_authorizer: Callable[[str], bool] | None = None,
) -> list[Any]:
    from mcp.types import TextContent

    t = tool_instances[name]
    runtime_redactions: tuple[str, ...] = ()
    chat_runtime = False
    session_id = str(arguments.get("session_id") or "")
    if session_id:
        try:
            session = t.context.get_session(session_id)
            chat_runtime = bool(
                getattr(session, "_signalpilot_chat_runtime", False)
            )
            runtime_redactions = tuple(
                getattr(session, "_signalpilot_chat_redactions", ()) or ()
            )
        except Exception:
            pass

    try:
        result = await t(arguments)
        if name == ACTIVE_NOTEBOOKS_TOOL:
            result = _filter_active_notebooks(result, session_authorizer)
            chat_runtime = chat_runtime or session_authorizer is not None
        if is_dataclass(result):
            text = json.dumps(asdict(result), default=str)
        elif isinstance(result, dict):
            text = json.dumps(result, default=str)
        else:
            text = str(result)
        if chat_runtime:
            text = compact_chat_runtime_output(
                text,
                mimetype="application/json",
                redactions=runtime_redactions,
            )
        return [TextContent(type="text", text=text)]
    except ToolExecutionError as e:
        error_text = (
            f"Error: {e.message}\nSuggested fix: {e.suggested_fix or 'N/A'}"
        )
        return [
            TextContent(
                type="text",
                text=redact_chat_runtime_text(error_text, runtime_redactions),
            )
        ]
    except Exception as e:
        LOGGER.error(f"Tool {name} failed: {e}")
        return [
            TextContent(
                type="text",
                text=redact_chat_runtime_text(
                    f"Error: {e}", runtime_redactions
                ),
            )
        ]
