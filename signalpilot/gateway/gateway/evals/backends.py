"""Execution backends for eval containers.

One seam, two implementations. `runner.py` describes a short-lived container
(image, command, env, limits, timeout) and gets back (exit_code, logs); it does
not know whether that ran on a Docker daemon or as a Kubernetes pod.

    local mode  -> DockerBackend      (host Docker Engine API over the unix socket)
    cloud mode  -> KubernetesBackend  (short-lived sandboxed pod, no docker socket)

In cloud mode the Docker path is unreachable: `get_execution_backend` raises
rather than falling back, so a misconfigured cluster can never silently hand
eval workloads the host daemon.
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

# Unversioned path — the daemon serves its newest supported API version.
_DOCKER_API = "http://docker"

# Exit code reported when the workload outlived its timeout.
TIMED_OUT = -2

_EVAL_POD_LABEL = "signalpilot.ai/eval"


@dataclass
class ContainerRun:
    """One short-lived container: what to run and what it may consume.

    `secret_env` carries credentials (Anthropic tokens, the per-run MCP API key
    embedded in the MCP config). Backends must keep those out of any spec a
    cluster operator can read back — on Kubernetes they ride a Secret, never the
    pod spec.

    `binds` and `extra_network` are Docker-only host affordances used by the
    state-setup path; KubernetesBackend refuses them rather than silently
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


# ─── Docker ──────────────────────────────────────────────────────────────────


class DockerBackend:
    """Host Docker Engine API over the unix socket via httpx (no docker CLI)."""

    def __init__(self, settings: EvalRunSettings) -> None:
        self._settings = settings
        transport = httpx.AsyncHTTPTransport(uds=settings.docker_socket)
        self._client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(30.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def run(self, spec: ContainerRun) -> tuple[int, str]:
        docker = self._client
        env = [f"{k}={v}" for k, v in {**spec.env, **spec.secret_env}.items()]
        create = await docker.post(
            f"{_DOCKER_API}/containers/create",
            json={
                "Image": spec.image,
                "Cmd": spec.command,
                "Env": env,
                "Tty": True,  # raw (non-multiplexed) log stream
                "Labels": {
                    "signalpilot.eval": "1",
                    **{f"signalpilot.eval.{k}": v for k, v in spec.labels.items()},
                },
                "HostConfig": {
                    "NetworkMode": self._settings.docker_network,
                    "Binds": spec.binds,
                    "Memory": spec.memory_bytes,
                    "NanoCpus": spec.nano_cpus,
                },
            },
        )
        if create.status_code != 201:
            raise RuntimeError(f"container create failed ({create.status_code}): {create.text[:300]}")
        cid = create.json()["Id"]

        try:
            if spec.extra_network:
                net_resp = await docker.post(
                    f"{_DOCKER_API}/networks/{spec.extra_network}/connect", json={"Container": cid}
                )
                if net_resp.status_code not in (200, 201):
                    raise RuntimeError(
                        f"setup network '{spec.extra_network}' attach failed "
                        f"({net_resp.status_code}): {net_resp.text[:200]}"
                    )
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


# ─── Kubernetes ──────────────────────────────────────────────────────────────

# Everything the runner script writes goes to one of these emptyDirs, so the
# image's root filesystem can stay read-only: /work is the claude CLI's project
# dir (.mcp.json, .claude/settings.local.json) and doubles as HOME, /tmp is
# scratch for node and the CLI, /repo is where a setup script's `git clone`
# lands (unused by question pods, and an empty dir costs nothing there).
_WORK_DIR = "/work"
_TMP_DIR = "/tmp"
_REPO_DIR = "/repo"


def eval_pod_manifest(
    *,
    pod_name: str,
    namespace: str,
    spec: ContainerRun,
    secret_name: str,
    resources: dict | None = None,
) -> dict:
    """Pod spec for one eval workload.

    restartPolicy Never rather than a Job: the runner already owns retry,
    sequencing and timeout policy, and a bare Pod is the object it can name,
    poll, read logs from and delete without a controller re-creating it or a
    second object to garbage-collect. It also matches the notebook machinery,
    so both sandboxed workloads share one scheduling and hardening story.

    Credentials are never in this spec — they arrive via envFrom on the
    ownerRef'd Secret, so `kubectl describe pod` and pod events show nothing.

    `spec.memory_bytes`/`nano_cpus` size the Docker path only. Pod sizing comes
    from settings (SP_EVAL_CPU_*/MEMORY_*/EPHEMERAL_*) and matches the notebook
    pod: eval pods land on the same sandbox node group, so a limit above that
    node's allocatable capacity is unschedulable rather than generous.
    """
    from ..orchestrator.kubernetes import _k8s_label_value, sandbox_scheduling

    if resources is None:
        from ..config.evals import get_eval_run_settings

        resources = get_eval_run_settings().pod_resources

    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "namespace": namespace,
            "labels": {
                "app": "signalpilot-eval",
                _EVAL_POD_LABEL: "1",
                **{
                    f"{_EVAL_POD_LABEL}-{k}": _k8s_label_value(v, k)
                    for k, v in spec.labels.items()
                },
            },
        },
        "spec": {
            **sandbox_scheduling(),
            # The eval workload runs untrusted model-authored commands; it must
            # not be able to reach the Kubernetes API at all.
            "automountServiceAccountToken": False,
            "enableServiceLinks": False,
            "restartPolicy": "Never",
            # Backstop for a pod the runner loses track of: kubelet stops it even
            # if the gateway replica that created it died mid-run.
            "activeDeadlineSeconds": spec.timeout_seconds,
            "terminationGracePeriodSeconds": 5,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 10002,
                "runAsGroup": 10002,
                "fsGroup": 10002,
                "fsGroupChangePolicy": "OnRootMismatch",
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [
                {
                    "name": "eval",
                    "image": spec.image,
                    "imagePullPolicy": "IfNotPresent",
                    "command": spec.command,
                    "env": [
                        {"name": k, "value": v}
                        for k, v in {"HOME": _WORK_DIR, **spec.env}.items()
                    ],
                    "envFrom": [{"secretRef": {"name": secret_name}}],
                    "workingDir": _WORK_DIR,
                    "resources": resources,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "allowPrivilegeEscalation": False,
                        "readOnlyRootFilesystem": True,
                        "capabilities": {"drop": ["ALL"]},
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "volumeMounts": [
                        {"name": "work", "mountPath": _WORK_DIR},
                        {"name": "tmp", "mountPath": _TMP_DIR},
                        {"name": "repo", "mountPath": _REPO_DIR},
                    ],
                }
            ],
            "volumes": [
                {"name": "work", "emptyDir": {"sizeLimit": "2Gi"}},
                {"name": "tmp", "emptyDir": {"sizeLimit": "1Gi"}},
                {"name": "repo", "emptyDir": {"sizeLimit": "4Gi"}},
            ],
        },
    }


