"""Notebook kernel, archive, checkout, and integrity helpers for chat."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html as html_lib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import httpx
from starlette.exceptions import HTTPException

from signalpilot import _loggers
from signalpilot._server.ai.chat_runtime_output import (
    compact_chat_runtime_output,
)
from signalpilot._server.files.workspace import PROJECTS_ROOT
from signalpilot._utils.requests import RequestError

LOGGER = _loggers.sp_logger()
_ANALYSIS_SESSIONS_BY_RUN: dict[str, str] = {}

# Completed runs keep their analysis kernel and notebook ALIVE so the chat
# page's live notebook panel can stay attached (or attach late) and show the
# real rendered outputs. One keepalive per conversation: the next run in the
# conversation replaces it; the sandbox's own lifecycle bounds it otherwise.
_KEEPALIVE_BY_CONVERSATION: dict[str, tuple[str, Path]] = {}


def register_keepalive_analysis_session(
    *,
    conversation_id: str,
    session_id: str,
    scratch: Path,
) -> None:
    """Keep a finished run's kernel + notebook for the live notebook panel.

    The scoped gateway token file is deleted immediately: the browser view is
    read-only and no gateway calls happen between runs. The next run's
    adoption writes a fresh run-scoped token to the same path, and the
    kernel's SDK client reads that file per request.
    """
    _KEEPALIVE_BY_CONVERSATION[conversation_id] = (session_id, scratch)
    try:
        (scratch / ".gateway-token").unlink(missing_ok=True)
    except OSError:
        pass


def close_keepalive_analysis_session(app: Any, conversation_id: str) -> None:
    """Close and clean the previous run's kept-alive kernel, if any."""
    entry = _KEEPALIVE_BY_CONVERSATION.pop(conversation_id, None)
    if entry is None:
        return
    session_id, scratch = entry
    try:
        _close_analysis_kernel(app, session_id)
    except Exception:
        LOGGER.warning(
            "Keepalive analysis kernel close failed conversation_id=%s",
            conversation_id,
            exc_info=True,
        )
    shutil.rmtree(scratch, ignore_errors=True)


def adopt_keepalive_analysis_session(
    app: Any,
    conversation_id: str,
    *,
    scoped_token: str,
) -> tuple[str, Path] | None:
    """Adopt the conversation's kept-alive kernel for a NEW run.

    Returns (session_id, notebook_path) when the previous turn's kernel is
    still alive so the run continues in the SAME notebook — the agent keeps
    its session id across turns and the live notebook panel stays attached.
    Writes the new run's scoped token where the notebook's setup cell reads
    it, so re-running that cell refreshes credentials.

    Returns None (after cleanup) when there is no live kernel to adopt.
    """
    entry = _KEEPALIVE_BY_CONVERSATION.get(conversation_id)
    if entry is None:
        return None
    session_id, scratch = entry
    notebook_path = scratch / "analysis.py"
    session = None
    try:
        session = _analysis_session(app, session_id)
    except Exception:
        session = None
    if session is None or not notebook_path.is_file():
        _KEEPALIVE_BY_CONVERSATION.pop(conversation_id, None)
        try:
            _close_analysis_kernel(app, session_id)
        except Exception:
            pass
        shutil.rmtree(scratch, ignore_errors=True)
        return None
    token_file = scratch / ".gateway-token"
    token_file.write_text(scoped_token, encoding="utf-8")
    try:
        token_file.chmod(0o600)
    except OSError:
        pass
    return session_id, notebook_path


def _scratch_directory(run_id: str) -> Path:
    root = Path(
        os.getenv(
            "SP_CHAT_SCRATCH_ROOT",
            "/tmp/signalpilot-chat-runs",  # nosec B108 - container-local scratch
        )
    ).resolve()
    scratch = (root / run_id).resolve()
    if root not in scratch.parents:
        raise HTTPException(status_code=400, detail="Invalid scratch path")
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch


