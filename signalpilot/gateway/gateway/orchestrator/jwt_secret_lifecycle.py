"""Shared helper for the JWT Secret + Pod creation lifecycle.

Both the HTTP path (gateway/api/notebook_sessions.py) and the MCP path
(gateway/mcp/tools/notebook.py) must: create the Secret, create the Pod,
then patch ownerReference so kube GC cleans up the Secret when the pod dies.

This helper owns that three-step contract.  Post-return invariant:
  - The Pod and Secret both exist, Secret has ownerReference pointing to Pod.
  - On any failure, cleanup is attempted and the original exception is re-raised.
  - Secret-create failure: just re-raise (nothing to clean up).
  - Pod-create or ownerRef-patch failure: delete Secret (and Pod if it exists), then re-raise.

R7 F-13 (1b): extracted to eliminate the two-callsite drift that caused the MCP
path to miss the ownerRef patch for an entire round.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

_OWNER_REF_API_VERSION = "v1"
_OWNER_REF_KIND = "Pod"


async def create_jwt_secret_with_owner_ref(
    core_v1: Any,
    *,
    namespace: str,
    pod_name: str,
    session_jwt: str,
    create_pod_fn: Callable[[], Awaitable[Any]],
) -> Any:
    """Create the sp-jwt-<pod_name> Secret, call create_pod_fn, then patch ownerRef.

    Args:
        core_v1: An initialised kubernetes_asyncio CoreV1Api client.
        namespace: Tenant namespace where both Secret and Pod live.
        pod_name: Name of the pod being created (also used to derive secret_name).
        session_jwt: Raw JWT string to store in the Secret (base64-encoded internally).
        create_pod_fn: Async callable that creates the Pod and returns the pod object.
            Called with no arguments; any required params must be captured in the closure.

    Returns:
        The pod object returned by create_pod_fn (a V1Pod or equivalent dict).

    Raises:
        Any exception raised during secret create, pod create, pod read, or ownerRef patch.
        On pod-create or patch failure, delete_namespaced_secret is called before re-raising.
    """
    from kubernetes_asyncio import client as k8s_client

    secret_name = f"sp-jwt-{pod_name}"

    # Step (a): create the Secret.  On failure, nothing to clean up — just re-raise.
    await core_v1.create_namespaced_secret(
        namespace=namespace,
        body=k8s_client.V1Secret(
            metadata=k8s_client.V1ObjectMeta(name=secret_name),
            type="Opaque",
            data={
                "session_jwt": base64.b64encode(session_jwt.encode()).decode(),
            },
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
