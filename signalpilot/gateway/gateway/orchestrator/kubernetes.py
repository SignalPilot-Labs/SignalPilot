"""Kubernetes client for eval workloads.

Notebook Runtime v2 removed notebook pods entirely — notebooks run on the
sandbox runtime. What remains here is exactly the surface the eval Kubernetes
backend needs: an authenticated API client, per-org tenant namespace bootstrap
(quota / limits / network policy / scoped RBAC via namespaces.py), and the
gVisor scheduling block eval pods share.

Works with K3s locally and EKS in production. Same code path.
"""

from __future__ import annotations

import logging
import os
import re

from .namespaces import ensure_org_namespace, namespace_for_org

logger = logging.getLogger(__name__)

# Sandbox runtime + scheduling for eval pods. On EKS they run under gVisor
# (runsc) on a dedicated tainted/labeled node group; emit runtimeClassName only
# when set so non-gVisor clusters (local/dev) still work. Empty disables it.
_SANDBOX_RUNTIME_CLASS = os.getenv("SP_NOTEBOOK_RUNTIME_CLASS", "").strip()
_SANDBOX_NODE_LABEL_KEY = os.getenv("SP_NOTEBOOK_NODE_LABEL_KEY", "signalpilot.ai/notebook").strip()
_SANDBOX_NODE_LABEL_VALUE = os.getenv("SP_NOTEBOOK_NODE_LABEL_VALUE", "true").strip()

_K8S_LABEL_INVALID_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


def _k8s_label_value(value: str, fallback: str) -> str:
    """Return a Kubernetes-safe label value while preserving readability."""
    label = _K8S_LABEL_INVALID_CHARS.sub("-", value.strip())[:63]
    label = label.strip("-_.")
    if label:
        return label
    return fallback[:63].strip("-_.") or "unknown"


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


def sandbox_scheduling() -> dict:
    """runtimeClassName + node pinning for sandboxed workload pods.

    Empty when SP_NOTEBOOK_RUNTIME_CLASS is unset so clusters without gVisor
    (local/dev) still schedule.
    """
    if not _SANDBOX_RUNTIME_CLASS:
        return {}
    return {
        "runtimeClassName": _SANDBOX_RUNTIME_CLASS,
        "nodeSelector": {_SANDBOX_NODE_LABEL_KEY: _SANDBOX_NODE_LABEL_VALUE},
        "tolerations": [
            {
                "key": _SANDBOX_NODE_LABEL_KEY,
                "operator": "Equal",
                "value": _SANDBOX_NODE_LABEL_VALUE,
                "effect": "NoSchedule",
            }
        ],
    }


class KubernetesOrchestrator:
    """Authenticated K8s client + tenant namespace bootstrap for evals."""

    def __init__(self) -> None:
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
        # SP-SEC-009: extra Group subjects for the per-namespace RoleBinding (EC2 path).
        self._gateway_runtime_groups: tuple[str, ...] = ()

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
        self._gateway_runtime_groups = tuple(
            g.strip() for g in settings.sp_gateway_runtime_groups.split(",") if g.strip()
        )

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

    async def ensure_namespace(self, org_id: str) -> str:
        """Idempotently create the org's tenant namespace (+ quota/limits/netpol/RBAC).

        Returns the namespace name. Eval workloads stage per-run Secrets before
        their pods, so callers must call this first on a brand-new org.
        """
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
            gateway_runtime_groups=self._gateway_runtime_groups,
            skip_network_policy=skip_netpol,
        )
        return ns

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
            self._core_api = None
            self._networking_api = None
            self._rbac_api = None
