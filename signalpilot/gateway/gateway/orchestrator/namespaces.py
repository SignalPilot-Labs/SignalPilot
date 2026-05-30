"""Per-org Kubernetes namespace bootstrap — pure module, no FastAPI/DB imports.

Provides idempotent creation of per-org namespaces with default-deny NetworkPolicy,
gateway-access NetworkPolicy, ResourceQuota, LimitRange, and scoped RBAC.

Dependency direction: this module takes K8s API clients as arguments and has
no knowledge of gateway config or FastAPI. Callers (kubernetes.py) pass in clients.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

MANAGED_BY_LABEL = "signalpilot.ai/managed-by"
ORG_LABEL = "signalpilot.ai/org"
DEFAULT_NAMESPACE_PREFIX = "sp-nb"

DEFAULT_QUOTA: dict = {
    "pods": "20",
    "requests.cpu": "10",
    "requests.memory": "32Gi",
    "limits.cpu": "20",
    "limits.memory": "64Gi",
    "services": "0",
    "services.nodeports": "0",
    "persistentvolumeclaims": "0",
}

DEFAULT_LIMIT_RANGE: dict = {
    "limits": [
        {
            "type": "Container",
            "max": {"cpu": "4", "memory": "8Gi"},
            "maxLimitRequestRatio": {"cpu": "4", "memory": "4"},
        }
    ]
}

# Per-org asyncio locks to prevent intra-process bootstrap races.
# Cross-replica races rely on Kubernetes 409 AlreadyExists responses.
_org_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# Egress CIDRs that must never be reachable from user pods.
# 169.254.0.0/16 covers AWS IMDSv4 and link-local; fd00:ec2::/32 covers IMDSv6;
# 127.0.0.0/8 covers loopback.
_MANDATORY_EGRESS_EXCEPT: list[str] = [
    "169.254.0.0/16",
    "fd00:ec2::/32",
    "127.0.0.0/8",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

_DNS_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$")
_DNS_SAFE_CHAR_RE = re.compile(r"[^a-z0-9\-]")


def _stable_hash(value: str) -> str:
    """Return first 16 hex characters of SHA-256 of value. Never uses hash()."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _sanitize_prefix(prefix: str) -> str:
    """Lowercase and strip non-DNS-safe characters from prefix."""
    sanitized = _DNS_SAFE_CHAR_RE.sub("-", prefix.lower()).strip("-")
    if not sanitized:
        raise ValueError(f"Namespace prefix {prefix!r} contains no DNS-safe characters")
    return sanitized


def _is_409(exc: Exception) -> bool:
    """Return True if the exception represents a K8s 409 AlreadyExists error."""
    return getattr(exc, "status", None) == 409


async def _create_idempotent(coro_factory, resource_description: str) -> None:
    """Call coro_factory() and swallow 409 AlreadyExists. Raise on all other errors."""
    try:
        await coro_factory()
    except Exception as exc:
        if _is_409(exc):
            logger.debug("Resource already exists (409): %s", resource_description)
        else:
            logger.error("Failed to create %s: %s", resource_description, exc)
            raise


# ── Public API ─────────────────────────────────────────────────────────────────


def namespace_for_org(org_id: str, *, prefix: str) -> str:
    """Return the deterministic Kubernetes namespace name for an org.

    Format: ``{sanitized_prefix}-{sha256(org_id)[:16]}``.

    DNS-1123 label rules enforced: lowercase, [a-z0-9-], max 63 chars.
    Empty org_id raises ValueError.
    """
    if not org_id:
        raise ValueError("org_id must not be empty")
    sanitized = _sanitize_prefix(prefix)
    sha = _stable_hash(org_id)
    name = f"{sanitized}-{sha}"
    if len(name) > 63:
        raise ValueError(
            f"Namespace name {name!r} exceeds 63 characters (DNS-1123 limit). "
            "Shorten the prefix."
        )
    return name