def _seed_analysis_notebook(
    *,
    scratch: Path,
    run_id: str,
    project_id: str,
    connection_name: str,
    gateway_url: str,
    scoped_token: str,
) -> Path:
    token_file = scratch / ".gateway-token"
    token_file.write_text(scoped_token, encoding="utf-8")
    token_file.chmod(0o600)
    notebook_path = scratch / "analysis.py"
    context = json.dumps(
        {
            "run_id": run_id,
            "project_id": project_id,
            "connection_name": connection_name,
        }
    )
    notebook_path.write_text(
        f"""import signalpilot as sp

__generated_with = "0.1.0"
app = sp.App()


@app.cell(hide_code=True)
def _():
    import os
    from pathlib import Path
    import signalpilot as sp
    runtime_context = {context}
    os.environ["SP_CHAT_SCRATCH_DIRECTORY"] = {str(scratch)!r}
    os.environ["SP_CHAT_NOTEBOOK_PATH"] = {str(notebook_path)!r}
    return Path, runtime_context, sp


@app.cell(hide_code=True)
def _(Path, sp):
    sp.init(gateway_url={gateway_url!r}, session_token_file=Path({str(token_file)!r}))
    db = sp.connect({connection_name!r})
    return (db,)


@app.cell(hide_code=True)
def _(db):
    analysis_summary = {{"status": "pending", "preview": []}}
    return (analysis_summary,)


@app.cell(hide_code=True)
def _(analysis_summary):
    analysis_checks = {{"nulls": None, "duplicates": None, "freshness": None, "reconciled": False}}
    return (analysis_checks,)


@app.cell(hide_code=True)
def _(analysis_checks, analysis_summary, sp):
    sp.md("## Analysis output\\n\\nPending governed notebook analysis.")


if __name__ == "__main__":
    app.run()
""",
        encoding="utf-8",
    )
    return notebook_path


def _analysis_session(app: Any, session_id: str) -> Any:
    from signalpilot._server.ai.tools.base import ToolContext

    return ToolContext(app=app).get_session(session_id)


def _is_error_output(output: Any) -> bool:
    channel = getattr(output, "channel", None)
    return getattr(channel, "value", channel) == "sp-error"


def _safe_notebook_error(error: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": str(error.get("type") or "NotebookValidationError")[:100],
        "variable": str(error.get("variable") or "")[:100] or None,
        "cell_ids": [
            str(value)[:100] for value in error.get("cell_ids") or []
        ][:20],
    }


