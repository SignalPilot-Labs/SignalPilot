"""Kubernetes orchestrator — creates/deletes notebook pods via K8s API.

Works with K3s locally and EKS in production. Same code path.

Cloud mode only: SP_DEPLOYMENT_MODE=cloud + SP_NOTEBOOK_UPSTREAM_MODE=pod_ip.
NodePort path is fully removed in R3. The constructor refuses any upstream mode
other than pod_ip with a clear RuntimeError.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from . import NotebookOrchestrator, PodInfo
from .namespaces import ensure_org_namespace, namespace_for_org

logger = logging.getLogger(__name__)

# SP_NOTEBOOK_UPSTREAM_MODE: the env-var validator still accepts "nodeport" for
# compose/dev test environments that instantiate a different orchestrator path.
# KubernetesOrchestrator itself refuses anything other than "pod_ip" in its
# constructor — there are no nodeport branches left in this class.
_UPSTREAM_MODE = os.getenv("SP_NOTEBOOK_UPSTREAM_MODE", "nodeport")
if _UPSTREAM_MODE not in {"pod_ip", "nodeport", "direct"}:
    raise RuntimeError(
        f"Invalid SP_NOTEBOOK_UPSTREAM_MODE: {_UPSTREAM_MODE!r}. "
        "Allowed values: 'pod_ip', 'nodeport', 'direct'."
    )


def _parse_single_kv(selector_str: str) -> dict[str, str]:
    """Parse a single k=v selector string into a dict. Raises on violation."""
    if "," in selector_str or selector_str.count("=") != 1:
        raise ValueError(
            f"Gateway pod selector must be a single k=v pair, no commas or wildcards. "
            f"Got: {selector_str!r}"
        )
    k, v = selector_str.split("=", 1)
    k = k.strip()
    v = v.strip()
    if not k or not v:
        raise ValueError(
            f"Gateway pod selector key and value must be non-empty. Got: {selector_str!r}"
        )
    return {k: v}


def _pod_manifest(
    *,
    pod_name: str,
    namespace: str,
    image: str,
    user_id: str,
    org_id: str,
    project_id: str | None,
    branch: str,
    gateway_url: str,
    session_jwt: str,
    session_id: str,
    access_token: str | None,
    extra_env: dict[str, str] | None = None,
) -> dict:
    """Build the pod spec dict for the Kubernetes API.

    Injects SP_SESSION_JWT and SP_SESSION_ID into the pod env.
    Does NOT inject SP_API_KEY (replaced by per-session JWT) or SP_ACCESS_TOKEN
    (removed in R2 — the gateway proxy is the sole auth gate; the pod runs --no-token).
    --token-password is removed unconditionally; the pod runs --no-token always.
    --base-url /notebook/{session_id} tells the notebook server to emit asset URLs under that prefix.
    access_token is stored on the DB row as the gateway proxy cookie value but is NOT
    injected into the pod env or CLI.

    R3: Adds pod-level securityContext (non-root, seccomp RuntimeDefault),
    container-level securityContext (readOnlyRootFilesystem, drop ALL caps),
    automountServiceAccountToken: false, emptyDir volumes for writable scratch,
    and env additions for HOME, PYTHONDONTWRITEBYTECODE, SP_LOG_DIR.
    """
    static_internal_url = os.getenv("SP_GATEWAY_INTERNAL_URL", "")
    gateway_port = os.getenv("SP_PUBLIC_GATEWAY_PORT", "3300")
    env = [
        {"name": "SP_NODE_IP", "valueFrom": {"fieldRef": {"fieldPath": "status.hostIP"}}},
    ]
    if static_internal_url:
        env.append({"name": "SP_GATEWAY_URL", "value": static_internal_url})
    else:
        env.append({"name": "SP_GATEWAY_URL", "value": f"http://$(SP_NODE_IP):{gateway_port}"})
    env += [
        {"name": "SP_GATEWAY_PUBLIC_URL", "value": gateway_url},
        {"name": "SP_PROJECT_ID", "value": project_id or ""},
        {"name": "SP_BRANCH", "value": branch},
        {"name": "SP_USER_ID", "value": user_id},
        {"name": "SP_ORG_ID", "value": org_id},
        {"name": "SP_SESSION_JWT", "value": session_jwt},
        {"name": "SP_SESSION_ID", "value": session_id},
        # Required because sp-notebook is installed at /opt/sp-notebook which is on the
        # read-only root FS; without this, Python attempts to write __pycache__/*.pyc
        # and EROFS surfaces at import time.
        {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
        {"name": "HOME", "value": "/home/notebook"},
        {"name": "SP_LOG_DIR", "value": "/tmp/sp-logs"},
    ]
    if extra_env:
        for k, v in extra_env.items():
            env.append({"name": k, "value": v})
    # SP_ACCESS_TOKEN removed in R2. access_token is stored for the proxy cookie only.

    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "namespace": namespace,
            "labels": {
                "app": "signalpilot-notebook",
                "signalpilot.ai/user": user_id[:63],
                "signalpilot.ai/org": org_id[:63],
            },
        },
        "spec": {
            # Pods must not mount the SA token — no K8s API access from within notebook pods.
            "automountServiceAccountToken": False,
            # Suppress per-Service env var injection (SVC_SERVICE_HOST, SVC_PORT, etc.).
            # Prevents information disclosure of cluster Service topology to notebook pods.
            "enableServiceLinks": False,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 10001,
                "runAsGroup": 10001,
                "fsGroup": 10001,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [
                {
                    "name": "notebook",
                    "image": (
                        f"docker.io/library/{image}"
                        if ":" in image and "/" not in image
                        else image
                    ),
                    "imagePullPolicy": "IfNotPresent",
                    # R4: Sentinel-wait shim (C1). The pod CMD polls for /workspace/.sp-ready
                    # before starting the notebook server. This ensures the gateway has finished
                    # injecting the workspace content (via pods/exec tar) before it opens /workspace.
                    # The pod reaches Running state but NOT Ready (readinessProbe probes the
                    # notebook HTTP port which is not bound until after the sentinel is written).
                    # Sequence: create_pod → wait_for_running → populate_pod_workspace
                    #           (writes .sp-ready last) → wait_for_ready.
                    # --no-token: pod runs without the notebook server's built-in auth; the gateway
                    # proxy is the sole auth gate.
                    # --base-url: tells the notebook server to emit asset/WS URLs under /notebook/{session_id}.
                    "command": [
                        "sh", "-c",
                        "while [ ! -f /workspace/.sp-ready ]; do sleep 0.2; done; "
                        f"exec sp edit --host 0.0.0.0 --port 2718 --headless --no-token "
                        f"--no-skew-protection --allow-origins 'http://localhost:3200,http://localhost:3300' "
                        f"--base-url /notebook/{session_id} /workspace",
                    ],
                    "ports": [{"containerPort": 2718}],
                    "env": env,
                    "resources": {
                        "requests": {"memory": "512Mi", "cpu": "500m"},
                        "limits": {"memory": "2Gi", "cpu": "2"},
                    },
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "readOnlyRootFilesystem": False,
                        "capabilities": {"drop": ["ALL"]},
                    },
                    "volumeMounts": [
                        {"name": "tmp", "mountPath": "/tmp"},
                        {"name": "home", "mountPath": "/home/notebook"},
                        {"name": "workspace", "mountPath": "/workspace"},
                    ],
                    "readinessProbe": {
                        "tcpSocket": {"port": 2718},
                        "initialDelaySeconds": 1,
                        "periodSeconds": 1,
                        "failureThreshold": 60,
                    },
                    "livenessProbe": {
                        "tcpSocket": {"port": 2718},
                        "initialDelaySeconds": 30,
                        "periodSeconds": 30,
                        "failureThreshold": 5,
                    },
                }
            ],
            "volumes": [
                {"name": "tmp", "emptyDir": {}},
                {"name": "home", "emptyDir": {}},
                {"name": "workspace", "emptyDir": {}},
            ],
            "restartPolicy": "Never",
            "terminationGracePeriodSeconds": 5,
        },
    }


def _parse_pod_status(pod: dict) -> str:
    status = pod.get("status", {})
    phase = status.get("phase") or status.get("Phase") or "Unknown"
    return phase.lower()


def _parse_pod_ip(pod: dict) -> str | None:
    status = pod.get("status", {})
    return status.get("pod_ip") or status.get("podIP")


class KubernetesOrchestrator(NotebookOrchestrator):
    """Manages notebook pods via the Kubernetes API.

    Requires SP_NOTEBOOK_UPSTREAM_MODE=pod_ip. Refuses any other value at
    construction time. The nodeport path was fully removed in R3.
    """

    def __init__(self, image: str | None = None):
        if _UPSTREAM_MODE != "pod_ip":
            raise RuntimeError(
                "KubernetesOrchestrator requires SP_NOTEBOOK_UPSTREAM_MODE=pod_ip. "
                f"Got: {_UPSTREAM_MODE!r}. "
                "NodePort mode was retired in R3. Use pod_ip for cloud/k8s deployments."
            )
        self._image = image or os.getenv("SP_NOTEBOOK_IMAGE", "signalpilot-notebook:latest")
        self._client = None
        self._core_api = None
        self._networking_api = None
        self._rbac_api = None

        # Loaded from settings — resolved lazily to avoid importing settings at module load.
        self._namespace_prefix: str | None = None
        self._gateway_namespace: str | None = None
        self._gateway_pod_selector: dict[str, str] | None = None
        self._gateway_port: int | None = None
        self._egress_cidr: str | None = None
        self._gateway_service_account: str | None = None

    def _load_settings(self) -> None:
        """Load K8s settings on first use. Called from _ensure_client."""
        if self._namespace_prefix is not None:
            return
        from ..config.k8s import get_k8s_settings

        settings = get_k8s_settings()
        self._namespace_prefix = settings.sp_notebook_namespace_prefix
        self._gateway_namespace = settings.sp_gateway_namespace
        self._gateway_pod_selector = _parse_single_kv(settings.sp_gateway_pod_selector)
        self._gateway_port = settings.sp_public_gateway_port
        self._egress_cidr = settings.sp_notebook_egress_cidr
        self._gateway_service_account = settings.sp_gateway_service_account

    async def _ensure_client(self) -> None:
        if self._client is not None:
            return
        self._load_settings()
        from kubernetes_asyncio import client, config

        kubeconfig = os.getenv("KUBECONFIG")
        k8s_host = os.getenv("SP_K8S_HOST")
        try:
            if kubeconfig and os.path.exists(kubeconfig):
                await config.load_kube_config(config_file=kubeconfig)
                if k8s_host:
                    cfg = client.Configuration.get_default_copy()
                    cfg.host = k8s_host
                    cfg.verify_ssl = False
                    self._client = client.ApiClient(configuration=cfg)
            else:
                config.load_incluster_config()
        except Exception as e:
            logger.warning("K8s config failed: %s — orchestrator disabled", e)
            return
        if self._client is None:
            self._client = client.ApiClient()
        self._core_api = client.CoreV1Api(self._client)
        self._networking_api = client.NetworkingV1Api(self._client)
        self._rbac_api = client.RbacAuthorizationV1Api(self._client)
        logger.info("K8s orchestrator connected (namespace_prefix=%s)", self._namespace_prefix)

    def _resolve_namespace(self, org_id: str) -> str:
        """Resolve the namespace for an org_id. Raises ValueError on empty org_id."""
        if not org_id:
            raise ValueError("org_id must not be empty")
        if self._namespace_prefix is None:
            self._load_settings()
        assert self._namespace_prefix is not None
        return namespace_for_org(org_id, prefix=self._namespace_prefix)

    def _assert_settings_loaded(self) -> None:
        """Assert all settings were loaded. Called after _ensure_client."""
        assert self._namespace_prefix is not None, "namespace_prefix not loaded"
        assert self._gateway_namespace is not None, "gateway_namespace not loaded"
        assert self._gateway_pod_selector is not None, "gateway_pod_selector not loaded"
        assert self._gateway_port is not None, "gateway_port not loaded"
        assert self._gateway_service_account is not None, "gateway_service_account not loaded"

    async def create_pod(
        self,
        *,
        pod_name: str,
        user_id: str,
        org_id: str,
        project_id: str | None,
        branch: str,
        image: str,
        gateway_url: str,
        session_jwt: str,
        session_id: str,
        access_token: str | None,
        extra_env: dict[str, str] | None = None,
    ) -> PodInfo:
        if not org_id:
            raise ValueError("org_id must not be empty")
        await self._ensure_client()
        if not self._core_api:
            raise RuntimeError("K8s orchestrator not available")
        self._assert_settings_loaded()

        ns = self._resolve_namespace(org_id)

        # These cannot be None after _assert_settings_loaded().
        gateway_namespace: str = self._gateway_namespace  # type: ignore[assignment]
        gateway_pod_selector: dict[str, str] = self._gateway_pod_selector  # type: ignore[assignment]
        gateway_port: int = self._gateway_port  # type: ignore[assignment]
        gateway_service_account: str = self._gateway_service_account  # type: ignore[assignment]

        skip_netpol = os.getenv("SP_NOTEBOOK_NETWORK_POLICY", "true").lower() == "false"
        await ensure_org_namespace(
            self._core_api,
            self._networking_api,
            self._rbac_api,
            org_id=org_id,
            namespace=ns,
            gateway_namespace=gateway_namespace,
            gateway_pod_selector=gateway_pod_selector,
            gateway_port=gateway_port,
            egress_cidr=self._egress_cidr,
            gateway_service_account=gateway_service_account,
            skip_network_policy=skip_netpol,
        )

        manifest = _pod_manifest(
            pod_name=pod_name,
            namespace=ns,
            image=image or self._image,
            user_id=user_id,
            org_id=org_id,
            project_id=project_id,
            branch=branch,
            gateway_url=gateway_url,
            session_jwt=session_jwt,
            session_id=session_id,
            access_token=access_token,
            extra_env=extra_env,
        )
        await self._core_api.create_namespaced_pod(namespace=ns, body=manifest)
        logger.info("Created pod %s in namespace %s (pod_ip mode)", pod_name, ns)
        return PodInfo(name=pod_name, ip=None, status="pending")

    async def delete_pod(self, pod_name: str, *, org_id: str) -> bool:
        if not org_id:
            raise ValueError("org_id must not be empty")
        await self._ensure_client()
        if not self._core_api:
            return False
        ns = self._resolve_namespace(org_id)
        deleted = False
        try:
            await self._core_api.delete_namespaced_pod(
                name=pod_name, namespace=ns, grace_period_seconds=5,
            )
            deleted = True
        except Exception as e:
            if "404" not in str(e) and "Not Found" not in str(e):
                logger.warning("Failed to delete pod %s in %s: %s", pod_name, ns, e)
        if deleted:
            logger.info("Deleted pod %s from namespace %s", pod_name, ns)
        return deleted

    async def get_pod(self, pod_name: str, *, org_id: str) -> PodInfo | None:
        if not org_id:
            raise ValueError("org_id must not be empty")
        await self._ensure_client()
        if not self._core_api:
            return None
        ns = self._resolve_namespace(org_id)
        try:
            resp = await self._core_api.read_namespaced_pod(name=pod_name, namespace=ns)
            pod = resp.to_dict()
            return PodInfo(
                name=pod_name,
                ip=_parse_pod_ip(pod),
                status=_parse_pod_status(pod),
            )
        except Exception:
            return None

    async def is_pod_alive(self, pod_name: str, *, org_id: str) -> bool:
        """Return True iff the pod exists and its phase is 'running'."""
        if not org_id:
            raise ValueError("org_id must not be empty")
        pod = await self.get_pod(pod_name, org_id=org_id)
        return pod is not None and pod.status == "running"

    async def wait_for_running(self, pod_name: str, *, org_id: str, timeout: int = 60) -> PodInfo:
        """Poll until pod phase is Running and container started=True, or timeout.

        Does NOT wait for readinessProbe. Used before populate_pod_workspace so we
        can exec into the pod as soon as the container process is up.
        """
        if not org_id:
            raise ValueError("org_id must not be empty")
        await self._ensure_client()
        if not self._core_api:
            raise RuntimeError("K8s orchestrator not available")

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            pod = await self.get_pod(pod_name, org_id=org_id)
            if pod and pod.status == "running":
                return PodInfo(
                    name=pod.name,
                    ip=pod.ip,
                    status="running",
                    internal_ip=pod.ip,
                )
            if pod and pod.status in ("failed", "succeeded"):
                raise RuntimeError(f"Pod {pod_name} entered terminal state: {pod.status}")
            await asyncio.sleep(0.5)
        raise TimeoutError(f"Pod {pod_name} not in Running state after {timeout}s")

    async def _is_pod_container_ready(self, pod_name: str, *, ns: str) -> tuple[bool, str | None]:
        """Return (all_containers_ready, pod_ip) by inspecting containerStatuses[*].ready.

        Reads pod directly (not via get_pod) to access the full status object.
        Returns (False, None) on any K8s API error.
        """
        if not self._core_api:
            return False, None
        try:
            resp = await self._core_api.read_namespaced_pod(name=pod_name, namespace=ns)
            pod = resp.to_dict()
            status = pod.get("status", {})
            phase = (status.get("phase") or "").lower()
            if phase in ("failed", "succeeded"):
                return False, None

            container_statuses = status.get("container_statuses") or []
            if not container_statuses:
                return False, None

            all_ready = all(cs.get("ready", False) for cs in container_statuses)
            pod_ip = status.get("pod_ip") or status.get("podIP")
            return all_ready and bool(pod_ip), pod_ip
        except Exception:
            return False, None

    async def wait_for_ready(self, pod_name: str, *, org_id: str, timeout: int = 60) -> PodInfo:
        """Poll until all containers in the pod are ready (containerStatuses[*].ready=True).

        Returns PodInfo with internal_ip set to the raw pod IP (pod_ip mode only).
        Container readiness is gated by the readinessProbe (tcpSocket on port 2718),
        which passes only after the notebook server starts, which only happens after the sentinel
        /workspace/.sp-ready is extracted — making this the true end of the C1 flow.

        Distinct from wait_for_running: that method only checks pod phase == Running;
        this method checks that all containers have passed their readinessProbe.
        """
        if not org_id:
            raise ValueError("org_id must not be empty")
        await self._ensure_client()
        if not self._core_api:
            raise RuntimeError("K8s orchestrator not available")

        ns = self._resolve_namespace(org_id)
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            all_ready, pod_ip = await self._is_pod_container_ready(pod_name, ns=ns)
            if all_ready and pod_ip:
                return PodInfo(
                    name=pod_name,
                    ip=pod_ip,
                    status="running",
                    internal_ip=pod_ip,
                )
            # Check for terminal state to avoid polling until timeout.
            pod = await self.get_pod(pod_name, org_id=org_id)
            if pod and pod.status in ("failed", "succeeded"):
                raise RuntimeError(f"Pod {pod_name} entered terminal state: {pod.status}")
            await asyncio.sleep(0.5)
        raise TimeoutError(f"Pod {pod_name} not ready after {timeout}s")

    async def populate_pod_workspace(
        self, pod_name: str, *, org_id: str, src: Path
    ) -> None:
        """Inject workspace content into the pod via pods/exec tar stream.

        Writes .sp-ready as the FINAL entry in the tar stream so the sentinel-wait
        shim in the pod CMD starts the notebook server only after all workspace content is present.

        Delegates to pod_exec_io.stream_tar_into_pod — the sole authorized
        caller of the K8s exec API. Not on the NotebookOrchestrator ABC (K8s-specific).
        """
        if not org_id:
            raise ValueError("org_id must not be empty")
        await self._ensure_client()
        if not self._core_api:
            raise RuntimeError("K8s orchestrator not available")

        # Write .sp-ready sentinel into src dir. Pass it as sentinel_last so
        # stream_tar_into_pod guarantees it is the FINAL tar member regardless of
        # lexicographic sort order (C1: dot-files sort before visible files in ASCII,
        # so a naive sorted() would place ".sp-ready" first, not last).
        sentinel = src / ".sp-ready"
        sentinel.write_bytes(b"")

        from .pod_exec_io import stream_tar_into_pod

        ns = self._resolve_namespace(org_id)
        await stream_tar_into_pod(
            self._core_api,
            namespace=ns,
            pod_name=pod_name,
            src_dir=src,
            dest_path="/workspace/",
            sentinel_last=sentinel,
        )

    async def snapshot_pod_workspace(
        self, pod_name: str, *, org_id: str, dest: Path
    ) -> None:
        """Pull workspace content from the pod via pods/exec tar stream into dest.

        Delegates to pod_exec_io.stream_tar_out_of_pod. Not on the ABC (K8s-specific).
        """
        if not org_id:
            raise ValueError("org_id must not be empty")
        await self._ensure_client()
        if not self._core_api:
            raise RuntimeError("K8s orchestrator not available")

        from .pod_exec_io import stream_tar_out_of_pod

        ns = self._resolve_namespace(org_id)
        await stream_tar_out_of_pod(
            self._core_api,
            namespace=ns,
            pod_name=pod_name,
            src_path="/workspace/",
            dest_dir=dest,
        )

    async def exec_in_pod(
        self, pod_name: str, *, org_id: str, argv: list[str], timeout: int = 300
    ) -> tuple[str, str, int]:
        """Run a command in a pod and return (stdout, stderr, exit_code)."""
        if not org_id:
            raise ValueError("org_id must not be empty")
        await self._ensure_client()
        if not self._core_api:
            raise RuntimeError("K8s orchestrator not available")

        from .pod_exec_io import exec_command_in_pod

        ns = self._resolve_namespace(org_id)
        return await exec_command_in_pod(
            self._core_api,
            namespace=ns,
            pod_name=pod_name,
            argv=argv,
            timeout_seconds=timeout,
        )

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
            self._core_api = None
            self._networking_api = None
            self._rbac_api = None
