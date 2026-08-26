"""Execution backends for eval containers.

One seam, two implementations. `runner.py` describes a short-lived container
(image, command, env, limits, timeout) and gets back (exit_code, logs); it does
not know where that ran.

    local mode  -> DockerBackend  (host Docker Engine API over the unix socket)
    cloud mode  -> VercelBackend  (ephemeral Vercel sandbox VM; required)

In cloud mode the Docker path is unreachable: `get_execution_backend` raises
rather than falling back, so a misconfiguration can never silently hand
eval workloads the host daemon. (The Kubernetes backend was retired with the
EKS estate; eval workloads no longer run on cluster pods.)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from ..config.evals import EvalRunSettings

logger = logging.getLogger(__name__)

# Unversioned path: the daemon serves its newest supported API version.
_DOCKER_API = "http://docker"

# Exit code reported when the workload outlived its timeout.
TIMED_OUT = -2

_EVAL_POD_LABEL = "signalpilot.ai/eval"


@dataclass
class ContainerRun:
    """One short-lived container: what to run and what it may consume.

    `secret_env` carries credentials (Anthropic tokens, the per-run MCP API key
    embedded in the MCP config). Backends must keep those out of anything an
    operator can read back.

    `binds` and `extra_network` are Docker-only host affordances used by the
    state-setup path; other backends refuse them rather than silently
    dropping the mount a setup script depends on.

    `on_start` fires once the workload exists and carries its identity
    ({backend, name, namespace, started_at}). The runner records it so the
    sandbox panel can attribute a live pod to the question it is answering
    without waiting for `run` to return.
    """

    image: str
    command: list[str]
    env: dict[str, str]
    secret_env: dict[str, str]
    labels: dict[str, str]
    memory_bytes: int
    nano_cpus: int
    timeout_seconds: int
    binds: list[str] = field(default_factory=list)
    extra_network: str = ""
    on_start: Callable[[dict], None] | None = None


def _notify_start(spec: ContainerRun, info: dict) -> None:
    """Hand the workload's identity to the runner. Never fatal: a bookkeeping
    failure must not take down the eval it is describing."""
    if spec.on_start is None:
        return
    try:
        spec.on_start({**info, "started_at": _utcnow()})
    except Exception:
        logger.warning("Eval sandbox start callback failed for %s", info.get("name"), exc_info=True)


def _utcnow() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


class ExecutionBackend(Protocol):
    async def run(self, spec: ContainerRun) -> tuple[int, str]:
        """Run to completion and return (exit_code, combined logs)."""
        ...

    async def aclose(self) -> None: ...


# Docker.


class DockerBackend:
    """Host Docker Engine API over the unix socket via httpx (no docker CLI)."""

    def __init__(self, settings: EvalRunSettings) -> None:
        self._settings = settings
        transport = httpx.AsyncHTTPTransport(uds=settings.docker_socket)
        self._client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(30.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def run(self, spec: ContainerRun) -> tuple[int, str]:
        if spec.extra_network:
            raise RuntimeError("Eval workloads may not attach an extra Docker network")
        docker = self._client
        env = [f"{k}={v}" for k, v in {"HOME": "/work", **spec.env, **spec.secret_env}.items()]
        tmpfs = {
            "/work": "rw,size=512m,mode=1777",
            "/tmp": "rw,size=512m,mode=1777",  # nosec B108 - This path is a container tmpfs.
        }
        if not any(bind.rsplit(":", 2)[-2] == "/repo" for bind in spec.binds):
            tmpfs["/repo"] = "rw,size=512m,mode=1777"
        create = await docker.post(
            f"{_DOCKER_API}/containers/create",
            json={
                "Image": spec.image,
                "Cmd": spec.command,
                "Env": env,
                "User": "65532:65532",
                "Tty": True,  # raw (non-multiplexed) log stream
                "WorkingDir": "/work",
                "Labels": {
                    "signalpilot.eval": "1",
                    **{f"signalpilot.eval.{k}": v for k, v in spec.labels.items()},
                },
                "HostConfig": {
                    "NetworkMode": self._settings.docker_network,
                    "Binds": spec.binds,
                    "Memory": spec.memory_bytes,
                    "NanoCpus": spec.nano_cpus,
                    "ReadonlyRootfs": True,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "PidsLimit": 256,
                    "Tmpfs": tmpfs,
                },
            },
        )
        if create.status_code != 201:
            raise RuntimeError(f"container create failed ({create.status_code}): {create.text[:300]}")
        cid = create.json()["Id"]

        try:
            start = await docker.post(f"{_DOCKER_API}/containers/{cid}/start")
            if start.status_code not in (204, 304):
                raise RuntimeError(f"container start failed ({start.status_code}): {start.text[:300]}")
            _notify_start(spec, {"backend": "docker", "name": cid[:12], "id": cid, "namespace": ""})

            try:
                wait = await docker.post(
                    f"{_DOCKER_API}/containers/{cid}/wait",
                    timeout=httpx.Timeout(spec.timeout_seconds + 30, connect=30),
                )
                exit_code = int(wait.json().get("StatusCode", -1))
            except httpx.TimeoutException:
                await docker.post(f"{_DOCKER_API}/containers/{cid}/kill")
                exit_code = TIMED_OUT

            logs = await docker.get(
                f"{_DOCKER_API}/containers/{cid}/logs",
                params={"stdout": "1", "stderr": "1"},
            )
            return exit_code, logs.content.decode("utf-8", errors="replace")
        finally:
            await docker.delete(f"{_DOCKER_API}/containers/{cid}", params={"force": "1"})


# Kubernetes.

# Everything the runner script writes goes to one of these emptyDirs, so the
# image's root filesystem can stay read-only: /work is the claude CLI's project
# dir (.mcp.json, .claude/settings.local.json) and doubles as HOME, /tmp is
# scratch for node and the CLI, /repo is where a setup script's `git clone`
# lands (unused by question pods, and an empty dir costs nothing there).
_WORK_DIR = "/work"
_TMP_DIR = "/tmp"  # nosec B108 - This path is a mounted container directory.
_REPO_DIR = "/repo"


_VERCEL_BOOTSTRAP = (
    "sudo mkdir -p /work && sudo chown \"$(id -u):$(id -g)\" /work && "
    "command -v claude >/dev/null 2>&1 || sudo npm install -g @anthropic-ai/claude-code"
)
_VERCEL_BOOTSTRAP_TIMEOUT = 240
# Provider-side ceiling on execution_time_limit (45 min); creation headroom
# beyond the eval timeout covers bootstrap plus scheduling.
_VERCEL_MAX_LIFETIME = 2700
_VERCEL_LIFETIME_HEADROOM = 300
# The run's combined output is tee'd here inside the sandbox so the panel can
# poll a live tail (exec only returns output when the command finishes).
_VERCEL_LOG_PATH = "/tmp/sp-eval-output.log"


class VercelBackend:
    """One ephemeral Vercel sandbox VM per eval container.

    Unlike the container backends, there is no runner image: the sandbox is a
    stock VM bootstrapped with the Claude CLI at start. The eval MCP config
    must therefore point at a publicly reachable gateway URL (SP_EVAL_MCP_URL)
    — sandboxes run in Vercel's network, not next to the gateway.

    Credentials ride the exec environment only; they are never baked into the
    sandbox spec, and the sandbox is destroyed in a finally block with the
    provider's execution time limit as backstop.
    """

    def __init__(self, settings: EvalRunSettings, *, org_id: str) -> None:
        from ..config.sandbox_runtime import get_sandbox_runtime_settings

        runtime_settings = get_sandbox_runtime_settings()
        if not runtime_settings.enabled:
            raise RuntimeError(
                "Vercel eval backend unavailable: VERCEL_TOKEN / VERCEL_TEAM_ID / "
                "VERCEL_PROJECT_ID are not all configured."
            )
        self._settings = settings
        self._org_id = org_id
        self._runtime_settings = runtime_settings

    async def aclose(self) -> None:
        return None

    def _make_runtime(self):
        from ..sandbox_runtime.vercel import VercelSandboxRuntime

        return VercelSandboxRuntime(project_id=self._runtime_settings.vercel_project_id)

    @staticmethod
    def _shell_command(spec: ContainerRun) -> str:
        # _task_spec/_script_spec always ship ["sh", "-lc", script]; anything
        # else is joined defensively rather than guessed at.
        if len(spec.command) == 3 and spec.command[0] == "sh" and spec.command[1] in ("-lc", "-c"):
            return spec.command[2]
        import shlex

        return shlex.join(spec.command)

    async def run(self, spec: ContainerRun) -> tuple[int, str]:
        if spec.binds or spec.extra_network:
            raise RuntimeError(
                "This eval set needs host bind mounts or an extra docker network, "
                "which the Vercel backend cannot provide. Use a git eval repo "
                "with a self-contained setup script."
            )
        from ..sandbox_runtime.base import SandboxSpec

        runtime = self._make_runtime()
        lifetime = min(spec.timeout_seconds + _VERCEL_LIFETIME_HEADROOM, _VERCEL_MAX_LIFETIME)
        # Secrets go to exec env, not the creation spec: creation metadata is
        # readable back from the provider API, per-exec env is not persisted.
        sandbox_id = await runtime.create(
            SandboxSpec(time_limit_seconds=lifetime, tags={"sp-eval": "1", "org": self._org_id[:64]})
        )
        _notify_start(spec, {"backend": "vercel", "name": sandbox_id, "namespace": ""})
        try:
            boot = await runtime.exec(
                sandbox_id, _VERCEL_BOOTSTRAP, timeout_seconds=_VERCEL_BOOTSTRAP_TIMEOUT
            )
            if boot.returncode != 0:
                return 1, (
                    "Vercel sandbox bootstrap failed "
                    f"(exit {boot.returncode}):\n{boot.stdout}\n{boot.stderr}"
                )
            loop = asyncio.get_event_loop()
            started = loop.time()
            # tee the merged output to a file: exec only returns output at
            # completion, so the file is what makes a live panel tail (and a
            # post-kill log recovery) possible. pipefail preserves the task's
            # exit code through the tee.
            wrapped = (
                "set -o pipefail; { "
                + self._shell_command(spec)
                + f" ; }} 2>&1 | tee {_VERCEL_LOG_PATH}"
            )
            result = await runtime.exec(
                sandbox_id,
                wrapped,
                env={**spec.env, **spec.secret_env},
                timeout_seconds=spec.timeout_seconds,
            )
            logs = result.stdout + (("\n" + result.stderr) if result.stderr else "")
            if not logs.strip():
                # A kill_after termination can drop the captured stream; the
                # tee'd file still holds everything up to the kill.
                data = await runtime.read_file(sandbox_id, _VERCEL_LOG_PATH)
                if data:
                    logs = data.decode("utf-8", errors="replace")
            # kill_after reports a plain non-zero exit; recover the timeout
            # signal from elapsed time so grading treats it like the container
            # backends' TIMED_OUT.
            if result.returncode != 0 and loop.time() - started >= spec.timeout_seconds - 1:
                return TIMED_OUT, logs
            return result.returncode, logs
        finally:
            await runtime.destroy(sandbox_id)


# Reaper.

# Terminal pods linger this long so the sandbox panel can still show their
# outcome, then they are removed. The run path deletes its own pod in a
# finally block; this only catches pods stranded by a gateway crash/restart
# mid-run — bare pods have no TTL, so without it they live forever.


def get_execution_backend(settings: EvalRunSettings, *, org_id: str) -> ExecutionBackend:
    """Pick the backend for the current deployment mode.

    SP_EVAL_EXECUTION_BACKEND=vercel opts eval workloads onto ephemeral Vercel
    sandbox VMs in any mode. Otherwise cloud never reaches DockerBackend: a
    cluster this gateway cannot talk to is a failed run, not a reason to hand
    untrusted eval workloads the host daemon.
    """
    from ..runtime.mode import is_cloud_mode

    if settings.execution_backend == "vercel":
        return VercelBackend(settings, org_id=org_id)
    if is_cloud_mode():
        raise RuntimeError(
            "Cloud mode requires SP_EVAL_EXECUTION_BACKEND=vercel — the "
            "Kubernetes eval backend was retired with the EKS estate, and "
            "cloud never hands eval workloads the host Docker daemon."
        )
    return DockerBackend(settings)
