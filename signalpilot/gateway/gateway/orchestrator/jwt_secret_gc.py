"""Periodic GC for orphaned sp-jwt-* Secrets in tenant namespaces.

An 'orphan' Secret is one that:
  - Has the sp-jwt- prefix (created by the gateway JWT staging path).
  - Has no ownerReferences (the normal kube GC path is therefore disabled).
  - Is older than max_age_seconds (default 15 min) — guards the creation race window.
  - Has no corresponding Pod with a matching name.

Race-window rationale: between create_namespaced_secret and the ownerRef patch, the
gateway process can be killed (OOM, SIGKILL).  The inline try/except cleanup in
jwt_secret_lifecycle.py only fires when an exception propagates in the same process run.
This GC catches leaks that survive across gateway restarts.

Design choice — in-process loop, not CronJob:
  The gateway already holds the K8s client with the right RBAC and the right namespace
  list (KubernetesOrchestrator).  A CronJob would need its own ServiceAccount, image,
  and ClusterRoleBinding, tripling the review surface.  Trade-off: if all gateway replicas
  are down, GC pauses.  Acceptable — Secrets are not externally readable (RBAC +
  automountServiceAccountToken:false), so a missed GC run causes namespace clutter, not
  a security incident.

R7 F-13 (1c).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .kubernetes import KubernetesOrchestrator

logger = logging.getLogger(__name__)

SP_JWT_SECRET_PREFIX = "sp-jwt-"
_TENANT_NAMESPACE_LABEL = "signalpilot.dev/tenant=user"


async def gc_orphan_jwt_secrets(
    orch: KubernetesOrchestrator,
    *,
    max_age_seconds: int = 900,
) -> int:
    """Delete sp-jwt-* Secrets with no ownerRef, no live Pod, older than max_age_seconds.

    Args:
        orch: Initialised KubernetesOrchestrator (provides K8s API access and namespace list).
        max_age_seconds: Minimum age before a Secret is eligible for GC. Default 900 (15 min).

    Returns:
        Count of Secrets deleted this run (for logging/test assertions).

    Raises:
        Any K8s exception other than 404 on individual pod-existence checks.
        Callers (the loop in main.py) are expected to catch and log; this function
        does NOT silently swallow unexpected errors.
    """
    from kubernetes_asyncio.client.exceptions import ApiException

    await orch._ensure_client()  # type: ignore[attr-defined]
    core_v1 = orch._core_api  # type: ignore[attr-defined]

    now = datetime.now(UTC)
    deleted_count = 0

    # Iterate only tenant namespaces — DO NOT list Secrets cluster-wide.
    ns_response = await core_v1.list_namespace(label_selector=_TENANT_NAMESPACE_LABEL)
    for ns_obj in ns_response.items:
        ns_name: str = ns_obj.metadata.name

        secret_response = await core_v1.list_namespaced_secret(namespace=ns_name)
        for secret in secret_response.items:
            deleted_count += await _evaluate_secret(
                core_v1=core_v1,
                secret=secret,
                namespace=ns_name,
                now=now,
                max_age_seconds=max_age_seconds,
                api_exception_cls=ApiException,
            )

    return deleted_count


async def _evaluate_secret(
    *,
    core_v1: object,
    secret: object,
    namespace: str,
    now: datetime,
    max_age_seconds: int,
    api_exception_cls: type[Exception],
) -> int:
    """Evaluate one Secret for GC eligibility. Returns 1 if deleted, 0 otherwise."""
    name: str = secret.metadata.name  # type: ignore[attr-defined]

    # Guard 1: prefix filter — unconditionally skip non-sp-jwt- Secrets.
    if not name.startswith(SP_JWT_SECRET_PREFIX):
        return 0

    # Guard 2: ownerReferences present — kube GC handles it; do not race.
    if secret.metadata.owner_references:  # type: ignore[attr-defined]
        return 0

    # Guard 3: age floor — skip Secrets younger than max_age_seconds.
    creation_ts: datetime = secret.metadata.creation_timestamp  # type: ignore[attr-defined]
    age_seconds = (now - creation_ts).total_seconds()
    if age_seconds < max_age_seconds:
        return 0

    # Guard 4: pod existence check — skip if a Pod with matching name is alive.
    expected_pod_name = name.removeprefix(SP_JWT_SECRET_PREFIX)
    try:
        await core_v1.read_namespaced_pod(  # type: ignore[attr-defined]
            name=expected_pod_name,
            namespace=namespace,
        )
        # Pod exists — do nothing; ownerRef patch may still be in-flight.
        return 0
    except api_exception_cls as exc:
        if exc.status != 404:  # type: ignore[attr-defined]
            raise  # Non-404 errors are unexpected — propagate.
        # Pod is gone (404) — proceed to delete.

    # Delete the orphan Secret.  Treat 404 as success (concurrent GC from another replica).
    try:
        await core_v1.delete_namespaced_secret(  # type: ignore[attr-defined]
            name=name,
            namespace=namespace,
        )
        logger.info(
            "GC: deleted orphan Secret %s/%s (age=%.0fs, no pod=%s)",
            namespace,
            name,
            age_seconds,
            expected_pod_name,
        )
        return 1
    except api_exception_cls as exc:
        if exc.status == 404:  # type: ignore[attr-defined]
            # Another replica already deleted it — count as deletion.
            logger.info(
                "GC: Secret %s/%s already deleted by another replica (404 on delete)",
                namespace,
                name,
            )
            return 1
        raise
