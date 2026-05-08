"""KernelSession — wraps one ipykernel subprocess with jupyter_client/ZMQ."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from jupyter_client import AsyncKernelManager
from models import CellResult

logger = logging.getLogger(__name__)

_SENSITIVE_VARS = frozenset({
    "DATABASE_URL", "CLERK_SECRET_KEY", "CLERK_PUBLISHABLE_KEY",
    "SP_ENCRYPTION_KEY", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
})

KERNEL_EXEC_PATH = os.environ.get("KERNEL_EXEC_PATH", "/opt/signalpilot/kernel_exec.sh")


class SPKernelManager(AsyncKernelManager):
    """KernelManager that chmods the connection file for privilege-dropped kernels."""

    def write_connection_file(self, **kwargs):
        super().write_connection_file(**kwargs)
        try:
            os.chmod(self.connection_file, 0o644)
        except OSError:
            pass


class KernelSession:
    """Wraps a single ipykernel subprocess via jupyter_client."""

    def __init__(self, session_id: str, workdir: Path):
        self.id = session_id
        self.workdir = workdir
        self._km: SPKernelManager | None = None
        self._kc = None
        self._lock = asyncio.Lock()
        self.history: list[CellResult] = []
        self.created_at = time.time()
        self.last_active = time.time()
        self.status = "starting"
        self._execution_count = 0

    async def start(self) -> None:
        self._km = SPKernelManager(kernel_name="python3")
        self._km.connection_file = f"/tmp/sp-kernel-{self.id[:8]}.json"

        safe_env = {
            k: v for k, v in os.environ.items()
            if k.upper() not in _SENSITIVE_VARS
        }
        safe_env["TMPDIR"] = "/tmp"
        safe_env["MPLBACKEND"] = "agg"

        if os.path.isfile(KERNEL_EXEC_PATH):
            self._km.kernel_cmd = [
                KERNEL_EXEC_PATH, sys.executable, "-m", "ipykernel_launcher",
                "-f", "{connection_file}",
            ]

        await self._km.start_kernel(cwd=str(self.workdir), env=safe_env)
        self._kc = self._km.client()
        self._kc.start_channels()

        try:
            await self._kc.wait_for_ready(timeout=30)
        except Exception:
            await self._force_kill()
            raise RuntimeError("Kernel failed to start")

        self.status = "idle"
        logger.info(
            "kernel session %s started (ipykernel, pid=%s)",
            self.id[:8], self._km.provisioner.pid if self._km.provisioner else "?",
        )

    async def execute(self, code: str, timeout: int = 30, cell_id: str | None = None) -> CellResult:
        if self.status == "dead":
            raise RuntimeError("Session is dead")

        async with self._lock:
            self.status = "running"
            start = time.monotonic()

            msg_id = self._kc.execute(code, allow_stdin=False)

            outputs: list[dict] = []
            error = None
            success = True

            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(
                            self._kc.get_iopub_msg(), timeout=timeout + 5,
                        )
                    except asyncio.TimeoutError:
                        self.status = "dead"
                        await self._force_kill()
                        return CellResult(
                            success=False, output="", outputs=[],
                            error=f"Cell timed out after {timeout}s",
                            execution_ms=(time.monotonic() - start) * 1000,
                            cell_id=cell_id,
                        )

                    if msg["parent_header"].get("msg_id") != msg_id:
                        continue

                    msg_type = msg["header"]["msg_type"]
                    content = msg["content"]

                    if msg_type == "stream":
                        outputs.append({
                            "type": "stream",
                            "name": content.get("name", "stdout"),
                            "text": content.get("text", ""),
                        })
                    elif msg_type == "execute_result":
                        self._execution_count = content.get(
                            "execution_count", self._execution_count + 1,
                        )
                        outputs.append({
                            "type": "execute_result",
                            "data": content.get("data", {}),
                            "metadata": content.get("metadata", {}),
                            "execution_count": self._execution_count,
                        })
                    elif msg_type == "display_data":
                        outputs.append({
                            "type": "display_data",
                            "data": content.get("data", {}),
                            "metadata": content.get("metadata", {}),
                        })
                    elif msg_type == "update_display_data":
                        outputs.append({
                            "type": "update_display_data",
                            "data": content.get("data", {}),
                            "metadata": content.get("metadata", {}),
                            "transient": content.get("transient", {}),
                        })
                    elif msg_type == "error":
                        success = False
                        tb = content.get("traceback", [])
                        error = "\n".join(tb) if tb else content.get("evalue", "")
                        outputs.append({
                            "type": "error",
                            "ename": content.get("ename", "Error"),
                            "evalue": content.get("evalue", ""),
                            "traceback": tb,
                        })
                    elif (
                        msg_type == "status"
                        and content.get("execution_state") == "idle"
                    ):
                        break

                reply = await asyncio.wait_for(self._kc.get_shell_msg(), timeout=5)
                if reply["content"].get("status") != "ok" and error is None:
                    success = False

            except asyncio.TimeoutError:
                self.status = "dead"
                await self._force_kill()
                return CellResult(
                    success=False, output="", outputs=outputs,
                    error=f"Cell timed out after {timeout}s",
                    execution_ms=(time.monotonic() - start) * 1000,
                    cell_id=cell_id,
                )
            except Exception as e:
                self.status = "dead"
                return CellResult(
                    success=False, output="", outputs=outputs,
                    error=str(e),
                    execution_ms=(time.monotonic() - start) * 1000,
                    cell_id=cell_id,
                )

            elapsed_ms = (time.monotonic() - start) * 1000

            text_parts = [o["text"] for o in outputs if o["type"] == "stream"]
            text_output = "".join(text_parts)
            if not text_output:
                for o in outputs:
                    if o["type"] == "execute_result":
                        text_output = o.get("data", {}).get("text/plain", "")
                        break

            result = CellResult(
                success=success,
                output=text_output,
                outputs=outputs,
                error=error,
                execution_ms=elapsed_ms,
                cell_id=cell_id,
                execution_count=self._execution_count,
            )
            self.history.append(result)
            self.last_active = time.time()
            self.status = "idle"
            return result

    async def inject_bootstrap(self, code: str) -> CellResult:
        """Execute bootstrap code silently (not added to user history)."""
        if self.status == "dead":
            raise RuntimeError("Session is dead")

        async with self._lock:
            self.status = "running"
            start = time.monotonic()
            msg_id = self._kc.execute(code, silent=True, store_history=False)

            try:
                while True:
                    msg = await asyncio.wait_for(
                        self._kc.get_iopub_msg(), timeout=15,
                    )
                    if msg["parent_header"].get("msg_id") != msg_id:
                        continue
                    if msg["header"]["msg_type"] == "error":
                        self.status = "idle"
                        evalue = msg["content"].get("evalue", "unknown")
                        raise RuntimeError(f"Bootstrap failed: {evalue}")
                    if (
                        msg["header"]["msg_type"] == "status"
                        and msg["content"].get("execution_state") == "idle"
                    ):
                        break

                reply = await asyncio.wait_for(
                    self._kc.get_shell_msg(), timeout=5,
                )
                if reply["content"].get("status") != "ok":
                    self.status = "idle"
                    raise RuntimeError("Bootstrap execution failed")

            except asyncio.TimeoutError:
                self.status = "dead"
                await self._force_kill()
                raise RuntimeError("Bootstrap timed out")

            self.status = "idle"
            return CellResult(
                success=True, output="", error=None,
                execution_ms=(time.monotonic() - start) * 1000,
                cell_id="__bootstrap__",
            )

    async def complete(self, code: str, cursor_pos: int) -> dict:
        """Request tab completion from IPython."""
        if self.status == "dead" or not self._kc:
            return {"matches": [], "cursor_start": cursor_pos, "cursor_end": cursor_pos}

        msg_id = self._kc.complete(code, cursor_pos)
        reply = await asyncio.wait_for(self._kc.get_shell_msg(), timeout=5)
        content = reply.get("content", {})
        return {
            "matches": content.get("matches", []),
            "cursor_start": content.get("cursor_start", cursor_pos),
            "cursor_end": content.get("cursor_end", cursor_pos),
            "metadata": content.get("metadata", {}),
        }

    async def inspect(self, code: str, cursor_pos: int, detail_level: int = 0) -> dict:
        """Request object inspection from IPython."""
        if self.status == "dead" or not self._kc:
            return {"found": False, "data": {}, "metadata": {}}

        msg_id = self._kc.inspect(code, cursor_pos, detail_level=detail_level)
        reply = await asyncio.wait_for(self._kc.get_shell_msg(), timeout=5)
        content = reply.get("content", {})
        return {
            "found": content.get("found", False),
            "data": content.get("data", {}),
            "metadata": content.get("metadata", {}),
        }

    async def interrupt(self) -> None:
        """Interrupt the running kernel."""
        if self._km and self._km.is_alive():
            await self._km.interrupt_kernel()

    async def kill(self) -> None:
        await self._force_kill()
        if self.workdir.exists():
            shutil.rmtree(self.workdir, ignore_errors=True)
        logger.info("kernel session %s killed", self.id[:8])

    @property
    def cell_count(self) -> int:
        return len(self.history)

    @property
    def is_alive(self) -> bool:
        return (
            self._km is not None
            and self._km.is_alive()
            and self.status != "dead"
        )

    async def _force_kill(self) -> None:
        self.status = "dead"
        if self._kc:
            self._kc.stop_channels()
            self._kc = None
        if self._km and self._km.is_alive():
            try:
                await self._km.shutdown_kernel(now=True)
            except Exception:
                pass
