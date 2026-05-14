"""Command execution HTTP handler for the sandbox.

Runs arbitrary subprocess commands in the sandbox container. gVisor isolates
the process; a small env filter strips AutoFyn-internal secrets before exec.
"""

import asyncio
import logging
import os
import re

from aiohttp import web

from constants import CMD_TIMEOUT, SECRET_ENV_VARS

logger = logging.getLogger("sandbox.endpoints.execute")

_STRIP_PATTERN = re.compile(SECRET_ENV_VARS) if SECRET_ENV_VARS else None


def _safe_env() -> dict[str, str]:
    """Copy os.environ, stripping AutoFyn-internal secrets.

    Project secrets (API keys etc.) are kept — the sandbox needs them
    to build and run the target project. Only our own credentials
    (GIT_TOKEN, CLAUDE_CODE_OAUTH_TOKEN, AGENT_INTERNAL_SECRET, etc.)
    are removed so the LLM cannot read them from the process env.
    """
    return {
        k: v
        for k, v in os.environ.items()
        if not (_STRIP_PATTERN and _STRIP_PATTERN.search(k))
    }


async def handle_execute(request: web.Request) -> web.Response:
    """Execute a command in the sandbox. Security is via gVisor isolation."""
    body = await request.json()
    args: list[str] = body.get("args", [])
    cwd: str = body.get("cwd", "/")
    timeout: int = body.get("timeout", CMD_TIMEOUT)
    extra_env: dict[str, str] = body.get("env", {})

    if not args:
        return web.json_response({"error": "args is required"}, status=400)

    env = _safe_env()
    env.update(extra_env)

    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return web.json_response(
            {
                "stdout": (stdout or b"").decode().strip(),
                "stderr": (stderr or b"").decode().strip(),
                "exit_code": proc.returncode or 0,
            }
        )
    except asyncio.TimeoutError:
        if proc:
            proc.kill()
        return web.json_response(
            {
                "stdout": "",
                "stderr": "Command timed out",
                "exit_code": -1,
            },
            status=408,
        )
    except FileNotFoundError:
        return web.json_response(
            {
                "stdout": "",
                "stderr": f"Command not found: {args[0]}",
                "exit_code": -1,
            },
            status=404,
        )


def register(app: web.Application) -> None:
    """Attach /execute route to the aiohttp app."""
    app.router.add_post("/execute", handle_execute)
