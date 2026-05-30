"""MCP tool: run_notebook — execute a notebook in a cloud pod."""

import logging
import re
import uuid

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session, mcp_org_id_var, mcp_user_id_var
from gateway.mcp.server import mcp

logger = logging.getLogger(__name__)

# Filename must be a plain name with no path separators.
# Rejects shell metacharacters, path traversal, and anything not a safe Python filename.
# Branch names are copied from notebook-server/signalpilot/_server/files/project_sync.py:28.
_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.py$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")


def _validate_filename(filename: str) -> str | None:
    """Return None if filename is valid, else an error string."""
    if not _FILENAME_RE.match(filename):
        return "Error: filename must match [A-Za-z0-9._-]+.py (no path separators or special chars)"
    return None


def _validate_branch(branch: str) -> str | None:
    """Return None if branch is valid, else an error string."""
    if not branch or branch.startswith("-") or not _BRANCH_RE.match(branch):
        return f"Error: agent_branch {branch!r} is invalid (must match [A-Za-z0-9._/\\-]+ and not start with -)"
    return None


@audited_tool(mcp)
async def run_notebook(
    filename: str,
    code: str,
    project_id: str,
    agent_branch: str = "",
) -> str:
    """Run a .py notebook in a cloud K8s pod.

    Creates an agent branch on first call (pass back agent_branch on subsequent calls).
    Writes the notebook file to the branch in git, injects it into the pod, and
    executes it with `sp export session`. Returns stdout/stderr and a URL to view
    the notebook in the browser.

    Args:
        filename: Name of the .py file (e.g. "analysis.py")
        code: Full contents of the .py notebook file
        project_id: Workspace project ID to run against
        agent_branch: Branch name from a previous call (empty = create new branch)
    """
    org_id = mcp_org_id_var.get(None) or "local"
    user_id = mcp_user_id_var.get(None) or "local"

    # Validate filename first — before any use in paths or exec calls.
    filename_err = _validate_filename(filename)
    if filename_err:
        return filename_err

    if not code.strip():
        return "Error: code is empty"

    # 1. Validate project exists
    async with _store_session(user_id=user_id, org_id=org_id) as store:
        project = await store.get_workspace_project(project_id)
        if not project:
            return f"Error: project {project_id} not found"
        project_name = getattr(project, "name", None)
        if not project_name:
            return f"Error: project {project_id} has no name — cannot resolve pod project directory"

    # 2. Create or reuse agent branch via git
    from gateway.git.repos import _run_git, repo_exists, repo_path

    if not repo_exists(project_id):
        return f"Error: git repo not initialized for project {project_id}"

    rp = repo_path(project_id)
    if not agent_branch:
        agent_branch = f"signalpilot-agent/{uuid.uuid4().hex[:12]}"
        # Create branch in the bare repo (from HEAD if main exists, else orphan)
        rc, out, err = _run_git("branch", agent_branch, "main", cwd=rp)
        if rc != 0 and "not a valid" in err:
            rc, out, err = _run_git("branch", agent_branch, cwd=rp)
        if rc != 0 and "already exists" not in err:
            return f"Error creating branch: {err}"
        logger.info("Created agent branch %s for project %s", agent_branch, project_id)
    else:
        # Validate branch name before using it in exec argv.
        branch_err = _validate_branch(agent_branch)
        if branch_err:
            return branch_err
        # Verify branch exists
        rc, out, err = _run_git("rev-parse", "--verify", f"refs/heads/{agent_branch}", cwd=rp)
        if rc != 0:
            return f"Error: branch {agent_branch} not found"

    # 3. Get or create notebook session (pod reuse)
    from gateway.db.engine import get_session_factory
    from gateway.orchestrator.kubernetes import KubernetesOrchestrator
    from gateway.store import notebook_sessions as ns

    factory = get_session_factory()
    orch = KubernetesOrchestrator()

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

            h = hashlib.sha256(f"{org_id}:{user_id}".encode()).hexdigest()[:12]
            pod_name = f"nb-{h}"
            k8s_settings = get_k8s_settings()

            # Clean up any stale session
            if existing:
                await ns.mark_stopped(session, session_id=existing.id)
            await ns.delete_stopped(session, org_id=org_id, user_id=user_id)

            session_info = await ns.create_session(
                session, org_id=org_id, user_id=user_id,
                project_id=project_id, branch=agent_branch, pod_name=pod_name,
            )
            session_id = session_info.id

            session_jwt = mint_session_jwt(
                user_id=user_id, org_id=org_id, session_id=session_id,
                project_id=project_id, branch=agent_branch,
                ttl=k8s_settings.sp_session_jwt_ttl_seconds,
            )

            try:
                await orch.create_pod(
                    pod_name=pod_name, user_id=user_id, org_id=org_id,
                    project_id=project_id, branch=agent_branch,
                    image=os.getenv("SP_NOTEBOOK_IMAGE", "signalpilot-notebook:latest"),
                    gateway_url=k8s_settings.sp_public_gateway_url,
                    session_jwt=session_jwt, session_id=session_id,
                    access_token=session_info.access_token,
                    extra_env={"SP_AGENT_MODE": "true"},
                )
                await orch.wait_for_running(pod_name, org_id=org_id, timeout=90)
                # Pod entrypoint runs project_sync_boot (git clone) then exec sp edit.
                # wait_for_ready's TCP probe on :2718 gates clone success.
                await orch.wait_for_ready(pod_name, org_id=org_id, timeout=90)
                pod_info = await orch.get_pod(pod_name, org_id=org_id)
                await ns.update_session_status(
                    session, session_id=session_id, status="running",
                    pod_ip=pod_info.ip if pod_info else None,
                    pod_ip_internal=pod_info.ip if pod_info else None,
                )
            except Exception as exc:
                await ns.update_session_status(session, session_id=session_id, status="error")
                try:
                    await orch.delete_pod(pod_name, org_id=org_id)
                except Exception:
                    pass
                return f"Error starting notebook pod: {exc}"

    # 4. Locate the git clone that project_sync_boot placed in the pod at boot.
    # The entrypoint ran project_sync_boot before sp edit, so the deterministic path
    # is guaranteed. If missing, the boot failed — hard error, no fallback.
    project_dir = f"/home/notebook/.sp/projects/{project_id}/{project_name}"

    # Verify the project directory exists in the pod.
    check_out, check_err, check_rc = await orch.exec_in_pod(
        pod_name, org_id=org_id,
        argv=["test", "-d", project_dir],
        timeout=10,
    )
    if check_rc != 0:
        return (
            f"Error: project directory {project_dir!r} not found in pod. "
            "project_sync_boot may have failed. Check pod logs."
        )

    # 5. Write the .py file into the project directory via tee (argv + stdin, no shell).
    w_out, w_err, w_rc = await orch.exec_in_pod(
        pod_name, org_id=org_id,
        argv=["tee", f"{project_dir}/{filename}"],
        stdin_bytes=code.encode("utf-8"),
        timeout=30,
    )
    if w_rc != 0:
        logger.warning("Failed to write %s to pod %s (rc=%d): %s", filename, pod_name, w_rc, w_err.strip())

    # 6. Run sp export session from the project directory — absolute paths, no cd, no sh -c.
    stdout, stderr, exit_code = await orch.exec_in_pod(
        pod_name, org_id=org_id,
        argv=["python", "-m", "signalpilot", "export", "session",
              f"{project_dir}/{filename}", "--force-overwrite", "--verbose"],
        timeout=300,
    )

    # 7. Read session JSON from pod to extract cell outputs
    cell_outputs = ""
    session_json_path = f"{project_dir}/__sp__/session/{filename}.json"
    try:
        cat_stdout, cat_stderr, cat_rc = await orch.exec_in_pod(
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

    # 8. Commit and push results back via git — three separate exec calls, all argv.
    push_result = ""
    try:
        git_steps = [
            ["git", "-C", project_dir, "add", "-A"],
            ["git", "-C", project_dir, "commit", "-m", f"agent: {filename}"],
            ["git", "-C", project_dir, "push", "origin", f"HEAD:refs/heads/{agent_branch}"],
        ]
        for git_argv in git_steps:
            g_out, g_err, g_rc = await orch.exec_in_pod(
                pod_name, org_id=org_id,
                argv=git_argv,
                timeout=30,
            )
            if g_rc != 0 and "nothing to commit" not in g_err:
                push_result = f"failed: {g_err.strip()}"
                break
        else:
            push_result = "pushed to git"
    except Exception as e:
        logger.warning("Failed to push results to git: %s", e)
        push_result = f"push failed: {e}"

    # 9. Build notebook URL — link to the web app, not the gateway proxy
    import os
    from urllib.parse import quote
    web_url = os.getenv("SP_WEB_URL", "https://app.signalpilot.ai").rstrip("/")
    notebook_url = (
        f"{web_url}/projects"
        f"?project={project_id}&branch={quote(agent_branch)}&file={quote(filename)}"
    )

    # 10. Format result
    parts = []
    if exit_code == 0:
        parts.append(f"Notebook executed successfully. ({push_result})")
    else:
        parts.append(f"Notebook execution failed (exit code {exit_code}).")

    if cell_outputs:
        parts.append(f"\n--- Cell Outputs ---\n{cell_outputs}")
    elif stderr.strip():
        parts.append(f"\n--- output ---\n{stderr.strip()}")

    if exit_code != 0 and stdout.strip():
        parts.append(f"\n--- export log ---\n{stdout.strip()}")

    parts.append(f"\nagent_branch: {agent_branch}")
    parts.append(f"notebook_url: {notebook_url}")
    parts.append(f"\nView your notebook at: {notebook_url}")

    return "\n".join(parts)


def _format_cell_outputs(session_data: dict) -> str:
    """Extract human-readable cell outputs from the session JSON."""
    import html
    import json
    import re as _re

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
                match = _re.search(r"data-data='(.*?)'", html_content)
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
