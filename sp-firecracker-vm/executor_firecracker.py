"""
Firecracker executor — snapshot-accelerated microVM execution.

Used on Linux hosts where /dev/kvm is available. Boots a template VM once,
snapshots it with Python pre-loaded, then restores from snapshot for each
execution (~200ms vs ~1600ms cold boot).
"""

import asyncio
import http.client
import json
import logging
import os
import shutil
import socket
import subprocess
import time
import uuid

from executor_base import ExecutorBase

log = logging.getLogger("executor.firecracker")

# ─── Paths ───────────────────────────────────────────────────────────────────

KERNEL_PATH = "/opt/signalpilot/kernel/vmlinux.bin"
BASE_ROOTFS_PATH = "/opt/signalpilot/rootfs/sandbox-rootfs.ext4"
OVERLAYS_DIR = "/opt/signalpilot/overlays"
SOCKETS_DIR = "/opt/signalpilot/sockets"
SNAPSHOT_DIR = "/opt/signalpilot/snapshot"
SNAP_FILE = os.path.join(SNAPSHOT_DIR, "vm.snap")
MEM_FILE = os.path.join(SNAPSHOT_DIR, "vm.mem")


# ─── Firecracker Unix-socket API helpers ─────────────────────────────────────

class _UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP over a Unix domain socket (Firecracker API)."""

    def __init__(self, socket_path: str):
        super().__init__("localhost")
        self._socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self._socket_path)


def _fc_request(conn: _UnixHTTPConnection, method: str, path: str, body: dict) -> tuple[bool, str]:
    """Send a PUT/PATCH to the Firecracker API. Returns (ok, response_body)."""
    data = json.dumps(body)
    conn.request(method, path, body=data, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    resp_body = resp.read().decode()
    if resp.status >= 300:
        log.error("Firecracker API error: %s %s → %s %s", method, path, resp.status, resp_body)
        return False, resp_body
    return True, resp_body


def _fc_put(conn, path, body):
    return _fc_request(conn, "PUT", path, body)


def _fc_patch(conn, path, body):
    return _fc_request(conn, "PATCH", path, body)


def _wait_for_socket(path: str, timeout: float = 5.0) -> bool:
    """Block until a Unix socket file appears on disk."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.02)
    return False


# ─── Executor ────────────────────────────────────────────────────────────────

