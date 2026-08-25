"""MCP tool: run_notebook — execute a notebook on the session's runtime.

Runtime v2: one orchestration path for BOTH backends. The tool ensures a
notebook session through session_service (same as the HTTP API), then calls
the runtime's plain-HTTP headless-run endpoint
(POST /api/agent-notebooks/run). The runtime executes `sp export session`
and commits the notebook AND its output snapshot to the workspace store
under signalpilot-agent/ — durable, replayable without a kernel, and listed
on the web app's Notebooks page.
"""

import json
import logging
from pathlib import PurePosixPath

import httpx

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import mcp_org_id_var, mcp_user_id_var
from gateway.mcp.server import mcp

logger = logging.getLogger(__name__)

_RUN_TIMEOUT_SECONDS = 330


@audited_tool(mcp)
async def run_notebook(
    filename: str,
    code: str,
) -> str:
    """Run a .py notebook on the user's cloud notebook runtime.

    Executes the notebook headlessly and commits both the code and its
    outputs to the workspace store under signalpilot-agent/. Returns cell
    outputs and a URL to view the notebook (with outputs replayed) in the
    browser. Use the signalpilot plugin (`import signalpilot as sp`) for
    charts (sp.ui.altair_chart), tables (sp.ui.table), and interactive
    elements (sp.ui.slider etc.).

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
    from gateway.store import notebook_sessions as ns

    backend = get_notebook_backend()
    factory = get_session_factory()
    async with factory() as session:
        try:
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
            return f"Error starting notebook runtime: {exc}"
        internal = await ns.get_session_internal(
            session, session_id=session_info.id, org_id=org_id
        )

    if internal is None or not internal.upstream_url:
        return "Error: notebook session has no upstream URL"

    try:
        base = session_service.upstream_base_for(internal)
    except session_service.NotebookSessionError as exc:
        return f"Error: {exc}"
    token = _upstream_token(internal)
    if not token:
        return "Error: no runtime auth token available"

    try:
        async with httpx.AsyncClient(timeout=_RUN_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{base}/api/agent-notebooks/run",
                json={"filename": safe_path.as_posix(), "code": code},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        return f"Error reaching notebook runtime: {exc}"
    if resp.status_code != 200:
        return f"Error: runtime returned {resp.status_code}: {resp.text[:500]}"

    data = resp.json()
    stored_path = data.get("path") or f"signalpilot-agent/{safe_path.as_posix()}"
    cell_outputs = ""
    if isinstance(data.get("session"), dict):
        cell_outputs = _format_cell_outputs(data["session"])

    import os
    from urllib.parse import quote

    web_url = os.getenv("SP_WEB_URL", "https://app.signalpilot.ai").rstrip("/")
    notebook_url = f"{web_url}/notebooks?open={quote(stored_path)}"

    parts = []
    if data.get("success"):
        parts.append("Notebook executed successfully.")
    else:
        parts.append(
            f"Notebook execution failed (exit code {data.get('returncode')})."
        )

    if cell_outputs:
        parts.append(f"\n--- Cell Outputs ---\n{cell_outputs}")
    elif str(data.get("log", "")).strip():
        parts.append(f"\n--- run log ---\n{str(data['log']).strip()[:3000]}")

    parts.append(f"stored_path: {stored_path}")
    parts.append(f"notebook_url: {notebook_url}")
    parts.append(f"\nView your notebook at: {notebook_url}")

    return "\n".join(parts)


def _upstream_token(internal) -> str | None:
    """Auth token the runtime accepts: per-session for sandboxes, the shared
    container token for the local direct backend (same resolution the
    notebook proxy uses)."""
    if internal.backend == "direct":
        from gateway.notebook_proxy.auth import _local_notebook_token

        return _local_notebook_token()
    return internal.access_token


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