class KubernetesBackend:
    """One short-lived sandboxed pod per eval container.

    Namespace layout mirrors notebooks: a per-org namespace built by
    `ensure_org_namespace`, which installs the RoleBinding that grants this
    gateway pods/secrets inside it, plus default-deny + allow-gateway
    NetworkPolicies, a ResourceQuota and a LimitRange. The prefix is
    SP_EVAL_K8S_NAMESPACE_PREFIX — see config/evals.py for why it defaults to
    the notebook tenant prefix rather than a dedicated one.
    """

    def __init__(self, settings: EvalRunSettings, *, org_id: str) -> None:
        if not org_id:
            raise ValueError("org_id is required for the Kubernetes eval backend")
        self._settings = settings
        self._org_id = org_id
        self._orchestrator = None

    async def aclose(self) -> None:
        if self._orchestrator is not None:
            await self._orchestrator.close()
            self._orchestrator = None

    async def _namespace(self) -> str:
        """Resolve (and bootstrap) the eval namespace for this org."""
        if self._orchestrator is None:
            from ..orchestrator.kubernetes import KubernetesOrchestrator

            orch = KubernetesOrchestrator()
            await orch._ensure_client()
            if orch._core_api is None:
                raise RuntimeError(
                    "Kubernetes eval backend unavailable: no usable cluster config. "
                    "Eval runs do not fall back to the Docker socket in cloud mode."
                )
            orch._namespace_prefix = self._settings.k8s_namespace_prefix
            self._orchestrator = orch
        return await self._orchestrator.ensure_namespace(self._org_id)

    async def run(self, spec: ContainerRun) -> tuple[int, str]:
        if spec.binds or spec.extra_network:
            raise RuntimeError(
                "This eval set needs host bind mounts or an extra docker network, "
                "which the Kubernetes backend cannot provide. Use a git eval repo "
                "with a self-contained setup script."
            )
        ns = await self._namespace()
        core = self._orchestrator._core_api
        pod_name = f"sp-eval-{uuid.uuid4().hex[:12]}"
        secret_name = f"sp-eval-env-{pod_name}"
        manifest = eval_pod_manifest(
            pod_name=pod_name,
            namespace=ns,
            spec=spec,
            secret_name=secret_name,
            resources=self._settings.pod_resources,
        )

        from ..orchestrator.jwt_secret_lifecycle import create_secret_with_owner_ref

        await create_secret_with_owner_ref(
            core,
            namespace=ns,
            secret_name=secret_name,
            values=dict(spec.secret_env),
            pod_name=pod_name,
            create_pod_fn=lambda: core.create_namespaced_pod(namespace=ns, body=manifest),
        )
        _notify_start(spec, {"backend": "kubernetes", "name": pod_name, "namespace": ns})
        try:
            exit_code = await self._wait_terminal(core, pod_name, ns, spec.timeout_seconds)
            logs = await self._read_logs(core, pod_name, ns)
            return exit_code, logs
        finally:
            await self._delete(core, pod_name, secret_name, ns)

    async def _wait_terminal(self, core, pod_name: str, ns: str, timeout: int) -> int:
        """Poll until the pod terminates. Returns its exit code, or TIMED_OUT."""
        # Grace beyond activeDeadlineSeconds so the kubelet's own kill is observed
        # as a terminal phase rather than racing this loop.
        deadline = asyncio.get_event_loop().time() + timeout + 60
        while asyncio.get_event_loop().time() < deadline:
            pod = (await core.read_namespaced_pod(name=pod_name, namespace=ns)).to_dict()
            status = pod.get("status") or {}
            phase = (status.get("phase") or "").lower()
            if phase in ("succeeded", "failed"):
                # activeDeadlineSeconds fired — report it the way the Docker
                # path reports its own timeout, so grading treats them alike.
                if status.get("reason") == "DeadlineExceeded":
                    return TIMED_OUT
                for cs in status.get("container_statuses") or []:
                    term = (cs.get("state") or {}).get("terminated") or {}
                    if "exit_code" in term:
                        return int(term["exit_code"])
                return 0 if phase == "succeeded" else 1
            await asyncio.sleep(1.0)
        return TIMED_OUT

    async def _read_logs(self, core, pod_name: str, ns: str) -> str:
        try:
            return str(
                await core.read_namespaced_pod_log(name=pod_name, namespace=ns, container="eval")
            )
        except Exception as exc:
            logger.warning("Failed to read eval pod logs %s/%s: %s", ns, pod_name, exc)
            return ""

    async def _delete(self, core, pod_name: str, secret_name: str, ns: str) -> None:
        # Kube GC removes the ownerRef'd Secret with the Pod, but that is
        # asynchronous and best-effort; delete it explicitly so a credential
        # never outlives the run it was minted for.
        for call, what in (
            (lambda: core.delete_namespaced_pod(name=pod_name, namespace=ns, grace_period_seconds=0), "pod"),
            (lambda: core.delete_namespaced_secret(name=secret_name, namespace=ns), "secret"),
        ):
            try:
                await call()
            except Exception as exc:
                if "404" not in str(exc) and "Not Found" not in str(exc):
                    logger.warning("Failed to delete eval %s %s/%s: %s", what, ns, pod_name, exc)


# ─── Selection ───────────────────────────────────────────────────────────────


def get_execution_backend(settings: EvalRunSettings, *, org_id: str) -> ExecutionBackend:
    """Pick the backend for the current deployment mode.

    Cloud never reaches DockerBackend — a cluster this gateway cannot talk to is
    a failed run, not a reason to hand untrusted eval workloads the host daemon.
    """
    from ..runtime.mode import is_cloud_mode

    if is_cloud_mode():
        return KubernetesBackend(settings, org_id=org_id)
    return DockerBackend(settings)