def _with_recorded_notebook_errors(
    session: Any, failure: dict[str, Any]
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()
    recorded = getattr(session, "_signalpilot_notebook_failures", ())
    candidates = [
        *(item.get("error") or {} for item in recorded),
        failure.get("error") or {},
    ]
    for candidate in candidates:
        safe = _safe_notebook_error(candidate)
        key = json.dumps(safe, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        errors.append(safe)
    return {**failure, "errors": errors[-20:]}


def _notebook_failure(app: Any, session_id: str) -> dict[str, Any] | None:
    session = _analysis_session(app, session_id)
    if getattr(session, "_signalpilot_notebook_dirty", False):
        failure = dict(
            getattr(session, "_signalpilot_last_notebook_failure", None)
            or {
                "error": {
                    "type": "DocumentKernelSynchronizationError",
                    "variable": None,
                    "cell_ids": [],
                }
            }
        )
        return _with_recorded_notebook_errors(session, failure)

    for cell in session.app_file_manager.app.cell_manager.cell_data():
        cell_id = cell.cell_id
        notification = session.session_view.cell_notifications.get(cell_id)
        if notification is None:
            return _with_recorded_notebook_errors(
                session,
                {
                    "error": {
                        "type": "UnknownStateError",
                        "variable": None,
                        "cell_ids": [str(cell_id)],
                    }
                },
            )
        status = str(getattr(notification, "status", "") or "")
        if status != "idle":
            return _with_recorded_notebook_errors(
                session,
                {
                    "error": {
                        "type": "UnknownStateError",
                        "variable": None,
                        "cell_ids": [str(cell_id)],
                    }
                },
            )
        output = getattr(notification, "output", None)
        if _is_error_output(output):
            raw_errors = getattr(output, "data", None)
            error = (
                raw_errors[0]
                if isinstance(raw_errors, list) and raw_errors
                else None
            )
            involved = {str(cell_id)}
            involved.update(
                str(value) for value in getattr(error, "cells", ())
            )
            edge_variables: set[str] = set()
            for source, variables, target in getattr(
                error, "edges_with_vars", ()
            ):
                involved.update((str(source), str(target)))
                edge_variables.update(str(value) for value in variables)
            variable = getattr(error, "name", None)
            if variable is None and edge_variables:
                variable = sorted(edge_variables)[0]
            return _with_recorded_notebook_errors(
                session,
                {
                    "error": {
                        "type": type(error).__name__
                        if error
                        else "CellExecutionError",
                        "variable": variable,
                        "cell_ids": sorted(involved),
                    }
                },
            )
    return None


def _recovery_context(failure: dict[str, Any]) -> str:
    raw_errors = failure.get("errors") or [failure.get("error") or {}]
    safe_errors = [_safe_notebook_error(error) for error in raw_errors][:20]
    return (
        "The first notebook attempt was rejected and its notebook and artifacts "
        "were discarded. Start the newly seeded notebook, execute the evidence "
        "again, validate every requested cell, and answer only from this clean "
        "attempt. Treat every listed graph error as an explicit instruction not "
        "to recreate those duplicate globals; use unique public names, private "
        "underscore-prefixed scratch names, or uniquely named functions. Private "
        "underscore-prefixed names are cell-local and cannot be read from another "
        "cell. Re-run changed SQL through the SDK so it is governed automatically. "
        "Never replace SDK query "
        "evidence with copied MCP preview rows. "
        f"Recovery errors: {json.dumps(safe_errors, sort_keys=True)}"
    )


def _log_notebook_failure(
    *,
    run_id: str,
    session_id: str,
    attempt: int,
    failure: dict[str, Any],
) -> None:
    error = failure.get("error") or {}
    LOGGER.error(
        "Standalone notebook validation failed run_id=%s session_id=%s "
        "attempt=%s error_type=%s variable=%s cell_ids=%s",
        run_id,
        session_id,
        attempt,
        error.get("type"),
        error.get("variable"),
        error.get("cell_ids"),
    )


async def _archive_analysis_notebook(
    *,
    app: Any,
    session_id: str,
    run_id: str,
    gateway_api_url: str,
    scoped_token: str,
) -> str:
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
            filename="analysis.py",
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
        {"version": 1, "run_id": run_id, "cells": cells},
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
        f"<p>Run {html_lib.escape(run_id)}</p>{''.join(sections)}</body></html>"
    )


def _close_analysis_kernel(app: Any, session_id: str) -> bool:
    from signalpilot._server.ai.tools.base import ToolContext
    from signalpilot._types.ids import SessionId

    return ToolContext(app=app).session_manager.close_session(
        SessionId(session_id)
    )


def _start_analysis_kernel(app: Any, notebook_path: Path) -> str:
    from signalpilot._server.ai.notebook_mcp import (
        _handle_start_notebook_session,
    )
    from signalpilot._server.ai.tools.base import ToolContext

    result = _handle_start_notebook_session(
        ToolContext(app=app),
        {"file_path": str(notebook_path), "auto_run": True},
    )
    if not result:
        raise RuntimeError("Clean notebook kernel did not start")
    try:
        started = json.loads(str(getattr(result[0], "text", "")))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Clean notebook kernel returned an invalid response"
        ) from exc
    session_id = str(started.get("session_id") or "")
    if not session_id or str(started.get("status") or "").startswith("error"):
        raise RuntimeError("Clean notebook kernel did not start")
    return session_id


_CHECKOUT_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,80}$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _checkout_directory(project_id: str, checkout_id: str) -> Path:
    """Validated scratch location for one run's materialized checkout."""
    if not _UUID_RE.fullmatch(project_id):
        raise ValueError(f"Invalid project ID: {project_id!r}")
    if not _CHECKOUT_ID_RE.fullmatch(checkout_id):
        raise ValueError("Invalid frozen checkout id")
    root = (PROJECTS_ROOT / ".standalone-chat" / project_id).resolve()
    checkout = (root / checkout_id).resolve()
    if root not in checkout.parents:
        raise ValueError("Invalid frozen checkout path")
    return checkout