async def ensure_org_namespace(
    core_api,
    networking_api,
    rbac_api,
    *,
    org_id: str,
    namespace: str,
    gateway_namespace: str,
    gateway_pod_selector: dict,
    gateway_port: int,
    egress_cidr: str | None,
    gateway_service_account: str,
    skip_network_policy: bool = False,
) -> None:
    """Idempotently bootstrap a per-org Kubernetes namespace and all required resources.

    Creates in order, swallowing only 409 AlreadyExists:
    1. Namespace
    2. NetworkPolicy default-deny (skipped if skip_network_policy)
    3. NetworkPolicy allow-gateway-ingress-and-egress (skipped if skip_network_policy)
    4. ResourceQuota default-quota
    5. LimitRange default-limits
    6. Role signalpilot-gateway-org-role
    7. RoleBinding signalpilot-gateway-org-binding

    Uses a per-org asyncio.Lock to prevent intra-process bootstrap races.
    Cross-replica races are handled by swallowing 409 responses.
    Raises on any non-409 error — no silent fallback.
    """
    if not org_id:
        raise ValueError("org_id must not be empty")

    sha = _stable_hash(org_id)
    lock = _org_locks[org_id]

    async with lock:
        await _create_idempotent(
            lambda: core_api.create_namespace(body=_namespace_manifest(namespace, sha)),
            f"Namespace/{namespace}",
        )
        if skip_network_policy:
            logger.info("Skipping NetworkPolicy creation in local mode (SP_NOTEBOOK_NETWORK_POLICY=false)")
        if not skip_network_policy:
            await _create_idempotent(
                lambda: networking_api.create_namespaced_network_policy(
                    namespace=namespace,
                    body=_default_deny_policy(namespace),
                ),
                f"NetworkPolicy/default-deny in {namespace}",
            )
        if not skip_network_policy:
            await _create_idempotent(
                lambda: networking_api.create_namespaced_network_policy(
                    namespace=namespace,
                    body=_allow_gateway_policy(
                        namespace=namespace,
                        gateway_namespace=gateway_namespace,
                        gateway_pod_selector=gateway_pod_selector,
                        gateway_port=gateway_port,
                        egress_cidr=egress_cidr,
                    ),
                ),
                f"NetworkPolicy/allow-gateway-ingress-and-egress in {namespace}",
            )
        await _create_idempotent(
            lambda: core_api.create_namespaced_resource_quota(
                namespace=namespace,
                body=_resource_quota_manifest(namespace),
            ),
            f"ResourceQuota/default-quota in {namespace}",
        )
        await _create_idempotent(
            lambda: core_api.create_namespaced_limit_range(
                namespace=namespace,
                body=_limit_range_manifest(namespace),
            ),
            f"LimitRange/default-limits in {namespace}",
        )
        await _create_idempotent(
            lambda: rbac_api.create_namespaced_role(
                namespace=namespace,
                body=_gateway_org_role(namespace),
            ),
            f"Role/signalpilot-gateway-org-role in {namespace}",
        )
        await _create_idempotent(
            lambda: rbac_api.create_namespaced_role_binding(
                namespace=namespace,
                body=_gateway_org_role_binding(
                    namespace=namespace,
                    gateway_namespace=gateway_namespace,
                    gateway_service_account=gateway_service_account,
                ),
            ),
            f"RoleBinding/signalpilot-gateway-org-binding in {namespace}",
        )

    logger.info(
        "Namespace bootstrap complete: namespace=%s org_id=%s", namespace, org_id
    )


# ── Manifest builders ──────────────────────────────────────────────────────────


def _namespace_manifest(namespace: str, sha: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": namespace,
            "labels": {
                ORG_LABEL: sha,
                MANAGED_BY_LABEL: "gateway",
                # Required by NetworkPolicy namespaceSelector matching.
                "kubernetes.io/metadata.name": namespace,
                # Required by F-12 admission policy namespace selector.
                # The ValidatingAdmissionPolicy (and Kyverno fallback) match on
                # signalpilot.dev/tenant=user to scope enforcement to tenant namespaces only.
                "signalpilot.dev/tenant": "user",
            },
        },
    }


def _default_deny_policy(namespace: str) -> dict:
    """Policy 1: deny all ingress and egress by omission of rules."""
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": "default-deny",
            "namespace": namespace,
        },
        "spec": {
            "podSelector": {},
            "policyTypes": ["Ingress", "Egress"],
        },
    }


def _filter_except_entries(egress_cidr: str, candidates: list[str]) -> list[str]:
    """Return only candidates that are strict subnets of egress_cidr, excluding exact equality."""
    parent = ipaddress.ip_network(egress_cidr, strict=False)
    result = []
    for entry in candidates:
        candidate = ipaddress.ip_network(entry, strict=False)
        if candidate == parent:
            continue
        try:
            # subnet_of raises TypeError when address families differ (IPv4 vs IPv6).
            # We catch it defensively and skip the entry.
            is_subnet: bool = candidate.subnet_of(parent)  # type: ignore[arg-type]
            if is_subnet:
                result.append(entry)
        except TypeError:
            continue
    return result


