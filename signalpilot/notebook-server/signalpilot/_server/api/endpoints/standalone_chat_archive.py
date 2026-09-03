"""Archive export for one validated chat notebook kernel."""

from __future__ import annotations

import base64
import hashlib
import html as html_lib
import json
from typing import Any

import httpx

from signalpilot import _loggers
from signalpilot._server.ai.chat_runtime_output import (
    compact_chat_runtime_output,
)
from signalpilot._utils.requests import RequestError

LOGGER = _loggers.sp_logger()


async def _archive_analysis_notebook(
    *,
    app: Any,
    session_id: str,
    run_id: str,
    gateway_api_url: str,
    scoped_token: str,
    notebook_name: str = "analysis",
) -> str:
    # Call-time import: tests monkeypatch the runtime module's resolver.
    from signalpilot._server.api.endpoints.standalone_chat_runtime import (
        _analysis_session,
        _is_error_output,
    )
    from signalpilot._server.export.exporter import Exporter
    from signalpilot._server.models.export import ExportAsHTMLRequest

    session = _analysis_session(app, session_id)
    source = session.app_file_manager.app.to_py().encode("utf-8")
    if scoped_token.encode("utf-8") in source:
        raise RuntimeError(
            "Refusing to archive notebook source containing a runtime token"
        )
    try:
        html, _ = Exporter().export_as_html(
            app=session.app_file_manager.app,
            filename=f"{notebook_name}.py",
            session_view=session.session_view,
            display_config=session.config_manager.get_config()["display"],
            request=ExportAsHTMLRequest(
                download=False,
                files=[],
                include_code=False,
            ),
        )
    except (FileNotFoundError, RequestError, httpx.HTTPError) as exc:
        # The slim runtime image intentionally omits the notebook frontend
        # bundle. Preserve the validated evidence in a bounded, code-free HTML
        # archive instead of rejecting an otherwise clean analysis.
        LOGGER.warning(
            "Notebook frontend assets unavailable; using safe archive fallback "
            "run_id=%s session_id=%s error_type=%s",
            run_id,
            session_id,
            type(exc).__name__,
        )
        html = _fallback_archive_html(
            session,
            run_id=run_id,
            notebook_name=notebook_name,
            redactions=(scoped_token,),
        )
    cells = []
    for cell in session.app_file_manager.app.cell_manager.cell_data():
        notification = session.session_view.cell_notifications.get(
            cell.cell_id
        )
        cells.append(
            {
                "cell_id": str(cell.cell_id),
                "code_hash": hashlib.sha256(
                    cell.code.encode("utf-8")
                ).hexdigest(),
                "status": str(
                    getattr(notification, "status", "unknown") or "unknown"
                ),
                "has_errors": bool(
                    notification is not None
                    and _is_error_output(getattr(notification, "output", None))
                ),
            }
        )
    manifest = json.dumps(
        {
            "version": 1,
            "run_id": run_id,
            "notebook": notebook_name,
            "cells": cells,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    # Structured outputs snapshot (NotebookSessionV1): lets the chat page
    # rehydrate the REAL notebook view kernel-free after the sandbox is gone,
    # instead of the static HTML fallback.
    session_payload: dict[str, str] = {}
    try:
        from signalpilot._server.export._session_cache import (
            serialize_session_snapshot,
        )

        snapshot = serialize_session_snapshot(
            session.session_view,
            notebook_path=session.app_file_manager.path,
            cell_ids=[
                cell.cell_id
                for cell in session.app_file_manager.app.cell_manager.cell_data()
            ],
        )
        snapshot_bytes = json.dumps(snapshot, separators=(",", ":")).encode(
            "utf-8"
        )
        if scoped_token.encode("utf-8") not in snapshot_bytes:
            session_payload["session_base64"] = base64.b64encode(
                snapshot_bytes
            ).decode("ascii")
    except Exception:
        LOGGER.warning(
            "Session snapshot serialization failed; archiving without "
            "outputs run_id=%s",
            run_id,
            exc_info=True,
        )
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{gateway_api_url}/api/chat/runtime-archives",
            headers={"Authorization": f"Bearer {scoped_token}"},
            json={
                "notebook_name": notebook_name,
                "source_base64": base64.b64encode(source).decode("ascii"),
                "html_base64": base64.b64encode(html.encode("utf-8")).decode(
                    "ascii"
                ),
                "manifest_base64": base64.b64encode(manifest).decode("ascii"),
                **session_payload,
            },
        )
    response.raise_for_status()
    return str(response.json()["archive_id"])


def _fallback_archive_html(
    session: Any,
    *,
    run_id: str,
    redactions: tuple[str, ...],
    notebook_name: str = "analysis",
) -> str:
    """Render validated cell outputs without notebook code or active markup."""
    sections: list[str] = []
    for index, cell in enumerate(
        session.app_file_manager.app.cell_manager.cell_data(), start=1
    ):
        notification = session.session_view.cell_notifications.get(
            cell.cell_id
        )
        status = str(getattr(notification, "status", "unknown") or "unknown")
        output = getattr(notification, "output", None)
        mimetype = str(getattr(output, "mimetype", "") or "")
        rendered_output = "No displayed output."
        if output is not None:
            rendered_output = compact_chat_runtime_output(
                getattr(output, "data", ""),
                mimetype=mimetype,
                redactions=redactions,
            )
        sections.append(
            "<section>"
            f"<h2>Cell {index}</h2>"
            f"<p>Status: {html_lib.escape(status)}</p>"
            f"<p>Output type: {html_lib.escape(mimetype or 'none')}</p>"
            f"<pre>{html_lib.escape(rendered_output)}</pre>"
            "</section>"
        )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Validated analysis notebook</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:960px;margin:40px auto;"
        "padding:0 20px;background:#141416;color:#ededed}section{border:1px solid #333;"
        "border-radius:8px;padding:16px;margin:16px 0}pre{white-space:pre-wrap;"
        "overflow-wrap:anywhere;background:#1d1d20;padding:12px;border-radius:6px}</style>"
        "</head><body><h1>Validated analysis notebook</h1>"
        f"<p>Run {html_lib.escape(run_id)}</p>"
        f"<p>Notebook {html_lib.escape(notebook_name)}</p>"
        f"{''.join(sections)}</body></html>"
    )