def _materialize_snapshot_checkout(
    *,
    project_id: str,
    branch: str,
    checkout_id: str,
    gateway_url: str,
    gateway_token: str,
) -> Path:
    """Materialize a disposable execution checkout from the S3 snapshot.

    Disk is never the truth: the tarball is the branch head's revision,
    pulled through the gateway Workspace Files API snapshot endpoint.
    """
    import tarfile
    import tempfile

    if not gateway_token:
        raise ValueError("Scoped gateway identity required")
    checkout = _checkout_directory(project_id, checkout_id)

    response = httpx.get(
        f"{gateway_url}/api/workspace-projects/{project_id}/snapshot",
        params={"branch": branch},
        headers={"Authorization": f"Bearer {gateway_token}"},
        timeout=30.0,
    )
    response.raise_for_status()
    snapshot_url = str(response.json().get("url") or "")
    if not snapshot_url:
        raise ValueError("No snapshot URL available")

    if checkout.exists():
        shutil.rmtree(checkout)
    checkout.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryFile() as spool:
        with httpx.stream("GET", snapshot_url, timeout=120.0) as tarball:
            tarball.raise_for_status()
            for chunk in tarball.iter_bytes():
                spool.write(chunk)
        spool.seek(0)
        with tarfile.open(fileobj=spool, mode="r:*") as tar:
            for member in tar.getmembers():
                name = member.name.replace("\\", "/")
                if (
                    name.startswith(("/", "../"))
                    or "/../" in name
                    or member.islnk()
                    or member.issym()
                ):
                    raise ValueError(
                        f"Unsafe member in snapshot tarball: {member.name!r}"
                    )
            tar.extractall(checkout, filter="data")
    return checkout


async def _execution_project_directory(
    *,
    run_id: str,
    project_id: str,
    branch: str,
    gateway_url: str,
    gateway_token: str,
) -> tuple[Path, bool]:
    """Return (checkout_path, created). Reuses this run's existing checkout
    (follow-up messages in the same run); otherwise pulls a fresh snapshot."""
    try:
        checkout = _checkout_directory(project_id, run_id)
        if checkout.is_dir() and any(checkout.iterdir()):
            return checkout, False
        checkout = await asyncio.to_thread(
            _materialize_snapshot_checkout,
            project_id=project_id,
            branch=branch,
            checkout_id=run_id,
            gateway_url=gateway_url,
            gateway_token=gateway_token,
        )
    except (OSError, ValueError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=409,
            detail="Frozen project workspace could not be prepared",
        ) from exc
    return checkout, True


# Ephemeral outputs that dbt/python tooling drops into the checkout during a
# read-only analysis. They are not project source, so they must not trip the
# integrity check â€” only human-authored files are frozen.
_DIGEST_IGNORED_DIRS = frozenset(
    {"target", "logs", "dbt_packages", "__pycache__", ".ruff_cache", ".pytest_cache"}
)
_DIGEST_IGNORED_FILES = frozenset({".user.yml", "package-lock.yml"})


def _tree_digest(directory: Path) -> str:
    """Content digest of a materialized checkout.

    Replaces the git-status integrity check from the worktree era: the frozen
    checkout has no git, so 'unchanged' means every file's bytes hash the same
    as when the run started. Path order is normalized so the digest is stable
    across platforms. Generated artifacts (dbt target/, logs/, caches) are
    excluded on both the baseline and the final check.
    """
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*"), key=lambda p: p.as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(directory)
        if any(part in _DIGEST_IGNORED_DIRS for part in relative.parts[:-1]):
            continue
        if relative.name in _DIGEST_IGNORED_FILES or relative.name.endswith(".log"):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _project_is_unchanged(directory: Path, baseline_digest: str) -> bool:
    return _tree_digest(directory) == baseline_digest


def _runtime_auth_override(body: dict[str, Any]) -> dict[str, str] | None:
    value = body.get("runtime_auth")
    if not isinstance(value, dict):
        return None
    auth_type = str(value.get("type") or "")
    token = str(value.get("token") or "").strip()
    if (
        auth_type not in {"api_key", "oauth"}
        or not token
        or len(token) > 20_000
    ):
        raise HTTPException(
            status_code=400, detail="Invalid runtime credential"
        )
    return {"type": auth_type, "token": token}
