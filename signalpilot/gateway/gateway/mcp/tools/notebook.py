"""MCP tool: run_notebook — execute a notebook in a cloud pod."""

import logging
import tempfile
from pathlib import Path, PurePosixPath

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import mcp_org_id_var, mcp_user_id_var
from gateway.mcp.server import mcp

logger = logging.getLogger(__name__)


@audited_tool(mcp)
async def run_notebook(
    filename: str,
    code: str,
    agent_branch: str = "",
) -> str:
    """Run a .py notebook in a cloud K8s pod.

    Writes the notebook file into the user's notebook workspace and executes it
    with `sp export session`. Returns stdout/stderr and a URL to view the
    notebook in the browser.

    Args:
        filename: Name of the .py file (e.g. "analysis.py")
        code: Full contents of the .py notebook file
        agent_branch: Deprecated legacy label; ignored for project routing.
    """
    org_id = mcp_org_id_var.get(None) or "local"
    user_id = mcp_user_id_var.get(None) or "local"

    safe_path = PurePosixPath(filename)
    if not filename.endswith(".py"):
        return "Error: filename must end with .py"
    if safe_path.is_absolute() or any(
        part in {"", ".", ".."} for part in safe_path.parts
    ):
        return "Error: filename must be a relative path inside the notebook workspace"
    if not code.strip():
        return "Error: code is empty"

    # 1. Get or create notebook session (pod reuse)
    from gateway.db.engine import get_session_factory
    from gateway.orchestrator.kubernetes import KubernetesOrchestrator
    from gateway.store import notebook_sessions as ns

    factory = get_session_factory()
    orch = KubernetesOrchestrator()
    branch_label = agent_branch or "main"

    async with factory() as session:
        existing = await ns.get_active_session(session, org_id=org_id, user_id=user_id)
        pod_name = None
        session_id = None

        if existing and existing.status == "running" and existing.pod_name:
            if await orch.is_pod_alive(existing.pod_name, org_id=org_id):
                pod_name = existing.pod_name
                session_id = existing.id

        if not pod_name:
            # Create a new session — follows the pattern from notebook_sessions.py
            import hashlib
            import os

            from gateway.auth.notebook_jwt import mint_session_jwt
            from gateway.config.k8s import get_k8s_settings
            from gateway.orchestrator.jwt_secret_lifecycle import (
                create_jwt_secret_with_owner_ref,
            )

            h = hashlib.sha256(f"{org_id}:{user_id}".encode()).hexdigest()[:12]
            pod_name = f"nb-{h}"
            k8s_settings = get_k8s_settings()

            # Clean up any stale session
            if existing:
                await ns.mark_stopped(session, session_id=existing.id, org_id=existing.org_id)
            await ns.delete_stopped(session, org_id=org_id, user_id=user_id)

            session_info = await ns.create_session(
                session, org_id=org_id, user_id=user_id,
                project_id=None, branch=branch_label, pod_name=pod_name,
            )
            session_id = session_info.id

            session_jwt = mint_session_jwt(
                user_id=user_id, org_id=org_id, session_id=session_id,
                project_id=None,
                branch=branch_label,
                ttl=k8s_settings.sp_session_jwt_ttl_seconds,
            )

            await orch._ensure_client()
            if not orch._core_api:
                await ns.update_session_status(session, session_id=session_id, org_id=org_id, status="error")
                return "Error starting notebook pod: K8s orchestrator not available"
            core_v1 = orch._core_api
            ns_name = await orch.ensure_namespace(org_id)

            async def _create_pod_fn():
                return await orch.create_pod(
                    pod_name=pod_name, user_id=user_id, org_id=org_id,
                    project_id=None,
                    branch=branch_label,
                    image=os.getenv("SP_NOTEBOOK_IMAGE", "signalpilot-notebook:latest"),
                    gateway_url=k8s_settings.sp_public_gateway_url,
                    session_jwt_secret_name=f"sp-jwt-{pod_name}",
                    session_id=session_id,
                    access_token=session_info.access_token,
                    extra_env={"SP_AGENT_MODE": "true"},
                )

            try:
                await create_jwt_secret_with_owner_ref(
                    core_v1,
                    namespace=ns_name,
                    pod_name=pod_name,
                    session_jwt=session_jwt,
                    create_pod_fn=_create_pod_fn,
                )
            except Exception as exc:
                await ns.update_session_status(session, session_id=session_id, org_id=org_id, status="error")
                return f"Error starting notebook pod: {exc}"

            try:
                await orch.wait_for_running(pod_name, org_id=org_id, timeout=90)
                await orch.wait_for_ready(pod_name, org_id=org_id, timeout=90)
                pod_info = await orch.get_pod(pod_name, org_id=org_id)
                await ns.update_session_status(
                    session, session_id=session_id, org_id=org_id, status="running",
                    pod_ip=pod_info.ip if pod_info else None,
                    pod_ip_internal=pod_info.ip if pod_info else None,
                )
            except Exception as exc:
                await ns.update_session_status(session, session_id=session_id, org_id=org_id, status="error")
                try:
                    await orch.delete_pod(pod_name, org_id=org_id)
                except Exception:
                    pass
                return f"Error starting notebook pod: {exc}"

    # 2. Write the .py file into the notebook workspace.
    workspace_dir = "/workspace"
    notebook_path = f"{workspace_dir}/{safe_path.as_posix()}"
    await orch.exec_in_pod(
        pod_name, org_id=org_id,
        argv=["mkdir", "-p", workspace_dir],
        timeout=10,
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        host_file = tmp_path / safe_path.as_posix()
        host_file.parent.mkdir(parents=True, exist_ok=True)
        host_file.write_text(code, encoding="utf-8")
        from gateway.orchestrator.pod_exec_io import stream_tar_into_pod
        ns_name = orch._resolve_namespace(org_id)
        await orch._ensure_client()
        await stream_tar_into_pod(
            orch._core_api,
            namespace=ns_name,
            pod_name=pod_name,
            src_dir=tmp_path,
            dest_path=f"{workspace_dir}/",
        )

    # 3. Run sp export session from the notebook workspace.
    stdout, stderr, exit_code = await orch.exec_in_pod(
        pod_name, org_id=org_id,
        argv=[
            "python", "-m", "signalpilot", "export", "session",
            notebook_path, "--force-overwrite", "--verbose",
        ],
        timeout=300,
    )

    # 4. Read session JSON from pod to extract cell outputs.
    cell_outputs = ""
    session_json_path = f"{workspace_dir}/__sp__/session/{safe_path.as_posix()}.json"
    try:
        cat_stdout, _, cat_rc = await orch.exec_in_pod(
            pod_name, org_id=org_id,
            argv=["cat", session_json_path],
            timeout=10,
        )
        if cat_rc == 0 and cat_stdout.strip():
            import json
            session_data = json.loads(cat_stdout)
            cell_outputs = _format_cell_outputs(session_data)
    except Exception as e:
        logger.warning("Failed to read session JSON: %s", e)

    # 5. Build notebook URL — link to the web app, not the gateway proxy.
    import os
    from urllib.parse import quote
    web_url = os.getenv("SP_WEB_URL", "https://app.signalpilot.ai").rstrip("/")
    notebook_url = (
        f"{web_url}/projects"
        f"?file={quote(safe_path.as_posix())}&session_id={quote(session_id or '')}"
    )

    # 6. Format result.
    parts = []
    if exit_code == 0:
        parts.append("Notebook executed successfully.")
    else:
        parts.append(f"Notebook execution failed (exit code {exit_code}).")

    if cell_outputs:
        parts.append(f"\n--- Cell Outputs ---\n{cell_outputs}")
    elif stderr.strip():
        parts.append(f"\n--- output ---\n{stderr.strip()}")

    if exit_code != 0 and stdout.strip():
        parts.append(f"\n--- export log ---\n{stdout.strip()}")

    parts.append(f"notebook_url: {notebook_url}")
    parts.append(f"\nView your notebook at: {notebook_url}")

    return "\n".join(parts)


def _format_cell_outputs(session_data: dict) -> str:
    """Extract human-readable cell outputs from the session JSON."""
    import html
    import json
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
