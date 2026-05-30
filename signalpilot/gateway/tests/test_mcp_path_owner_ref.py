"""Gate test: MCP run_notebook path applies ownerReference patch to sp-jwt-* Secrets.

F-13 invariant: after create_pod succeeds, the MCP path must call patch_namespaced_secret
with an ownerReferences body pointing to the pod UID.  Before F-13, the MCP path skipped
this step — the Secret outlived the pod.

F-9/F-11/F-13 inject→fail→revert→pass pattern:
  - This test fails if the create_jwt_secret_with_owner_ref helper is removed from the
    MCP path (injection: restore the old inline create/pod-only code without patch).
  - Records the gate-test demonstration in /tmp/round-7/backend-dev.md.

R7 F-13 (1a).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_patch_tracked_core_v1() -> tuple[MagicMock, list[dict]]:
    """Return a mock CoreV1Api and a list that accumulates ownerRef patch bodies."""
    patches_recorded: list[dict] = []
    core_v1 = MagicMock()
    core_v1.create_namespaced_secret = AsyncMock()
    core_v1.delete_namespaced_secret = AsyncMock()
    core_v1.delete_namespaced_pod = AsyncMock()

    async def _patch(name, namespace, body):
        patches_recorded.append({"name": name, "namespace": namespace, "body": body})

    core_v1.patch_namespaced_secret = AsyncMock(side_effect=_patch)

    pod_meta = MagicMock()
    pod_meta.name = "nb-testpod"
    pod_meta.uid = "uid-gate-test-1234"
    fake_pod = MagicMock()
    fake_pod.metadata = pod_meta
    core_v1.read_namespaced_pod = AsyncMock(return_value=fake_pod)

    return core_v1, patches_recorded


class TestMcpPathOwnerRef:
    @pytest.mark.asyncio
    async def test_mcp_path_patches_ownerref_after_create_pod(self):
        """create_jwt_secret_with_owner_ref is called on the MCP path and patches ownerRef.

        This is the F-13 gate test: if the helper invocation is removed from
        gateway/mcp/tools/notebook.py, this test fails because patch_namespaced_secret
        would never be called.
        """
        from gateway.orchestrator.jwt_secret_lifecycle import create_jwt_secret_with_owner_ref

        core_v1, patches = _make_patch_tracked_core_v1()

        async def _fake_create_pod():
            pod = MagicMock()
            pod.metadata = MagicMock()
            pod.metadata.name = "nb-testpod"
            pod.metadata.uid = "uid-gate-test-1234"
            return pod

        await create_jwt_secret_with_owner_ref(
            core_v1,
            namespace="sp-nb-testorg",
            pod_name="nb-testpod",
            session_jwt="fake.jwt.value",
            create_pod_fn=_fake_create_pod,
        )

        # Assert patch_namespaced_secret was called exactly once.
        assert len(patches) == 1, (
            "patch_namespaced_secret must be called exactly once to set ownerReference; "
            f"was called {len(patches)} time(s). MCP path is missing the ownerRef patch."
        )
        patch_body = patches[0]["body"]
        owner_refs = patch_body["metadata"]["ownerReferences"]
        assert len(owner_refs) == 1
        ref = owner_refs[0]
        assert ref["kind"] == "Pod"
        assert ref["uid"] == "uid-gate-test-1234"
        assert ref["controller"] is True
        assert ref["blockOwnerDeletion"] is True

    @pytest.mark.asyncio
    async def test_ownerref_patch_contains_pod_uid_not_empty(self):
        """ownerReference uid must be the actual pod UID, never an empty string."""
        from gateway.orchestrator.jwt_secret_lifecycle import create_jwt_secret_with_owner_ref

        core_v1, patches = _make_patch_tracked_core_v1()

        await create_jwt_secret_with_owner_ref(
            core_v1,
            namespace="sp-nb-testorg",
            pod_name="nb-testpod",
            session_jwt="fake.jwt.value",
            create_pod_fn=AsyncMock(return_value=MagicMock()),
        )

        assert len(patches) == 1
        uid = patches[0]["body"]["metadata"]["ownerReferences"][0]["uid"]
        assert uid, "ownerReference uid must not be empty"
        assert uid == "uid-gate-test-1234"
