"""
gVisor executor — user-space kernel sandbox via runsc.

Used on hosts without /dev/kvm (macOS Docker Desktop, CI, etc.).
Runs untrusted code inside a gVisor sandbox using `runsc do`, which
intercepts all syscalls through a user-space kernel (Sentry). No VM
boot required — startup is near-instant (~50ms).

gVisor is downloaded once at container build time (Dockerfile.gvisor).
"""

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid

from executor_base import ExecutorBase

log = logging.getLogger("executor.gvisor")

RUNSC_PATH = "/usr/local/bin/runsc"
PYTHON_PATH = os.getenv("SP_PYTHON_PATH", "/usr/local/bin/python3")

# Wrapper that executes user code and captures output as JSON.
# User code is injected via json.dumps() which escapes all special chars,
# then exec()'d inside gVisor's sandboxed kernel — no host access even if
# the escaping were bypassed.
_WRAPPER_TEMPLATE = '''
import io, json, sys, traceback

code = {code_json}

stdout_buf = io.StringIO()
stderr_buf = io.StringIO()
old_out, old_err = sys.stdout, sys.stderr
exit_code = 0

try:
    sys.stdout = stdout_buf
    sys.stderr = stderr_buf
    exec(compile(code, "<sandbox>", "exec"), {{"__builtins__": __builtins__}})
except SystemExit as e:
    exit_code = e.code if isinstance(e.code, int) else 1
except Exception:
    exit_code = 1
    traceback.print_exc(file=stderr_buf)
finally:
    sys.stdout = old_out
    sys.stderr = old_err

result = json.dumps({{
    "success": exit_code == 0,
    "output": stdout_buf.getvalue().rstrip("\\n"),
    "error": stderr_buf.getvalue().rstrip("\\n") or None,
    "exit_code": exit_code,
}})
print(result)
'''


class GVisorExecutor(ExecutorBase):
    """gVisor sandbox executor using runsc standalone mode."""

    def __init__(self, max_sandboxes: int, timeout_sec: int):
        self._max_sandboxes = max_sandboxes
        self._timeout_sec = timeout_sec
        self._active: dict[str, dict] = {}

    async def start(self) -> None:
        """Verify runsc binary is available and clean orphan temp dirs."""
        if not os.path.exists(RUNSC_PATH):
            raise RuntimeError(f"gVisor binary not found at {RUNSC_PATH}")
        self._cleanup_orphan_temps()
        log.info("gVisor executor ready (runsc at %s)", RUNSC_PATH)

    def _cleanup_orphan_temps(self) -> None:
        """Remove leftover /tmp/sp_gvisor_* dirs from prior crashes."""
        import glob
        for path in glob.glob("/tmp/sp_gvisor_*"):
            try:
                for f in os.listdir(path):
                    os.remove(os.path.join(path, f))
                os.rmdir(path)
            except OSError:
                pass

    def health(self) -> dict:
        return {
            "backend": "gvisor",
            "runsc_available": os.path.exists(RUNSC_PATH),
            "active_sandboxes": len(self._active),
            "max_sandboxes": self._max_sandboxes,
        }

    def cleanup_vm(self, vm_id: str) -> None:
        entry = self._active.pop(vm_id, None)
        if entry is None:
            return
        proc = entry.get("process")
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        log.info("Sandbox %s cleaned up", vm_id)

    def list_vms(self) -> list[dict]:
        now = time.time()
        return [{"vm_id": k, "uptime_sec": now - v["started_at"]} for k, v in self._active.items()]

    async def execute(self, code: str, timeout: int) -> dict:
        """Run code inside a gVisor sandbox via `runsc do`."""
        if len(self._active) >= self._max_sandboxes:
            raise RuntimeError(f"Max concurrent sandboxes ({self._max_sandboxes}) reached")

        vm_id = str(uuid.uuid4())[:8]
        start_time = time.monotonic()

        wrapper_code = _WRAPPER_TEMPLATE.format(code_json=json.dumps(code))

        tmp_dir = tempfile.mkdtemp(prefix=f"sp_gvisor_{vm_id}_")
        script_path = os.path.join(tmp_dir, "run.py")
        with open(script_path, "w") as f:
            f.write(wrapper_code)

        cmd = [
            RUNSC_PATH,
            "-ignore-cgroups",
            "do",
            "-quiet",
            "--",
            PYTHON_PATH, script_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._active[vm_id] = {"process": proc, "started_at": time.time(), "tmp_dir": tmp_dir}

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return self._timeout_result(vm_id, start_time)

            elapsed_ms = (time.monotonic() - start_time) * 1000
            return self._parse_result(stdout_bytes, stderr_bytes, vm_id, elapsed_ms)
        finally:
            self._active.pop(vm_id, None)
            self._cleanup_tmp(tmp_dir)

    def _parse_result(self, stdout_bytes: bytes, stderr_bytes: bytes, vm_id: str, elapsed_ms: float) -> dict:
        """Parse JSON result from the wrapper script's stdout."""
        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

        try:
            result = json.loads(stdout)
            result["vm_id"] = vm_id
            result["execution_ms"] = elapsed_ms
            return result
        except (json.JSONDecodeError, KeyError):
            return {
                "success": False, "output": stdout, "error": stderr or "Failed to parse result",
                "exit_code": -1, "vm_id": vm_id, "execution_ms": elapsed_ms,
            }

    def _timeout_result(self, vm_id: str, start_time: float) -> dict:
        """Build a result dict for a timed-out execution."""
        return {
            "success": False, "output": "", "error": "Execution timed out",
            "exit_code": -1, "vm_id": vm_id, "execution_ms": (time.monotonic() - start_time) * 1000,
        }

    def _cleanup_tmp(self, tmp_dir: str) -> None:
        """Remove the temporary script directory."""
        try:
            for f in os.listdir(tmp_dir):
                os.remove(os.path.join(tmp_dir, f))
            os.rmdir(tmp_dir)
        except OSError:
            pass
