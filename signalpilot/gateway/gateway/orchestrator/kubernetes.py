"""Kubernetes orchestrator — creates/deletes notebook pods via K8s API.

Works with K3s locally and EKS in production. Same code path.
"""

from __future__ import annotations

import asyncio
import logging
import os

from . import NotebookOrchestrator, PodInfo

logger = logging.getLogger(__name__)


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
    api_key: str | None,
) -> dict:
    """Build the pod spec dict for the Kubernetes API."""
    env = [
        {"name": "SP_GATEWAY_URL", "value": gateway_url},
        {"name": "SP_PROJECT_ID", "value": project_id or ""},
        {"name": "SP_BRANCH", "value": branch},
        {"name": "SP_USER_ID", "value": user_id},
        {"name": "SP_ORG_ID", "value": org_id},
    ]
    if api_key:
        env.append({"name": "SP_API_KEY", "value": api_key})

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
                "image": image,
                "imagePullPolicy": "IfNotPresent",
                "ports": [{"containerPort": 2718}],
                "env": env,
                "resources": {
                    "requests": {"memory": "512Mi", "cpu": "500m"},
                    "limits": {"memory": "2Gi", "cpu": "2"},
                },
                "readinessProbe": {
                    "httpGet": {"path": "/api/health", "port": 2718},
                    "initialDelaySeconds": 5,
                    "periodSeconds": 5,
                    "failureThreshold": 12,
                },
                "livenessProbe": {
                    "httpGet": {"path": "/api/health", "port": 2718},
                    "initialDelaySeconds": 15,
                    "periodSeconds": 30,
                },
            }],
            "restartPolicy": "Never",
            "terminationGracePeriodSeconds": 5,
        },
    }


def _parse_pod_status(pod: dict) -> str:
    phase = pod.get("status", {}).get("phase", "Unknown")
    return phase.lower()


def _parse_pod_ip(pod: dict) -> str | None:
    return pod.get("status", {}).get("podIP")


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
        api_key: str | None,
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
            api_key=api_key,
        )
        resp = await self._core_api.create_namespaced_pod(
            namespace=self._namespace, body=manifest
        )
        logger.info("Created pod %s for user %s", pod_name, user_id)
        return PodInfo(
            name=pod_name,
            ip=None,
            status="pending",
        )

    async def delete_pod(self, pod_name: str) -> bool:
        await self._ensure_client()
        if not self._core_api:
            return False
        try:
            await self._core_api.delete_namespaced_pod(
                name=pod_name,
                namespace=self._namespace,
                grace_period_seconds=5,
            )
            logger.info("Deleted pod %s", pod_name)
            return True
        except Exception as e:
            if "404" in str(e) or "Not Found" in str(e):
                return False
            logger.warning("Failed to delete pod %s: %s", pod_name, e)
            return False

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

    async def wait_for_ready(self, pod_name: str, timeout: int = 60) -> PodInfo:
        """Poll until pod has an IP and is running, or timeout."""
        await self._ensure_client()
        if not self._core_api:
            raise RuntimeError("K8s orchestrator not available")

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            pod = await self.get_pod(pod_name)
            if pod and pod.ip and pod.status == "running":
                return pod
            if pod and pod.status in ("failed", "succeeded"):
                raise RuntimeError(f"Pod {pod_name} entered terminal state: {pod.status}")
            await asyncio.sleep(2)
        raise TimeoutError(f"Pod {pod_name} not ready after {timeout}s")

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
            self._core_api = None
