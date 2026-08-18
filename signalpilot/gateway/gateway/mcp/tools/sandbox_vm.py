"""Sandbox VM tools for automated improvement runs.

These tools give an improvement-run agent a disposable Linux VM (via the
configured sandbox runtime provider) to load and compile the dbt project in.
They are capability-gated: the session JWT must carry "sandbox:execute",
which the gateway mints only for improvement runs — ordinary standalone
chats never receive it.

One sandbox exists per execution identity (one per run), created lazily on
first use and destroyed by the improvement runner / provider time limit.
"""

from __future__ import annotations

import asyncio

from gateway.config.sandbox_runtime import get_sandbox_runtime_settings
from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import (
    mcp_capabilities_var,
    mcp_execution_identity_var,
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
    """Fail closed unless the caller's JWT carries the sandbox capability."""
    capabilities = mcp_capabilities_var.get(None) or []
    if SANDBOX_CAPABILITY not in capabilities:
        return "Error: sandbox tools are only available to automated improvement runs"
    if not (mcp_execution_identity_var.get(None) or "").startswith("chat:"):
        return "Error: sandbox tools require a run execution identity"
    return None


async def _sandbox_for_session() -> str:
    """Return the current run's sandbox id, creating the sandbox on first use."""
    identity = mcp_execution_identity_var.get(None) or ""
    async with _session_lock:
        sandbox_id = _session_sandboxes.get(identity)
        if sandbox_id:
            return sandbox_id
        runtime = get_sandbox_runtime()
        settings = get_sandbox_runtime_settings()
        sandbox_id = await runtime.create(
            SandboxSpec(
                time_limit_seconds=settings.time_limit_seconds,
                tags={"sp_execution_identity": identity, "sp_purpose": "improvement-run"},
            )
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

    The sandbox is a disposable Linux VM (Python 3, node, uv, pip, git
    preinstalled) created on first use and destroyed when the run ends.
    Use it to clone the dbt project, install dbt, and run `dbt parse` /
    `dbt compile`. It has no access to gateway secrets or the warehouse.

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
