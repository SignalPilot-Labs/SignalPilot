"""Sandbox VM tools for chat and improvement-run agents.

These tools give the agent a disposable Linux VM (via the configured sandbox
runtime provider) to explore, edit, and compile the dbt project in. They are
capability-gated: the session JWT must carry "sandbox:execute" — minted for
improvement runs always, and for user chats when SP_FEATURE_CHAT_SANDBOX_RUNTIME
is on.

Chat sandboxes are SEEDED: created from the pinned notebook image (dbt
preinstalled) and hydrated with the project's branch snapshot at /workspace,
plus a stub duckdb profile at /tmp/sp-profiles so `dbt deps/parse/compile`
work immediately. The sandbox NEVER holds warehouse credentials — connected
dbt commands go through the separate dbt_execute tool/executor.

One sandbox exists per execution identity (one per run), created lazily on
first use and destroyed by the run teardown / provider time limit.
"""

from __future__ import annotations

import asyncio

from gateway.config.notebooks import get_notebook_settings
from gateway.config.sandbox_runtime import get_sandbox_runtime_settings
from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import (
    _store_session,
    mcp_branch_var,
    mcp_capabilities_var,
    mcp_execution_identity_var,
    mcp_org_id_var,
    mcp_project_id_var,
)
from gateway.mcp.server import mcp
from gateway.sandbox_runtime import SandboxRuntimeError, SandboxSpec, get_sandbox_runtime

SANDBOX_CAPABILITY = "sandbox:execute"

_MAX_COMMAND_LENGTH = 20_000
_MAX_WRITE_BYTES = 5_000_000
_MAX_READ_BYTES = 2_000_000
_MAX_OUTPUT_CHARS = 30_000
_DEFAULT_EXEC_TIMEOUT = 300.0

# One sandbox per execution identity for the lifetime of this process.
_session_sandboxes: dict[str, str] = {}
_session_lock = asyncio.Lock()


def _sandbox_denial() -> str | None:
    """Fail closed unless the caller's JWT carries the sandbox capability.

    Only agent identities (chat:*) are accepted — the dbt EXECUTOR sandboxes
    (chat-exec:*) are gateway-driven and must stay unreachable from agents.
    """
    capabilities = mcp_capabilities_var.get(None) or []
    if SANDBOX_CAPABILITY not in capabilities:
        return "Error: sandbox tools are not enabled for this session"
    identity = mcp_execution_identity_var.get(None) or ""
    if not identity.startswith("chat:") or identity.startswith("chat-exec:"):
        return "Error: sandbox tools require a run execution identity"
    return None


async def _seed_project(runtime, sandbox_id: str) -> None:
    """Hydrate /workspace from the branch snapshot + write the stub profile.

    Best-effort: seeding failure leaves a blank sandbox (the agent can still
    work); it must never block sandbox availability."""
    project_id = mcp_project_id_var.get(None)
    org_id = mcp_org_id_var.get(None)
    branch = mcp_branch_var.get(None) or "main"
    if not project_id or not org_id:
        return
    from gateway.workspace_store import workspace_object_storage
    from gateway.workspace_store.store import WorkspaceStore

    storage = workspace_object_storage()
    if not storage.enabled:
        return
    async with _store_session() as store:
        ws = WorkspaceStore(storage)
        _, snap_key = await ws.build_snapshot(
            store.session, org_id=org_id, project_id=project_id, branch=branch
        )
        snapshot_url = await storage.presign_get(snap_key, expires_seconds=3600)
    stub = (
        "import yaml, pathlib, glob\n"
        "candidates = glob.glob('/workspace/**/dbt_project.yml', recursive=True)\n"
        "profile = 'default'\n"
        "if candidates:\n"
        "    proj = yaml.safe_load(pathlib.Path(sorted(candidates, key=len)[0]).read_text()) or {}\n"
        "    profile = proj.get('profile') or proj.get('name') or 'default'\n"
        "stub = {profile: {'target': 'sp', 'outputs': {'sp': {\n"
        "    'type': 'duckdb', 'path': '/tmp/sp-parse.duckdb', 'threads': 1}}}}\n"
        "out = pathlib.Path('/tmp/sp-profiles'); out.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'profiles.yml').write_text(yaml.safe_dump(stub))\n"
    )
    result = await runtime.exec(
        sandbox_id,
        "set -e; "
        'export PATH="/opt/sp-notebook/.venv/bin:$PATH"; '
        # Image runs as root without `sudo`; create /workspace directly.
        "mkdir -p /workspace 2>/dev/null || sudo mkdir -p /workspace; "
        'curl -fsSL "$SP_SNAPSHOT_URL" | tar xz -C /workspace; '
        f"python - <<'SP_EOF'\n{stub}\nSP_EOF",
        env={"SP_SNAPSHOT_URL": snapshot_url},
        timeout_seconds=300,
    )
    if not result.ok:
        raise SandboxRuntimeError(f"seed failed: {result.stderr[-300:]}")


