"""Manages multiple concurrent agent runs via sibling Docker containers."""

import asyncio
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx


MAX_CONCURRENT = 10

SIGNAL_ENDPOINTS: dict[str, str] = {
    "stop": "stop",
    "pause": "pause",
    "resume": "resume_signal",
    "inject": "inject",
    "unlock": "unlock",
    "kill": "kill",
}

PASSTHROUGH_ENV_VARS = [
    "AGENT_MODEL",
    "AGENT_FALLBACK_MODEL",
    "SP_BENCHMARK_DIR",
    "SP_GATEWAY_URL",
]


@dataclass
class RunSlot:
    run_id: str | None = None
    container_id: str = ""
    container_name: str = ""
    status: str = "starting"  # starting, running, completed, stopped, error, killed
    prompt: str | None = None
    max_budget_usd: float = 0
    duration_minutes: float = 0
    base_branch: str = "main"
    started_at: float = field(default_factory=time.time)
    error_message: str | None = None
    volume_name: str = ""  # per-worker repo volume for cleanup


ALLOWED_CREDENTIAL_KEYS = {"claude_token", "git_token", "github_repo"}


class RunManager:
    def __init__(self) -> None:
        self.slots: dict[str, RunSlot] = {}
        self._env_cache: dict[str, Any] | None = None
        self._start_lock = asyncio.Lock()

    def _detect_environment(self) -> dict[str, Any]:
        """Auto-detect image, network, and mounts from the current container."""
        if self._env_cache is not None:
            return self._env_cache

        hostname = os.uname().nodename
        result = self._run_docker(["inspect", hostname])

        import json
        info = json.loads(result)[0]
        image = info["Config"]["Image"]
        networks = info["NetworkSettings"]["Networks"]
        network = next(iter(networks.keys()), "bridge")

        raw_mounts = info.get("Mounts", [])
        mounts: list[dict[str, str]] = []
        for m in raw_mounts:
            src = m.get("Source") or m.get("Name", "")
            dst = m.get("Destination", "")
            mode = m.get("Mode", "rw") or "rw"
            if src and dst:
                mounts.append({"source": src, "destination": dst, "mode": mode})

        self._env_cache = {
            "image": image,
            "network": network,
            "mounts": mounts,
        }
        print(f"[run_manager] Detected image={image} network={network} mounts={len(mounts)}")
        return self._env_cache

    def _build_worker_mounts(self, worker_id: str) -> list[str]:
        """Build -v flags for a worker. /home/agentuser/repo gets a per-worker volume."""
        env = self._detect_environment()
        flags: list[str] = []

        repo_volume = f"improve-worker-repo-{worker_id}"
        repo_dst = "/home/agentuser/repo"

        repo_handled = False
        for mount in env["mounts"]:
            dst = mount["destination"]
            if dst == repo_dst:
                flags += ["-v", f"{repo_volume}:{dst}"]
                repo_handled = True
            else:
                src = mount["source"]
                mode = mount.get("mode", "rw")
                flags += ["-v", f"{src}:{dst}:{mode}"]

        if not repo_handled:
            flags += ["-v", f"{repo_volume}:{repo_dst}"]

        return flags

    def _run_docker(self, args: list[str], timeout: int = 30) -> str:
        """Run a docker CLI command. Returns stdout, raises on error."""
        result = subprocess.run(
            ["docker"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"[run_manager] docker {args[0]} failed: {result.stderr.strip()}"
            )
        return result.stdout.strip()

    def active_count(self) -> int:
        return sum(1 for s in self.slots.values() if s.status in ("starting", "running"))

    def get_all_slots(self) -> list[RunSlot]:
        return list(self.slots.values())

    def get_slot(self, container_name: str) -> RunSlot | None:
        return self.slots.get(container_name)

    def get_slot_by_run_id(self, run_id: str) -> RunSlot | None:
        for s in self.slots.values():
            if s.run_id == run_id:
                return s
        return None

    @staticmethod
    def to_dict(slot: RunSlot) -> dict[str, Any]:
        return {
            "run_id": slot.run_id,
            "container_id": slot.container_id,
            "container_name": slot.container_name,
            "status": slot.status,
            "prompt": slot.prompt,
            "max_budget_usd": slot.max_budget_usd,
            "duration_minutes": slot.duration_minutes,
            "base_branch": slot.base_branch,
            "started_at": slot.started_at,
            "error_message": slot.error_message,
            "volume_name": slot.volume_name,
        }

    async def start_run(
        self,
        prompt: str | None,
        max_budget_usd: float,
        duration_minutes: float,
        base_branch: str,
        credentials: dict[str, str],
    ) -> RunSlot:
        # Filter credentials to allowed keys only (prevent injection)
        safe_creds = {k: v for k, v in credentials.items() if k in ALLOWED_CREDENTIAL_KEYS}

        async with self._start_lock:
            if self.active_count() >= MAX_CONCURRENT:
                raise RuntimeError(
                    f"[run_manager] Max concurrent runs ({MAX_CONCURRENT}) reached"
                )

            worker_id = uuid.uuid4().hex[:8]
            container_name = f"improve-worker-{worker_id}"

            # Reserve the slot immediately to prevent TOCTOU races
            volume_name = f"improve-worker-repo-{worker_id}"
            slot = RunSlot(
                container_name=container_name,
                status="starting",
                prompt=prompt,
                max_budget_usd=max_budget_usd,
                duration_minutes=duration_minutes,
                base_branch=base_branch,
                volume_name=volume_name,
            )
            self.slots[container_name] = slot

        env = self._detect_environment()
        mount_flags = self._build_worker_mounts(worker_id)

        # Pass credentials as env vars so they're available from container start
        env_flags: list[str] = [
            "-e", "GIT_TERMINAL_PROMPT=0",
            "-e", "DB_PATH=/data/improve.db",
        ]
        if safe_creds.get("claude_token"):
            env_flags += ["-e", f"CLAUDE_CODE_OAUTH_TOKEN={safe_creds['claude_token']}"]
        if safe_creds.get("git_token"):
            env_flags += ["-e", f"GIT_TOKEN={safe_creds['git_token']}"]
        if safe_creds.get("github_repo"):
            env_flags += ["-e", f"GITHUB_REPO={safe_creds['github_repo']}"]
        for key in PASSTHROUGH_ENV_VARS:
            val = os.environ.get(key)
            if val:
                env_flags += ["-e", f"{key}={val}"]

        docker_args = (
            ["run", "-d",
             "--name", container_name,
             "--network", env["network"],
             "--restart", "no",
             "--add-host", "host.docker.internal:host-gateway"]
            + mount_flags
            + env_flags
            + [env["image"]]
        )

        try:
            container_id = self._run_docker(docker_args)
        except Exception as e:
            slot.status = "error"
            slot.error_message = str(e)
            raise
        slot.container_id = container_id[:12]
        print(f"[run_manager] Started container {container_name} ({container_id[:12]})")

        try:
            await self._wait_for_health(container_name)
        except Exception as e:
            slot.status = "error"
            slot.error_message = f"Health check failed: {e}"
            self.cleanup_container(container_name)
            raise

        slot.status = "running"

        # Send start request — credentials also passed via env vars above,
        # but the /start endpoint uses them from the POST body to set os.environ
        run_config = {
            "prompt": prompt,
            "max_budget_usd": max_budget_usd,
            "duration_minutes": duration_minutes,
            "base_branch": base_branch,
            **safe_creds,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"http://{container_name}:8500/start", json=run_config
            )
            resp.raise_for_status()
            data = resp.json()

        slot.run_id = data.get("run_id")
        print(f"[run_manager] Worker {container_name} started run_id={slot.run_id}")

        task = asyncio.create_task(self._monitor_worker(container_name))
        task.add_done_callback(self._on_monitor_done)
        return slot

    def _on_monitor_done(self, task: asyncio.Task) -> None:
        """Log any unhandled exception from a monitor task."""
        try:
            exc = task.exception()
            if exc:
                print(f"[run_manager] Monitor task failed: {exc}")
        except asyncio.CancelledError:
            pass

    async def _wait_for_health(self, container_name: str, timeout: int = 120) -> None:
        deadline = time.time() + timeout
        async with httpx.AsyncClient(timeout=5) as client:
            while time.time() < deadline:
                try:
                    resp = await client.get(f"http://{container_name}:8500/health")
                    if resp.status_code == 200:
                        print(f"[run_manager] {container_name} healthy")
                        return
                except Exception:
                    pass
                await asyncio.sleep(2)
        raise TimeoutError(
            f"[run_manager] {container_name} did not become healthy within {timeout}s"
        )

    async def _monitor_worker(self, container_name: str) -> None:
        slot = self.slots.get(container_name)
        if not slot:
            return

        try:
            print(f"[run_manager] Monitoring {container_name}")
            async with httpx.AsyncClient(timeout=10) as client:
                while slot.status in ("starting", "running"):
                    await asyncio.sleep(10)
                    try:
                        state = self._run_docker(
                            ["inspect", "--format", "{{.State.Status}}", container_name],
                            timeout=10,
                        )
                        if state not in ("running", "created"):
                            print(f"[run_manager] {container_name} exited (state={state})")
                            slot.status = "completed"
                            break
                    except Exception as e:
                        print(f"[run_manager] inspect error for {container_name}: {e}")
                        slot.status = "error"
                        slot.error_message = str(e)
                        break

                    try:
                        resp = await client.get(f"http://{container_name}:8500/health")
                        if resp.status_code == 200:
                            health = resp.json()
                            if health.get("status") == "idle" and slot.status == "running":
                                print(f"[run_manager] {container_name} idle — marking completed")
                                slot.status = "completed"
                                break
                    except Exception:
                        pass
        except Exception as e:
            print(f"[run_manager] Monitor crashed for {container_name}: {e}")
            if slot.status in ("starting", "running"):
                slot.status = "error"
                slot.error_message = f"Monitor failed: {e}"

        print(f"[run_manager] Monitor done for {container_name}: status={slot.status}")

    async def send_signal(
        self,
        container_name: str,
        signal: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        endpoint = SIGNAL_ENDPOINTS.get(signal)
        if endpoint is None:
            raise ValueError(f"Unknown signal: {signal!r}. Valid: {list(SIGNAL_ENDPOINTS)}")
        url = f"http://{container_name}:8500/{endpoint}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload or {})
            resp.raise_for_status()
            return resp.json()

    async def stop_run(self, container_name: str, reason: str) -> dict[str, Any]:
        slot = self.slots.get(container_name)
        result = await self.send_signal(container_name, "stop", {"reason": reason})
        if slot:
            slot.status = "stopped"
        return result

    async def kill_run(self, container_name: str) -> dict[str, Any]:
        slot = self.slots.get(container_name)
        try:
            result = await self.send_signal(container_name, "kill")
        except Exception as e:
            print(f"[run_manager] kill signal failed for {container_name}: {e}")
            result = {"ok": False, "error": str(e)}
        if slot:
            slot.status = "killed"
        self.cleanup_container(container_name)
        return result

    async def pause_run(self, container_name: str) -> dict[str, Any]:
        return await self.send_signal(container_name, "pause")

    async def resume_run(self, container_name: str) -> dict[str, Any]:
        return await self.send_signal(container_name, "resume")

    async def inject_prompt(
        self, container_name: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.send_signal(container_name, "inject", payload)

    async def unlock_run(self, container_name: str) -> dict[str, Any]:
        return await self.send_signal(container_name, "unlock")

    async def get_worker_health(self, container_name: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"http://{container_name}:8500/health")
            resp.raise_for_status()
            return resp.json()

    def cleanup_container(self, container_name: str, remove_volume: bool = False) -> None:
        try:
            self._run_docker(["stop", "-t", "10", container_name], timeout=20)
        except Exception as e:
            print(f"[run_manager] stop {container_name} (ignored): {e}")
        try:
            self._run_docker(["rm", "-f", container_name], timeout=10)
        except Exception as e:
            print(f"[run_manager] rm {container_name} (ignored): {e}")
        if remove_volume:
            slot = self.slots.get(container_name)
            if slot and slot.volume_name:
                try:
                    self._run_docker(["volume", "rm", slot.volume_name], timeout=10)
                    print(f"[run_manager] Removed volume {slot.volume_name}")
                except Exception as e:
                    print(f"[run_manager] volume rm {slot.volume_name} (ignored): {e}")

    def cleanup_all_finished(self, remove_volumes: bool = False) -> int:
        """Clean up containers and remove slots for finished runs. Returns count cleaned."""
        cleaned = 0
        for name, slot in list(self.slots.items()):
            if slot.status not in ("starting", "running"):
                self.cleanup_container(name, remove_volume=remove_volumes)
                del self.slots[name]
                cleaned += 1
        return cleaned