def _allow_gateway_policy(
    *,
    namespace: str,
    gateway_namespace: str,
    gateway_pod_selector: dict,
    gateway_port: int,
    egress_cidr: str | None,
    extra_egress_except: list[str] | None = None,
) -> dict:
    """Policy 2: allow ingress from gateway and restricted egress."""
    egress_rules = [
        # DNS via kube-dns — separate `to:` entry (NOT merged with coredns)
        {
            "to": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                    },
                    "podSelector": {
                        "matchLabels": {"k8s-app": "kube-dns"}
                    },
                }
            ],
            "ports": [
                {"protocol": "UDP", "port": 53},
                {"protocol": "TCP", "port": 53},
            ],
        },
        # DNS via coredns — separate `to:` entry (union, not intersection)
        {
            "to": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                    },
                    "podSelector": {
                        "matchLabels": {"k8s-app": "coredns"}
                    },
                }
            ],
            "ports": [
                {"protocol": "UDP", "port": 53},
                {"protocol": "TCP", "port": 53},
            ],
        },
        # Gateway callback
        {
            "to": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": gateway_namespace}
                    },
                    "podSelector": {
                        "matchLabels": gateway_pod_selector,
                    },
                }
            ],
            "ports": [
                {"protocol": "TCP", "port": gateway_port},
            ],
        },
    ]

    if egress_cidr is not None:
        all_except_candidates = list(_MANDATORY_EGRESS_EXCEPT)
        if extra_egress_except:
            all_except_candidates.extend(extra_egress_except)
        filtered_except = _filter_except_entries(egress_cidr, all_except_candidates)
        if filtered_except:
            ip_block: dict = {"cidr": egress_cidr, "except": filtered_except}
        else:
            ip_block = {"cidr": egress_cidr}
        egress_rules.append(
            {
                "to": [{"ipBlock": ip_block}],
                "ports": [{"protocol": "TCP", "port": 443}],
            }
        )

    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": "allow-gateway-ingress-and-egress",
            "namespace": namespace,
        },
        "spec": {
            "podSelector": {},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [
                {
                    "from": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": gateway_namespace
                                }
                            },
                            "podSelector": {
                                "matchLabels": gateway_pod_selector,
                            },
                        }
                    ],
                    "ports": [{"protocol": "TCP", "port": 2718}],
                }
            ],
            "egress": egress_rules,
        },
    }


def _resource_quota_manifest(namespace: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "ResourceQuota",
        "metadata": {
            "name": "default-quota",
            "namespace": namespace,
        },
        "spec": {"hard": DEFAULT_QUOTA},
    }


def _limit_range_manifest(namespace: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "LimitRange",
        "metadata": {
            "name": "default-limits",
            "namespace": namespace,
        },
        "spec": DEFAULT_LIMIT_RANGE,
    }


def _gateway_org_role(namespace: str) -> dict:
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "Role",
        "metadata": {
            "name": "signalpilot-gateway-org-role",
            "namespace": namespace,
        },
        "rules": [
            {
                "apiGroups": [""],
                "resources": ["pods", "resourcequotas", "limitranges"],
                "verbs": ["create", "get", "list", "delete", "patch"],
            },
            {
                "apiGroups": [""],
                "resources": ["pods/log", "pods/status"],
                "verbs": ["get", "list"],
            },
            # R4: pods/exec create — required for gateway-side workspace sync via tar.
            # Mitigated by: pod_exec_io is the sole caller (C4 AST test), container
            # hardcoded to "notebook", paths confined to /workspace/, argv is a list literal.
            # R9 F-21: RBAC cannot prefix-match pod names, so the broad pods/exec grant is
            # narrowed by Kyverno admission policy. Operator MUST also deploy
            # admission/restrict-pod-exec-kyverno.yaml; it enforces pod-name shape
            # (^nb-[0-9a-f]{12}$) and container=notebook as defense-in-depth.
            {
                "apiGroups": [""],
                "resources": ["pods/exec"],
                "verbs": ["create"],
            },
            # R4 F-6: gateway creates per-session Secrets (sp-jwt-<pod_name>) to stage
            # the JWT into the pod via initContainer → emptyDir. Scoped to this namespace
            # Role — NOT the cluster role.
            # R7 F-13: "list" added for gc_orphan_jwt_secrets — no other code path
            # lists Secrets in tenant namespaces; this verb is purely for the GC loop.
            {
                "apiGroups": [""],
                "resources": ["secrets"],
                "verbs": ["create", "get", "list", "patch", "delete"],
            },
            {
                "apiGroups": ["networking.k8s.io"],
                "resources": ["networkpolicies"],
                "verbs": ["create", "get", "list", "delete", "patch"],
            },
        ],
    }


def _gateway_org_role_binding(
    *,
    namespace: str,
    gateway_namespace: str,
    gateway_service_account: str,
) -> dict:
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": {
            "name": "signalpilot-gateway-org-binding",
            "namespace": namespace,
        },
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "Role",
            "name": "signalpilot-gateway-org-role",
        },
        "subjects": [
            {
                "kind": "ServiceAccount",
                "name": gateway_service_account,
                "namespace": gateway_namespace,
            }
        ],
    }