async def _sandbox_for_session() -> str:
    """Return the current run's sandbox id, creating (and for chat identities,
    seeding with the project) on first use."""
    identity = mcp_execution_identity_var.get(None) or ""
    async with _session_lock:
        sandbox_id = _session_sandboxes.get(identity)
        if sandbox_id:
            return sandbox_id
        runtime = get_sandbox_runtime()
        settings = get_sandbox_runtime_settings()
        image = get_notebook_settings().vercel_image or None
        sandbox_id = await runtime.create(
            SandboxSpec(
                time_limit_seconds=settings.time_limit_seconds,
                image=image,
                tags={"sp_execution_identity": identity, "sp_purpose": "agent-sandbox"},
            )
        )
        try:
            await _seed_project(runtime, sandbox_id)
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "sandbox seeding failed for %s; continuing blank", identity, exc_info=True
            )
        _session_sandboxes[identity] = sandbox_id
        return sandbox_id


async def release_session_sandbox(execution_identity: str) -> None:
    """Destroy and forget the sandbox bound to one run, if any."""
    async with _session_lock:
        sandbox_id = _session_sandboxes.pop(execution_identity, None)
    if sandbox_id:
        try:
            await get_sandbox_runtime().destroy(sandbox_id)
        except SandboxRuntimeError:
            pass


def _clip(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


@audited_tool(mcp)
async def sandbox_exec(command: str, cwd: str = "", timeout_seconds: int = 0) -> str:
    """
    Run a shell command inside this run's isolated sandbox VM.

    The sandbox is a disposable Linux VM created on first use and destroyed
    when the run ends. The dbt project is pre-seeded at /workspace and dbt is
    preinstalled (PATH includes /opt/sp-notebook/.venv/bin); a stub profile at
    /tmp/sp-profiles supports `dbt deps` / `dbt parse` / `dbt compile`
    immediately. It has NO warehouse credentials — use the dbt_execute tool
    for warehouse-connected commands (run/test/build).

    Args:
        command: Shell command to run (bash -c).
        cwd: Working directory inside the sandbox (optional).
        timeout_seconds: Kill the command after this many seconds (default 300).
    """
    if denial := _sandbox_denial():
        return denial
    if not command.strip():
        return "Error: command is required"
    if len(command) > _MAX_COMMAND_LENGTH:
        return f"Error: command exceeds {_MAX_COMMAND_LENGTH} characters"
    timeout = float(timeout_seconds) if timeout_seconds and timeout_seconds > 0 else _DEFAULT_EXEC_TIMEOUT
    try:
        sandbox_id = await _sandbox_for_session()
        runtime = get_sandbox_runtime()
        result = await runtime.exec(
            sandbox_id,
            command,
            cwd=cwd or None,
            timeout_seconds=timeout,
        )
    except SandboxRuntimeError as exc:
        return f"Error: {sanitize_mcp_error(str(exc))}"
    except Exception as exc:  # provider/transport errors must never leak internals
        return f"Error executing in sandbox: {sanitize_mcp_error(str(exc))}"
    # Format parsed by standalone_chat/tool_projection/ops.py; update tests there if you change this
    sections = [f"exit_code: {result.returncode}"]
    if result.stdout:
        sections.append(f"stdout:\n{_clip(result.stdout)}")
    if result.stderr:
        sections.append(f"stderr:\n{_clip(result.stderr)}")
    return "\n".join(sections)


@audited_tool(mcp)
async def sandbox_write_file(path: str, content: str) -> str:
    """
    Write a text file into this run's sandbox VM.

    Args:
        path: Absolute path inside the sandbox (e.g. /work/profiles.yml).
        content: File content (UTF-8 text).
    """
    if denial := _sandbox_denial():
        return denial
    if not path.startswith("/"):
        return "Error: path must be absolute"
    data = content.encode("utf-8")
    if len(data) > _MAX_WRITE_BYTES:
        return f"Error: content exceeds {_MAX_WRITE_BYTES} bytes"
    try:
        sandbox_id = await _sandbox_for_session()
        await get_sandbox_runtime().write_file(sandbox_id, path, data)
    except SandboxRuntimeError as exc:
        return f"Error: {sanitize_mcp_error(str(exc))}"
    except Exception as exc:
        return f"Error writing file: {sanitize_mcp_error(str(exc))}"
    return f"Wrote {len(data)} bytes to {path}"


@audited_tool(mcp)
async def sandbox_read_file(path: str) -> str:
    """
    Read a text file from this run's sandbox VM.

    Args:
        path: Absolute path inside the sandbox.
    """
    if denial := _sandbox_denial():
        return denial
    if not path.startswith("/"):
        return "Error: path must be absolute"
    try:
        sandbox_id = await _sandbox_for_session()
        data = await get_sandbox_runtime().read_file(sandbox_id, path)
    except SandboxRuntimeError as exc:
        return f"Error: {sanitize_mcp_error(str(exc))}"
    except Exception as exc:
        return f"Error reading file: {sanitize_mcp_error(str(exc))}"
    if data is None:
        return f"Error: {path} does not exist in the sandbox"
    if len(data) > _MAX_READ_BYTES:
        return f"Error: file exceeds {_MAX_READ_BYTES} bytes"
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return f"Error: {path} is not UTF-8 text ({len(data)} bytes)"
