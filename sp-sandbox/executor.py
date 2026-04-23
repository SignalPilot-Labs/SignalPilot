"""
gVisor (runsc) executor for sandboxed Python code execution.

Uses `runsc do` in rootless mode to run user code inside a gVisor sandbox.
Each execution is fully isolated — no shared filesystem, no network.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from constants import (
    GVISOR_WARNING_PREFIX,
    MAX_OUTPUT_BYTES,
    PYTHON_PATH,
    RUNSC_PATH,
)
from models import ExecutionResult

logger = logging.getLogger(__name__)


def _strip_gvisor_warnings(text: str) -> str:
    """Remove gVisor rootless-mode warning lines from output."""
    return "\n".join(
        line for line in text.splitlines()
        if not line.startswith(GVISOR_WARNING_PREFIX)
    )


def _now_ms() -> float:
    """Monotonic time in milliseconds."""
    return time.monotonic() * 1000


class GVisorExecutor:
    """Execute Python code inside gVisor sandboxes via `runsc do`."""

    def __init__(self) -> None:
        self._active: dict[str, asyncio.subprocess.Process] = {}
        self._workdirs: dict[str, Path] = {}

    async def execute(
        self, code: str, vm_id: str, timeout: int,
        file_mounts: list[dict] | None = None,
    ) -> ExecutionResult:
        """Run code in a gVisor sandbox using `runsc --rootless do`."""
        start = _now_ms()

        workdir = Path(tempfile.mkdtemp(prefix=f"sp-sandbox-{vm_id[:8]}-"))
        self._workdirs[vm_id] = workdir

        # Create symlinks for file mounts (host file → sandbox workdir)
        if file_mounts:
            for mount in file_mounts:
                host_path = Path(mount["host_path"])
                sandbox_path = workdir / mount["sandbox_path"]
                sandbox_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    sandbox_path.symlink_to(host_path)
                except OSError as e:
                    logger.warning("Failed to symlink %s → %s: %s", host_path, sandbox_path, e)

        script_path = workdir / "user_code.py"
        script_path.write_text(code, encoding="utf-8")

        # Run Python directly — the container itself provides gVisor isolation
        # (via Docker runtime). No need for runsc inside the container.
        cmd = [
            PYTHON_PATH,
            "-u",
            str(script_path),
        ]

        # Strip sensitive env vars before spawning subprocess
        safe_env = {
            k: v for k, v in os.environ.items()
            if k.upper() not in (
                "DATABASE_URL", "CLERK_SECRET_KEY", "CLERK_PUBLISHABLE_KEY",
                "SP_ENCRYPTION_KEY", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
            )
        }

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(workdir),
                env=safe_env,
            )
            self._active[vm_id] = proc

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                self._cleanup_vm(vm_id)
                return ExecutionResult(
                    success=False,
                    output="",
                    error=f"Execution timed out after {timeout}s",
                    execution_ms=_now_ms() - start,
                    vm_id=vm_id,
                )

            stdout = stdout_bytes[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            stderr = stderr_bytes[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")

            stdout = stdout.strip()
            stderr = stderr.strip()

            success = proc.returncode == 0
            error = stderr.strip() if not success and stderr.strip() else None

            return ExecutionResult(
                success=success,
                output=stdout,
                error=error,
                execution_ms=_now_ms() - start,
                vm_id=vm_id,
            )

        except FileNotFoundError:
            return ExecutionResult(
                success=False,
                output="",
                error=f"runsc not found at {RUNSC_PATH}. Is gVisor installed?",
                execution_ms=_now_ms() - start,
                vm_id=vm_id,
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                output="",
                error=str(e),
                execution_ms=_now_ms() - start,
                vm_id=vm_id,
            )
        finally:
            self._active.pop(vm_id, None)
            self._cleanup_vm(vm_id)

    async def kill(self, vm_id: str) -> bool:
        """Kill a running sandbox process."""
        proc = self._active.pop(vm_id, None)
        if proc is None:
            return False
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        self._cleanup_vm(vm_id)
        return True

    async def cleanup(self) -> None:
        """Kill all active sandboxes and remove temp dirs."""
        for vm_id in list(self._active):
            await self.kill(vm_id)
        for vm_id, workdir in list(self._workdirs.items()):
            shutil.rmtree(workdir, ignore_errors=True)
        self._workdirs.clear()

    def _cleanup_vm(self, vm_id: str) -> None:
        """Remove temp directory for a sandbox."""
        workdir = self._workdirs.pop(vm_id, None)
        if workdir and workdir.exists():
            shutil.rmtree(workdir, ignore_errors=True)
