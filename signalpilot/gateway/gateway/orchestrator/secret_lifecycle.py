"""Per-pod credential Secret + Pod creation lifecycle for eval workloads.

The eval Kubernetes backend stages a per-run env Secret, creates the pod, then
patches ownerReference so kube GC removes the Secret with the pod that owns it.
Post-return invariant:
  - The Pod and Secret both exist, Secret has ownerReference pointing to Pod.
  - On any failure, cleanup is attempted and the original exception is re-raised.
  - Secret-create failure: just re-raise (nothing to clean up).
  - Pod-create or ownerRef-patch failure: delete Secret (and Pod if it exists),
    then re-raise.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

_OWNER_REF_API_VERSION = "v1"
_OWNER_REF_KIND = "Pod"


async def create_secret_with_owner_ref(
    core_v1: Any,
    *,
    namespace: str,
    secret_name: str,
    values: dict[str, str],
    pod_name: str,
    create_pod_fn: Callable[[], Awaitable[Any]],
) -> Any:
    """Create secret_name carrying `values`, call create_pod_fn, then patch ownerRef."""
    from kubernetes_asyncio import client as k8s_client
    from kubernetes_asyncio.client.exceptions import ApiException

    # The secret name is derived from the pod name, so a Secret from a prior
    # run can linger if its pod was deleted before kube GC removed the
    # owner-ref'd Secret, or if a previous create half-failed. Delete any stale
    # Secret first so create is idempotent (otherwise create 409s "already
    # exists" and the run never starts).
    try:
        await core_v1.delete_namespaced_secret(name=secret_name, namespace=namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise

    # Step (a): create the Secret.  On failure, nothing to clean up — just re-raise.
    await core_v1.create_namespaced_secret(
        namespace=namespace,
        body=k8s_client.V1Secret(
            metadata=k8s_client.V1ObjectMeta(name=secret_name),
            type="Opaque",
            data={k: base64.b64encode(v.encode()).decode() for k, v in values.items()},
        ),
    )

    # Secret now exists.  From here, any failure must attempt Secret deletion.
    try:
        # Step (b): create the Pod.
        pod_obj = await create_pod_fn()

        # Step (c): read the pod to get its UID (needed for ownerReference).
        raw_pod = await core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        pod_meta = raw_pod.metadata

        # Step (d): patch ownerReference so kube GC deletes the Secret with the Pod.
        await core_v1.patch_namespaced_secret(
            name=secret_name,
            namespace=namespace,
            body={
                "metadata": {
                    "ownerReferences": [
                        {
                            "apiVersion": _OWNER_REF_API_VERSION,
                            "kind": _OWNER_REF_KIND,
                            "name": pod_meta.name,
                            "uid": pod_meta.uid,
                            "controller": True,
                            "blockOwnerDeletion": True,
                        }
                    ]
                }
            },
        )
    except Exception:
        # Pod-create or ownerRef-patch failed.  Attempt cleanup of both Secret and Pod.
        # Pod may or may not exist at this point; treat 404 as success in both deletes.
        try:
            await core_v1.delete_namespaced_secret(name=secret_name, namespace=namespace)
        except Exception:
            logger.warning(
                "Failed to delete Secret %s/%s during cleanup after pod-create/patch failure",
                namespace,
                secret_name,
            )
        try:
            await core_v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
        except Exception:
            logger.warning(
                "Failed to delete Pod %s/%s during cleanup after pod-create/patch failure",
                namespace,
                pod_name,
            )
        raise  # Re-raise original exception; do NOT swallow.

    return pod_obj
