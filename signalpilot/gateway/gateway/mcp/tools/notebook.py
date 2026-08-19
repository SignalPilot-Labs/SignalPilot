"""MCP tool: run_notebook — execute a notebook in the session's sandbox.

Runtime v2: one orchestration path. The tool goes through the same
session_service as the HTTP API (no duplicated pod/spec code, image pinning
enforced by the backend), then drives the sandbox with runtime primitives:
write_file → exec `sp export session` → read_file the session JSON.
"""

import json
import logging
import shlex
from pathlib import PurePosixPath

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import mcp_org_id_var, mcp_user_id_var
from gateway.mcp.server import mcp

logger = logging.getLogger(__name__)

_WORKSPACE = "/workspace"
_EXPORT_TIMEOUT_SECONDS = 300


@audited_tool(mcp)
async def run_notebook(
    filename: str,
    code: str,
) -> str:
    """Run a .py notebook in the user's cloud notebook sandbox.

    Writes the notebook file into the notebook workspace and executes it with
    `sp export session`. Returns cell outputs and a URL to view the notebook
    in the browser.

    Args:
        filename: Name of the .py file (e.g. "analysis.py")
        code: Full contents of the .py notebook file
    """
    org_id = mcp_org_id_var.get(None) or "local"
    user_id = mcp_user_id_var.get(None) or "local"

    safe_path = PurePosixPath(filename)
    if not filename.endswith(".py"):
        return "Error: filename must end with .py"
    if safe_path.is_absolute() or any(part in {"", ".", ".."} for part in safe_path.parts):
        return "Error: filename must be a relative path inside the notebook workspace"
    if not code.strip():
        return "Error: code is empty"

    from gateway.db.engine import get_session_factory
    from gateway.notebooks import session_service
    from gateway.notebooks.backends import get_notebook_backend
    from gateway.sandbox_runtime import get_sandbox_runtime
    from gateway.store import notebook_sessions as ns

    backend = get_notebook_backend()
    if backend.name != "vercel":
        return (
            "Error: run_notebook needs the vercel notebook backend "
            "(the local direct container has no execution channel)"
        )

    factory = get_session_factory()
    async with factory() as session:
        try:
            # Agent notebooks are not branch-routed: they always run on the
            # workspace's default branch.
            session_info = await session_service.ensure_notebook_session(
                session,
                org_id=org_id,
                user_id=user_id,
                project_id=None,
                branch="main",
                extra_env={"SP_AGENT_MODE": "true"},
                backend=backend,
            )
        except session_service.NotebookSessionError as exc:
            return f"Error starting notebook sandbox: {exc}"
        internal = await ns.get_session_internal(session, session_id=session_info.id, org_id=org_id)

    if internal is None or not internal.runtime_handle:
        return "Error: notebook session has no runtime handle"
    handle = internal.runtime_handle
    session_id = internal.session_id

    runtime = get_sandbox_runtime()
    notebook_path = f"{_WORKSPACE}/{safe_path.as_posix()}"
    await runtime.write_file(handle, notebook_path, code.encode("utf-8"))

    result = await runtime.exec(
        handle,
        f"cd {_WORKSPACE} && python -m signalpilot export session "
        f"{shlex.quote(notebook_path)} --force-overwrite --verbose",
        timeout_seconds=_EXPORT_TIMEOUT_SECONDS,
    )

    cell_outputs = ""
    session_json_path = f"{_WORKSPACE}/__sp__/session/{safe_path.as_posix()}.json"
    try:
        raw = await runtime.read_file(handle, session_json_path)
        if raw:
            cell_outputs = _format_cell_outputs(json.loads(raw.decode("utf-8")))
    except Exception as exc:
        logger.warning("Failed to read session JSON: %s", exc)

    import os
    from urllib.parse import quote

    web_url = os.getenv("SP_WEB_URL", "https://app.signalpilot.ai").rstrip("/")
    notebook_url = (
        f"{web_url}/projects"
        f"?file={quote(safe_path.as_posix())}&session_id={quote(session_id or '')}"
    )

    parts = []
    if result.ok:
        parts.append("Notebook executed successfully.")
    else:
        parts.append(f"Notebook execution failed (exit code {result.returncode}).")

    if cell_outputs:
        parts.append(f"\n--- Cell Outputs ---\n{cell_outputs}")
    elif result.stderr.strip():
        parts.append(f"\n--- output ---\n{result.stderr.strip()}")

    if not result.ok and result.stdout.strip():
        parts.append(f"\n--- export log ---\n{result.stdout.strip()}")

    parts.append(f"notebook_url: {notebook_url}")
    parts.append(f"\nView your notebook at: {notebook_url}")

    return "\n".join(parts)


def _format_cell_outputs(session_data: dict) -> str:
    """Extract human-readable cell outputs from the session JSON."""
    import html
    import re

    parts = []
    cells = session_data.get("cells", [])

    for cell in cells:
        if not isinstance(cell, dict):
            continue
        cell_id = cell.get("id", "?")
        outputs = cell.get("outputs", [])
        console = cell.get("console", [])
        cell_parts = []

        # Console output (print statements)
        for entry in console:
            if isinstance(entry, dict):
                text = entry.get("text", "")
                if text:
                    cell_parts.append(text.rstrip("\n"))

        # Data outputs
        for out in outputs:
            if not isinstance(out, dict):
                continue
            data = out.get("data", {})
            if not isinstance(data, dict):
                continue

            plain = data.get("text/plain", "")
            html_content = data.get("text/html", "")

            if plain and plain.strip():
                cell_parts.append(plain.strip()[:2000])
            elif html_content:
                # Extract table data from sp-table elements
                match = re.search(r"data-data='(.*?)'", html_content)
                if match:
                    try:
                        raw = html.unescape(match.group(1))
                        raw = raw.strip('"').replace('\\"', '"')
                        rows = json.loads(raw)
                        if rows and isinstance(rows, list):
                            cols = list(rows[0].keys())
                            cell_parts.append(f"  [{len(rows)} rows x {len(cols)} cols: {', '.join(cols)}]")
                            for row in rows[:5]:
                                cell_parts.append(f"  {row}")
                            if len(rows) > 5:
                                cell_parts.append(f"  ... ({len(rows) - 5} more rows)")
                    except Exception:
                        cell_parts.append(f"  [table output, {len(html_content)} chars]")
                else:
                    cell_parts.append(f"  [HTML output, {len(html_content)} chars]")

        if cell_parts:
            parts.append(f"[Cell {cell_id}]")
            parts.extend(f"  {line}" for line in cell_parts)

    return "\n".join(parts) if parts else ""
