"""Kubernetes orchestrator — creates/deletes notebook pods via K8s API.

Works with K3s locally and EKS in production. Same code path.
"""

from __future__ import annotations

import asyncio
import logging
import os

from . import NotebookOrchestrator, PodInfo

logger = logging.getLogger(__name__)

# SP_NOTEBOOK_UPSTREAM_MODE: how the gateway proxy reaches notebook pods.
# "pod_ip"   — use the raw pod IP from K8s API (requires network access to pod CIDR).
# "nodeport" — use the NodePort service address (k3s_host:nodeport).
# Read once at module import time; fail fast on unknown values so misconfiguration
# surfaces at startup, not on the first proxied request.
_UPSTREAM_MODE = os.getenv("SP_NOTEBOOK_UPSTREAM_MODE", "nodeport")
if _UPSTREAM_MODE not in {"pod_ip", "nodeport"}:
    raise RuntimeError(
        f"Invalid SP_NOTEBOOK_UPSTREAM_MODE: {_UPSTREAM_MODE!r}. "
        "Allowed values: 'pod_ip', 'nodeport'."
    )


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
) -> dict:
    """Build the pod spec dict for the Kubernetes API.

    Injects SP_SESSION_JWT and SP_SESSION_ID into the pod env.
    Does NOT inject SP_API_KEY (replaced by per-session JWT) or SP_ACCESS_TOKEN
    (removed in R2 — the gateway proxy is the sole auth gate; the pod runs --no-token).
    --token-password is removed unconditionally; the pod runs --no-token always.
    --base-url /notebook/{session_id} tells marimo to emit asset URLs under that prefix.
    access_token is stored on the DB row as the gateway proxy cookie value but is NOT
    injected into the pod env or CLI.
    # TODO(R3): Add NodePort retirement, securityContext hardening, per-pod ServiceAccount.
    """
    env = [
        {"name": "SP_GATEWAY_URL", "value": gateway_url},
        {"name": "SP_PROJECT_ID", "value": project_id or ""},
        {"name": "SP_BRANCH", "value": branch},
        {"name": "SP_USER_ID", "value": user_id},
        {"name": "SP_ORG_ID", "value": org_id},
        {"name": "SP_SESSION_JWT", "value": session_jwt},
        {"name": "SP_SESSION_ID", "value": session_id},
    ]
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
            "containers": [{
                "name": "notebook",
                "image": f"docker.io/library/{image}" if ":" in image and "/" not in image else image,
                "imagePullPolicy": "IfNotPresent",
                # --no-token: pod runs without marimo's built-in auth; the gateway proxy is the
                # sole auth gate. --token-password branch removed unconditionally in R2.
                # --base-url: tells marimo to emit asset/WS URLs under /notebook/{session_id}.
                "command": [
                    "sp", "edit", "--host", "0.0.0.0", "--port", "2718", "--headless",
                    "--no-token", "--base-url", f"/notebook/{session_id}",
                    "/workspace",
                ],
                "ports": [{"containerPort": 2718}],
                "env": env,
                "resources": {
                    "requests": {"memory": "512Mi", "cpu": "500m"},
                    "limits": {"memory": "2Gi", "cpu": "2"},
                },
                "readinessProbe": {
                    "tcpSocket": {"port": 2718},
                    "initialDelaySeconds": 5,
                    "periodSeconds": 5,
                    "failureThreshold": 20,
                },
                "livenessProbe": {
                    "tcpSocket": {"port": 2718},
                    "initialDelaySeconds": 30,
                    "periodSeconds": 30,
                    "failureThreshold": 5,
                },
            }],
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
    """Manages notebook pods via the Kubernetes API."""

    def __init__(self, namespace: str | None = None, image: str | None = None):
        self._namespace = namespace or os.getenv("SP_K8S_NAMESPACE", "default")
        self._image = image or os.getenv("SP_NOTEBOOK_IMAGE", "signalpilot-notebook:latest")
        self._client = None
        self._core_api = None

    async def _ensure_client(self):
        if self._client is not None:
            return
        from kubernetes_asyncio import client, config

        kubeconfig = os.getenv("KUBECONFIG")
        k8s_host = os.getenv("SP_K8S_HOST")
        try:
            if kubeconfig and os.path.exists(kubeconfig):
                await config.load_kube_config(config_file=kubeconfig)
                if k8s_host:
                    client.Configuration.get_default_copy().host = k8s_host
            else:
                config.load_incluster_config()
        except Exception as e:
            logger.warning("K8s config failed: %s — orchestrator disabled", e)
            return
        self._client = client.ApiClient()
        self._core_api = client.CoreV1Api(self._client)
        logger.info("K8s orchestrator connected (namespace=%s)", self._namespace)

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
    ) -> PodInfo:
        await self._ensure_client()
        if not self._core_api:
            raise RuntimeError("K8s orchestrator not available")

        manifest = _pod_manifest(
            pod_name=pod_name,
            namespace=self._namespace,
            image=image or self._image,
            user_id=user_id,
            org_id=org_id,
            project_id=project_id,
            branch=branch,
            gateway_url=gateway_url,
            session_jwt=session_jwt,
            session_id=session_id,
            access_token=access_token,
        )
        await self._core_api.create_namespaced_pod(
            namespace=self._namespace, body=manifest
        )
        # H-1 fix: only create the NodePort Service in 'nodeport' mode (dev-only docker-compose).
        # In 'pod_ip' mode (cloud/k8s), the gateway reaches pods directly via pod IP — no
        # NodePort service is needed or created. Creating one would expose the unauthenticated
        # marimo pod (--no-token) to anyone who can reach the k3s host's high-port range.
        #
        # IMPORTANT: 'nodeport' mode is for local docker-compose dev ONLY.
        # It MUST NOT be used in cloud deployments — set SP_NOTEBOOK_UPSTREAM_MODE=pod_ip in cloud.
        # The fail-fast check below enforces this.
        if _UPSTREAM_MODE == "nodeport":
            from ..runtime.mode import is_cloud_mode as _is_cloud_mode
            if _is_cloud_mode():
                raise RuntimeError(
                    "SP_NOTEBOOK_UPSTREAM_MODE=nodeport is forbidden in cloud mode. "
                    "Set SP_NOTEBOOK_UPSTREAM_MODE=pod_ip for cloud/k8s deployments."
                )
            svc_manifest = {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": pod_name, "namespace": self._namespace},
                "spec": {
                    "type": "NodePort",
                    "selector": {"app": "signalpilot-notebook", "signalpilot.ai/user": user_id[:63]},
                    "ports": [{"port": 2718, "targetPort": 2718, "protocol": "TCP", "nodePort": 30000 + (hash(pod_name) % 100)}],
                },
            }
            try:
                await self._core_api.create_namespaced_service(namespace=self._namespace, body=svc_manifest)
            except Exception as e:
                if "AlreadyExists" not in str(e):
                    logger.warning("Failed to create service for pod %s", pod_name)
            logger.info("Created pod + NodePort service %s (dev-only nodeport mode)", pod_name)
        else:
            # pod_ip mode: no NodePort service created. Gateway uses pod IP directly.
            logger.info("Created pod %s for user %s (pod_ip mode, no NodePort service)", pod_name, user_id)
        return PodInfo(name=pod_name, ip=None, status="pending")

    async def delete_pod(self, pod_name: str) -> bool:
        await self._ensure_client()
        if not self._core_api:
            return False
        deleted = False
        try:
            await self._core_api.delete_namespaced_pod(
                name=pod_name, namespace=self._namespace, grace_period_seconds=5,
            )
            deleted = True
        except Exception as e:
            if "404" not in str(e) and "Not Found" not in str(e):
                logger.warning("Failed to delete pod %s: %s", pod_name, e)
        try:
            await self._core_api.delete_namespaced_service(name=pod_name, namespace=self._namespace)
        except Exception:
            pass
        if deleted:
            logger.info("Deleted pod + service %s", pod_name)
        return deleted

    async def get_pod(self, pod_name: str) -> PodInfo | None:
        await self._ensure_client()
        if not self._core_api:
            return None
        try:
            resp = await self._core_api.read_namespaced_pod(
                name=pod_name, namespace=self._namespace
            )
            pod = resp.to_dict()
            return PodInfo(
                name=pod_name,
                ip=_parse_pod_ip(pod),
                status=_parse_pod_status(pod),
            )
        except Exception:
            return None

    async def is_pod_alive(self, pod_name: str) -> bool:
        """Return True iff the pod exists and its phase is 'running'."""
        pod = await self.get_pod(pod_name)
        return pod is not None and pod.status == "running"

    async def wait_for_ready(self, pod_name: str, timeout: int = 60) -> PodInfo:
        """Poll until pod has an IP and is running, or timeout.

        Returns PodInfo with:
        - ip: legacy {k3s_host}:{nodeport} address (TODO: remove in R3).
        - internal_ip: the value the gateway proxy should use to reach the pod.
          In 'pod_ip' mode this is the raw pod IP; in 'nodeport' mode it mirrors ip.
        Note (R2, not fixed): NodePort assignment uses hash(pod_name) % 100 which is
        non-deterministic across Python runs (PYTHONHASHSEED) and can collide. R3 cleanup.
        """
        await self._ensure_client()
        if not self._core_api:
            raise RuntimeError("K8s orchestrator not available")

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            pod = await self.get_pod(pod_name)
            if pod and pod.ip and pod.status == "running":
                node_port = await self._get_node_port(pod_name)
                k3s_host = os.getenv("SP_K8S_HOST", "").replace("https://", "").split(":")[0] or "k3s"
                reachable_ip = f"{k3s_host}:{node_port}" if node_port else pod.ip
                # Determine internal_ip based on upstream mode (read once at startup).
                if _UPSTREAM_MODE == "pod_ip":
                    internal_ip: str | None = pod.ip  # raw pod IP from K8s API
                else:
                    internal_ip = reachable_ip  # nodeport fallback
                return PodInfo(name=pod.name, ip=reachable_ip, status="running", internal_ip=internal_ip)
            if pod and pod.status in ("failed", "succeeded"):
                raise RuntimeError(f"Pod {pod_name} entered terminal state: {pod.status}")
            await asyncio.sleep(2)
        raise TimeoutError(f"Pod {pod_name} not ready after {timeout}s")

    async def _get_node_port(self, svc_name: str) -> int | None:
        try:
            svc = await self._core_api.read_namespaced_service(name=svc_name, namespace=self._namespace)
            ports = svc.to_dict().get("spec", {}).get("ports", [])
            if ports:
                return ports[0].get("node_port")
        except Exception:
            pass
        return None

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
            self._core_api = None
