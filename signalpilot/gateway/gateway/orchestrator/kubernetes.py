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

# Mount paths for the per-session JWT secret volume (initContainer → emptyDir).
# These must stay in sync with signalpilot/_server/entrypoint.py _JWT_PATH.
SP_SESSION_JWT_MOUNT_DIR = "/var/run/sp/session_jwt"
SP_SESSION_JWT_MOUNT_FILE = "/var/run/sp/session_jwt/session_jwt"


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


def _build_pod_spec(
    *,
    runtime_class: str | None,
    env: list[dict],
    image: str,
    session_id: str,
    session_jwt_secret_name: str,
) -> dict:
    """Build the pod spec dict. Separated from _pod_manifest to keep each under 50 lines.

    runtimeClassName is only set when runtime_class is non-empty — never emit empty string.

    R4 F-6: SP_SESSION_JWT is no longer injected via pod env. Instead, the per-session
    Secret is staged into an emptyDir tmpfs by the jwt-stager initContainer.  The main
    container entrypoint reads and unlinks the file before execvp-ing sp edit.

    R4 F-7a: readOnlyRootFilesystem: True on both main and init containers.
    R4 F-7b: ephemeral-storage requests/limits; sizeLimit on every emptyDir.

    Main container command is argv-only (no sh -c) — satisfies the F-4 argv-only
    invariant for the main container.  The initContainer uses sh -c with a constant
    string only (no user-input interpolation).
    """
    notebook_image = (
        f"docker.io/library/{image}"
        if ":" in image and "/" not in image
        else image
    )
    spec: dict = {
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
        "initContainers": [
            {
                "name": "jwt-stager",
                "image": notebook_image,
                # Constant sh -c string — no user-input interpolation.
                # Copies Secret file into emptyDir tmpfs and sets ownership to
                # uid 10001 so the main container can read and unlink it.
                "command": [
                    "sh",
                    "-c",
                    "cp /var/run/sp/session_jwt-src/session_jwt /var/run/sp/session_jwt/session_jwt "
                    "&& chmod 0400 /var/run/sp/session_jwt/session_jwt "
                    "&& chown 10001:10001 /var/run/sp/session_jwt/session_jwt",
                ],
                "securityContext": {
                    "runAsUser": 0,
                    "runAsNonRoot": False,
                    "readOnlyRootFilesystem": True,
                    "allowPrivilegeEscalation": False,
                    "capabilities": {
                        "drop": ["ALL"],
                        "add": ["CHOWN", "FOWNER"],
                    },
                },
                "volumeMounts": [
                    {
                        "name": "session-jwt-src",
                        "mountPath": "/var/run/sp/session_jwt-src",
                        "readOnly": True,
                    },
                    {
                        "name": "session-jwt",
                        "mountPath": SP_SESSION_JWT_MOUNT_DIR,
                    },
                ],
                "resources": {
                    "requests": {"cpu": "10m", "memory": "16Mi"},
                    "limits": {"cpu": "100m", "memory": "32Mi"},
                },
            },
        ],
        "containers": [
            {
                "name": "notebook",
                "image": notebook_image,
                "imagePullPolicy": "IfNotPresent",
                # Argv-only entrypoint — no sh -c in main container (F-4 invariant).
                # entrypoint.py reads the JWT from the emptyDir, unlinks it, then
                # execvp("sp", ["sp", "edit", ...]). _server.start pops SP_SESSION_JWT
                # from os.environ at import time before the HTTP listener binds.
                "command": ["python", "-m", "signalpilot._server.entrypoint"],
                "args": [
                    "--host", "0.0.0.0",
                    "--port", "2718",
                    "--headless",
                    "--no-token",
                    "--no-skew-protection",
                    "--allow-origins", "http://localhost:3200,http://localhost:3300",
                    "--base-url", f"/notebook/{session_id}",
                    "/workspace",
                ],
                "ports": [{"containerPort": 2718}],
                "env": env,
                "resources": {
                    "requests": {
                        "memory": "512Mi",
                        "cpu": "500m",
                        "ephemeral-storage": "256Mi",
                    },
                    "limits": {
                        "memory": "2Gi",
                        "cpu": "2",
                        "ephemeral-storage": "4Gi",
                    },
                },
                "securityContext": {
                    "allowPrivilegeEscalation": False,
                    "readOnlyRootFilesystem": True,
                    "capabilities": {"drop": ["ALL"]},
                },
                "volumeMounts": [
                    {"name": "tmp", "mountPath": "/tmp"},
                    {"name": "home", "mountPath": "/home/notebook"},
                    {"name": "workspace", "mountPath": "/workspace"},
                    # Writable emptyDir tmpfs — entrypoint unlinks the JWT file here.
                    # Main container does NOT mount session-jwt-src (the Secret).
                    {
                        "name": "session-jwt",
                        "mountPath": SP_SESSION_JWT_MOUNT_DIR,
                    },
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
            {"name": "tmp", "emptyDir": {"sizeLimit": "256Mi"}},
            {"name": "home", "emptyDir": {"sizeLimit": "1Gi"}},
            {"name": "workspace", "emptyDir": {"sizeLimit": "2Gi"}},
            # emptyDir tmpfs — writable for uid 10001, unlinked by entrypoint.
            {
                "name": "session-jwt",
                "emptyDir": {"medium": "Memory", "sizeLimit": "1Mi"},
            },
            # Read-only Secret volume — mounted only by initContainer.
            {
                "name": "session-jwt-src",
                "secret": {
                    "secretName": session_jwt_secret_name,
                    "defaultMode": 0o400,
                    "items": [{"key": "session_jwt", "path": "session_jwt"}],
                },
            },
        ],
        "restartPolicy": "Never",
        "terminationGracePeriodSeconds": 5,
    }
    if runtime_class:
        spec["runtimeClassName"] = runtime_class
    return spec


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
    session_id: str,
    session_jwt_secret_name: str,
    access_token: str | None,
    extra_env: dict[str, str] | None = None,
    runtime_class: str | None = None,
) -> dict:
    """Build the pod manifest dict for the Kubernetes API.

    Does NOT inject SP_SESSION_JWT into the pod env (R4 F-6). The JWT is staged
    via a per-session Secret → initContainer → emptyDir tmpfs path.  The entrypoint
    shim reads and unlinks the file, then execs sp edit.
    Does NOT inject SP_API_KEY (replaced by per-session JWT) or SP_ACCESS_TOKEN
    (removed in R2 — the gateway proxy is the sole auth gate; the pod runs --no-token).
    --token-password is removed unconditionally; the pod runs --no-token always.
    --base-url /notebook/{session_id} tells the notebook server to emit asset URLs under that prefix.
    access_token is stored on the DB row as the gateway proxy cookie value but is NOT
    injected into the pod env or CLI.

    R3: Adds pod-level securityContext (non-root, seccomp RuntimeDefault),
    container-level securityContext (drop ALL caps),
    automountServiceAccountToken: false, emptyDir volumes for writable scratch,
    and env additions for HOME, PYTHONDONTWRITEBYTECODE, SP_LOG_DIR.
    R4: Adds optional runtimeClassName for gVisor/Kata sandbox isolation.
    R4 F-6: Per-session Secret + initContainer + emptyDir replaces SP_SESSION_JWT env var.
    R4 F-7a/b: readOnlyRootFilesystem: True; ephemeral-storage limits; emptyDir sizeLimit.
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
        # SP_SESSION_JWT is NOT injected as an env var (R4 F-6).
        # It is staged via Secret → initContainer → emptyDir; the entrypoint
        # shim reads and unlinks the file, placing the value into os.environ
        # for the brief window before _server.start pops it at import time.
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
        "spec": _build_pod_spec(
            runtime_class=runtime_class,
            env=env,
            image=image,
            session_id=session_id,
            session_jwt_secret_name=session_jwt_secret_name,
        ),
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
        self._runtime_class: str | None = None
        # Set to True only after read_runtime_class returns successfully (or local mode skip).
        # Never set on failure — ensures retried callers re-attempt the check.
        self._runtime_class_verified: bool = False
        # Created lazily on first _ensure_client call to avoid binding to a running event loop
        # at construction time (asyncio.Lock() must be created inside a coroutine or after loop start).
        self._init_lock: asyncio.Lock | None = None

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
        self._runtime_class = settings.sp_notebook_runtime_class or None

    async def _ensure_client(self) -> None:
        # Lazy-create the lock here so it's always created inside a running event loop.
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._client is not None:
                return
            self._load_settings()
            from kubernetes_asyncio import client, config

            kubeconfig = os.getenv("KUBECONFIG")
            k8s_host = os.getenv("SP_K8S_HOST")
            # Use a local variable until preflight succeeds — only assign self._client
            # after _preflight_runtime_class() returns. This guarantees that a failed
            # preflight leaves self._client = None so the next caller retries.
            client_obj = None
            try:
                if kubeconfig and os.path.exists(kubeconfig):
                    await config.load_kube_config(config_file=kubeconfig)
                    if k8s_host:
                        cfg = client.Configuration.get_default_copy()
                        cfg.host = k8s_host
                        cfg.verify_ssl = False
                        client_obj = client.ApiClient(configuration=cfg)
                else:
                    config.load_incluster_config()
            except Exception as e:
                logger.warning("K8s config failed: %s — orchestrator disabled", e)
                return
            if client_obj is None:
                client_obj = client.ApiClient()
            core_api = client.CoreV1Api(client_obj)
            networking_api = client.NetworkingV1Api(client_obj)
            rbac_api = client.RbacAuthorizationV1Api(client_obj)
            logger.info("K8s orchestrator connected (namespace_prefix=%s)", self._namespace_prefix)
            # Run preflight against the not-yet-committed client. On failure (cloud mode),
            # _preflight_runtime_class raises and we never reach the assignments below —
            # self._client remains None so the next call retries.
            await self._preflight_runtime_class(client_obj)
            # Preflight passed — commit client state atomically.
            self._client = client_obj
            self._core_api = core_api
            self._networking_api = networking_api
            self._rbac_api = rbac_api

    async def _preflight_runtime_class(self, client_obj: object | None = None) -> None:
        """Verify the configured runtimeClass exists in the cluster (fail-closed).

        Called once from _ensure_client with the not-yet-committed client_obj.
        Results are cached via _runtime_class_verified; no re-check on subsequent
        pod creates. If sp_notebook_runtime_class is empty, does nothing.

        In cloud mode: missing RuntimeClass → RuntimeError (fail-closed).
            _runtime_class_verified is NOT set on failure so the next caller retries.
        In local mode: missing RuntimeClass → log warning, continue.
            _runtime_class_verified is set so we do not spam warnings on every call.
        """
        if self._runtime_class_verified:
            return

        runtime_class = self._runtime_class
        if not runtime_class:
            return

        is_cloud = os.environ.get("SP_DEPLOYMENT_MODE", "").lower() == "cloud"
        api_client = client_obj if client_obj is not None else self._client

        try:
            from kubernetes_asyncio import client as k8s_client

            node_api = k8s_client.NodeV1Api(api_client)
            await node_api.read_runtime_class(name=runtime_class)
            logger.info("RuntimeClass %r verified in cluster", runtime_class)
            # Only mark verified after a successful read — never on exception.
            self._runtime_class_verified = True
        except Exception as exc:
            msg = (
                f"RuntimeClass {runtime_class!r} not found in cluster (error: {exc}). "
                "Install the RuntimeClass resource or set SP_NOTEBOOK_RUNTIME_CLASS='' "
                "to disable sandbox enforcement."
            )
            if is_cloud:
                # Do NOT set _runtime_class_verified — next caller must re-attempt.
                raise RuntimeError(msg) from exc
            logger.warning("%s — continuing (local mode)", msg)
            # In local mode, mark verified to avoid repeated warnings.
            self._runtime_class_verified = True

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
        session_jwt_secret_name: str,
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
            session_jwt_secret_name=session_jwt_secret_name,
            session_id=session_id,
            access_token=access_token,
            extra_env=extra_env,
            runtime_class=self._runtime_class,
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

        Does NOT wait for readinessProbe. Polls until the container process is up
        so the pod entrypoint (project_sync_boot + sp edit) can proceed.
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
        which passes only after `sp edit` binds port 2718, which happens after
        project_sync_boot completes the workspace git clone.

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

    async def exec_in_pod(
        self,
        pod_name: str,
        *,
        org_id: str,
        argv: list[str],
        timeout: int = 300,
        stdin_bytes: bytes | None = None,
    ) -> tuple[str, str, int]:
        """Run a command in a pod and return (stdout, stderr, exit_code).

        When stdin_bytes is provided, the payload is written to stdin (channel 0)
        after the exec connection is established and EOF is signaled so that
        commands like `tee` exit cleanly. See pod_exec_io for size limits.
        """
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
            stdin_bytes=stdin_bytes,
        )

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
            self._core_api = None
            self._networking_api = None
            self._rbac_api = None