class FirecrackerExecutor(ExecutorBase):
    """Firecracker microVM executor with snapshot acceleration."""

    def __init__(self, max_vms: int, vm_memory_mb: int, vm_vcpus: int, vm_timeout_sec: int):
        self._max_vms = max_vms
        self._vm_memory_mb = vm_memory_mb
        self._vm_vcpus = vm_vcpus
        self._vm_timeout_sec = vm_timeout_sec
        self._active_vms: dict[str, dict] = {}
        self._snapshot_ready = False

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Create dirs and build snapshot."""
        for d in (SNAPSHOT_DIR, OVERLAYS_DIR, SOCKETS_DIR):
            os.makedirs(d, exist_ok=True)
        self._create_snapshot()

    def health(self) -> dict:
        return {
            "backend": "firecracker",
            "kvm_available": os.path.exists("/dev/kvm"),
            "snapshot_ready": self._snapshot_ready,
            "active_vms": len(self._active_vms),
            "max_vms": self._max_vms,
        }

    def cleanup_vm(self, vm_id: str) -> None:
        vm = self._active_vms.pop(vm_id, None)
        if vm is None:
            return
        proc = vm.get("process")
        if proc and proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        for key in ("socket_path", "overlay_path"):
            path = vm.get(key)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        log.info("VM %s cleaned up", vm_id)

    def list_vms(self) -> list[dict]:
        now = time.time()
        return [{"vm_id": k, "uptime_sec": now - v["started_at"]} for k, v in self._active_vms.items()]

    # ── Snapshot creation (runs once at startup) ──────────────────────────

    def _create_snapshot(self) -> None:
        """Boot a template VM, wait for Python readiness, snapshot it."""
        if os.path.exists(SNAP_FILE) and os.path.exists(MEM_FILE):
            log.info("Existing snapshot found, reusing")
            self._snapshot_ready = True
            return

        log.info("Creating template VM for snapshot...")
        sock_path = os.path.join(SOCKETS_DIR, "template.sock")
        log_path = "/tmp/fc_template.log"

        for f in (sock_path, log_path):
            if os.path.exists(f):
                os.remove(f)
        open(log_path, "w").close()

        proc = subprocess.Popen(
            ["/usr/local/bin/firecracker", "--api-sock", sock_path, "--log-path", log_path, "--level", "Info"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        if not _wait_for_socket(sock_path):
            log.error("Template Firecracker socket never appeared")
            proc.kill()
            return

        conn = _UnixHTTPConnection(sock_path)

        _fc_put(conn, "/boot-source", {
            "kernel_image_path": KERNEL_PATH,
            "boot_args": "console=ttyS0 reboot=k panic=1 pci=off init=/init",
        })
        _fc_put(conn, "/drives/rootfs", {
            "drive_id": "rootfs", "path_on_host": BASE_ROOTFS_PATH,
            "is_root_device": True, "is_read_only": False,
        })
        _fc_put(conn, "/machine-config", {"vcpu_count": self._vm_vcpus, "mem_size_mib": self._vm_memory_mb})

        start = time.monotonic()
        ok, _ = _fc_put(conn, "/actions", {"action_type": "InstanceStart"})
        if not ok:
            log.error("Failed to boot template VM")
            proc.kill()
            return

        log.info("Template VM booted in %.0fms, waiting for Python readiness...", (time.monotonic() - start) * 1000)

        ready = self._wait_for_ready_marker(proc, timeout_sec=30)
        if not ready:
            log.error("Template VM never became ready")
            proc.kill()
            return

        log.info("Template Python ready in %.0fms — creating snapshot", (time.monotonic() - start) * 1000)

        ok, _ = _fc_patch(conn, "/vm", {"state": "Paused"})
        if not ok:
            log.error("Failed to pause template VM")
            proc.kill()
            return

        ok, _ = _fc_put(conn, "/snapshot/create", {
            "snapshot_type": "Full", "snapshot_path": SNAP_FILE, "mem_file_path": MEM_FILE,
        })
        if not ok:
            log.error("Failed to create snapshot")
            proc.kill()
            return

        log.info("Snapshot created: state=%.0fKB mem=%.1fMB",
                 os.path.getsize(SNAP_FILE) / 1024, os.path.getsize(MEM_FILE) / (1024 * 1024))

        proc.kill()
        proc.wait()
        if os.path.exists(sock_path):
            os.remove(sock_path)

        self._snapshot_ready = True
        log.info("Snapshot ready — all subsequent executions will use restore")

    def _wait_for_ready_marker(self, proc: subprocess.Popen, timeout_sec: int) -> bool:
        """Read VM stdout until ===SP_READY=== appears."""
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            if line.decode("utf-8", errors="replace").strip() == "===SP_READY===":
                return True
        return False

    # ── Execution ────────────────────────────────────────────────────────

    async def execute(self, code: str, timeout: int) -> dict:
        if self._snapshot_ready:
            return await self._execute_snapshot(code, timeout)
        return await self._execute_cold(code, timeout)

    async def _execute_snapshot(self, code: str, timeout: int) -> dict:
        """Restore VM from snapshot, send code via serial, return result."""
        if len(self._active_vms) >= self._max_vms:
            raise RuntimeError(f"Max concurrent VMs ({self._max_vms}) reached")

        vm_id = str(uuid.uuid4())[:8]
        sock_path = os.path.join(SOCKETS_DIR, f"{vm_id}.sock")
        log_path = f"/tmp/fc_{vm_id}.log"
        overlay_path = os.path.join(OVERLAYS_DIR, f"{vm_id}.ext4")

        shutil.copy2(BASE_ROOTFS_PATH, overlay_path)
        for f in (sock_path, log_path):
            if os.path.exists(f):
                os.remove(f)
        open(log_path, "w").close()

        start_time = time.monotonic()

        proc = subprocess.Popen(
            ["/usr/local/bin/firecracker", "--api-sock", sock_path, "--log-path", log_path,
             "--level", "Info", "--id", vm_id],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self._active_vms[vm_id] = {
            "process": proc, "socket_path": sock_path,
            "overlay_path": overlay_path, "started_at": time.time(),
        }

        try:
            if not _wait_for_socket(sock_path):
                raise RuntimeError("Firecracker socket never appeared")

            conn = _UnixHTTPConnection(sock_path)

            ok, err = _fc_put(conn, "/snapshot/load", {
                "snapshot_path": SNAP_FILE,
                "mem_backend": {"backend_path": MEM_FILE, "backend_type": "File"},
                "enable_diff_snapshots": False,
            })
            if not ok:
                raise RuntimeError(f"Snapshot load failed: {err}")

            restore_ms = (time.monotonic() - start_time) * 1000

            ok, err = _fc_patch(conn, "/vm", {"state": "Resumed"})
            if not ok:
                raise RuntimeError(f"Resume failed: {err}")

            log.info("VM %s restored in %.0fms", vm_id, restore_ms)

            payload = code + "\n===SP_CODE_END===\n"
            try:
                proc.stdin.write(payload.encode())
                proc.stdin.flush()
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

            raw = await self._collect_output(proc, timeout)
            elapsed_ms = (time.monotonic() - start_time) * 1000
            return self._parse_serial_result(raw, vm_id, restore_ms, elapsed_ms)
        finally:
            self.cleanup_vm(vm_id)

    async def _execute_cold(self, code: str, timeout: int) -> dict:
        """Boot a fresh VM, inject code via rootfs, return result."""
        if len(self._active_vms) >= self._max_vms:
            raise RuntimeError(f"Max concurrent VMs ({self._max_vms}) reached")

        vm_id = str(uuid.uuid4())[:8]
        sock_path = os.path.join(SOCKETS_DIR, f"{vm_id}.sock")
        log_path = f"/tmp/fc_{vm_id}.log"
        overlay_path = os.path.join(OVERLAYS_DIR, f"{vm_id}.ext4")
        start_time = time.monotonic()

        shutil.copy2(BASE_ROOTFS_PATH, overlay_path)
        self._inject_code_into_rootfs(overlay_path, code)

        open(log_path, "w").close()
        proc = subprocess.Popen(
            ["/usr/local/bin/firecracker", "--api-sock", sock_path, "--log-path", log_path,
             "--level", "Info", "--id", vm_id],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self._active_vms[vm_id] = {
            "process": proc, "socket_path": sock_path,
            "overlay_path": overlay_path, "started_at": time.time(),
        }

        try:
            if not _wait_for_socket(sock_path):
                raise RuntimeError("Firecracker socket never appeared")

            conn = _UnixHTTPConnection(sock_path)
            _fc_put(conn, "/boot-source", {
                "kernel_image_path": KERNEL_PATH,
                "boot_args": "console=ttyS0 reboot=k panic=1 pci=off init=/init",
            })
            _fc_put(conn, "/drives/rootfs", {
                "drive_id": "rootfs", "path_on_host": overlay_path,
                "is_root_device": True, "is_read_only": False,
            })
            _fc_put(conn, "/machine-config", {"vcpu_count": self._vm_vcpus, "mem_size_mib": self._vm_memory_mb})

            boot_start = time.monotonic()
            _fc_put(conn, "/actions", {"action_type": "InstanceStart"})
            boot_ms = (time.monotonic() - boot_start) * 1000

            await self._wait_for_exit(proc, timeout)
            elapsed_ms = (time.monotonic() - start_time) * 1000

            result = self._read_result_from_rootfs(overlay_path)
            result["vm_id"] = vm_id
            result["boot_ms"] = boot_ms
            result["execution_ms"] = elapsed_ms
            return result
        finally:
            self.cleanup_vm(vm_id)

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _collect_output(self, proc: subprocess.Popen, timeout: int) -> str:
        """Read all stdout from a Firecracker process."""
        loop = asyncio.get_event_loop()

        def _read():
            try:
                stdout_bytes = proc.stdout.read()
                proc.wait(timeout=timeout)
                return stdout_bytes.decode("utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                return (proc.stdout.read() or b"").decode("utf-8", errors="replace")

        try:
            return await asyncio.wait_for(loop.run_in_executor(None, _read), timeout=timeout + 2)
        except asyncio.TimeoutError:
            return ""

    def _parse_serial_result(self, raw: str, vm_id: str, restore_ms: float, elapsed_ms: float) -> dict:
        """Extract JSON result from serial console output."""
        raw_clean = raw.replace("\r\n", "\n")
        if "===SP_RESULT_START===" in raw_clean and "===SP_RESULT_END===" in raw_clean:
            result_json = raw_clean.split("===SP_RESULT_START===\n", 1)[1].split("\n===SP_RESULT_END===", 1)[0].strip()
            try:
                result = json.loads(result_json)
                result["vm_id"] = vm_id
                result["restore_ms"] = restore_ms
                result["execution_ms"] = elapsed_ms
                return result
            except json.JSONDecodeError:
                pass

        return {
            "success": False, "output": "", "error": "Execution timed out or produced no result",
            "exit_code": -1, "vm_id": vm_id, "restore_ms": restore_ms, "execution_ms": elapsed_ms,
        }

    def _inject_code_into_rootfs(self, overlay_path: str, code: str) -> None:
        """Mount rootfs overlay, write code + init script, unmount."""
        mount_dir = f"/tmp/mount_{uuid.uuid4().hex[:8]}"
        os.makedirs(mount_dir, exist_ok=True)
        try:
            subprocess.run(["mount", "-o", "loop", overlay_path, mount_dir], check=True, capture_output=True)
            os.makedirs(os.path.join(mount_dir, "tmp", "output"), exist_ok=True)
            with open(os.path.join(mount_dir, "tmp", "user_code.py"), "w") as f:
                f.write(code)
            init_script = (
                "#!/bin/sh\n"
                "mount -t proc proc /proc 2>/dev/null\n"
                "mount -t sysfs sysfs /sys 2>/dev/null\n"
                "mount -t devtmpfs devtmpfs /dev 2>/dev/null\n"
                "/usr/bin/python3 /tmp/user_code.py > /tmp/output/stdout.txt 2> /tmp/output/stderr.txt\n"
                "echo $? > /tmp/output/exit_code.txt\n"
                "sync\n"
                "/bin/busybox reboot -f\n"
            )
            init_path = os.path.join(mount_dir, "init")
            with open(init_path, "w") as f:
                f.write(init_script)
            os.chmod(init_path, 0o755)
        finally:
            subprocess.run(["umount", mount_dir], check=False, capture_output=True)
            try:
                os.rmdir(mount_dir)
            except OSError:
                pass

    def _read_result_from_rootfs(self, overlay_path: str) -> dict:
        """Mount overlay read-only and extract execution results."""
        mount_dir = f"/tmp/read_{uuid.uuid4().hex[:8]}"
        os.makedirs(mount_dir, exist_ok=True)
        stdout = stderr = ""
        exit_code = -1
        try:
            subprocess.run(["mount", "-o", "loop,ro", overlay_path, mount_dir], check=True, capture_output=True)
            out_dir = os.path.join(mount_dir, "tmp", "output")
            for name, target in (("stdout.txt", "stdout"), ("stderr.txt", "stderr"), ("exit_code.txt", "exit_code")):
                path = os.path.join(out_dir, name)
                if not os.path.exists(path):
                    continue
                val = open(path).read()
                if target == "stdout":
                    stdout = val.rstrip()
                elif target == "stderr":
                    stderr = val.rstrip()
                elif target == "exit_code":
                    try:
                        exit_code = int(val.strip())
                    except ValueError:
                        pass
        finally:
            subprocess.run(["umount", mount_dir], check=False, capture_output=True)
            try:
                os.rmdir(mount_dir)
            except OSError:
                pass

        return {"success": exit_code == 0, "output": stdout, "error": stderr or None, "exit_code": exit_code}

    async def _wait_for_exit(self, proc: subprocess.Popen, timeout: int) -> None:
        """Wait for Firecracker process to exit within timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return
            await asyncio.sleep(0.1)
        proc.kill()
        proc.wait()
