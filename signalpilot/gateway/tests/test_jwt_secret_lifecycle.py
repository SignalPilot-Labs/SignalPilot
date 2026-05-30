"""Unit tests for gateway.orchestrator.jwt_secret_lifecycle.

Verifies the contract: post-return, the Pod and Secret both exist with ownerRef set,
OR neither exists and an exception was raised.

R7 F-13 (1b).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


def _make_core_v1(
    *,
    create_secret_side_effect=None,
    create_pod_side_effect=None,
    read_pod_return=None,
    patch_secret_side_effect=None,
    delete_secret_side_effect=None,
    delete_pod_side_effect=None,
):
    """Build a mock CoreV1Api with configurable behaviour."""
    core_v1 = MagicMock()
    core_v1.create_namespaced_secret = AsyncMock(side_effect=create_secret_side_effect)
    core_v1.delete_namespaced_secret = AsyncMock(side_effect=delete_secret_side_effect)
    core_v1.delete_namespaced_pod = AsyncMock(side_effect=delete_pod_side_effect)
    core_v1.patch_namespaced_secret = AsyncMock(side_effect=patch_secret_side_effect)

    if read_pod_return is not None:
        core_v1.read_namespaced_pod = AsyncMock(return_value=read_pod_return)
    else:
        pod_meta = MagicMock()
        pod_meta.name = "nb-abc"
        pod_meta.uid = "pod-uid-1234"
        default_pod = MagicMock()
        default_pod.metadata = pod_meta
        core_v1.read_namespaced_pod = AsyncMock(return_value=default_pod)

    return core_v1


def _make_pod_fn(*, side_effect=None):
    if side_effect is not None:
        return AsyncMock(side_effect=side_effect)
    pod_result = MagicMock()
    return AsyncMock(return_value=pod_result)


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_happy_path_creates_secret_pod_and_patches_ownerref(self):
        """Happy path: create_secret → create_pod → read_pod → patch_secret (in order)."""
        from gateway.orchestrator.jwt_secret_lifecycle import create_jwt_secret_with_owner_ref

        core_v1 = _make_core_v1()
        create_pod_fn = _make_pod_fn()

        await create_jwt_secret_with_owner_ref(
            core_v1,
            namespace="sp-nb-org1",
            pod_name="nb-abc",
            session_jwt="test.jwt.token",
            create_pod_fn=create_pod_fn,
        )

        core_v1.create_namespaced_secret.assert_called_once()
        create_pod_fn.assert_called_once()
        core_v1.read_namespaced_pod.assert_called_once_with(
            name="nb-abc", namespace="sp-nb-org1"
        )
        core_v1.patch_namespaced_secret.assert_called_once()

        # Verify ownerReferences body structure.
        patch_body = core_v1.patch_namespaced_secret.call_args[1]["body"]
        owner_refs = patch_body["metadata"]["ownerReferences"]
        assert len(owner_refs) == 1
        assert owner_refs[0]["kind"] == "Pod"
        assert owner_refs[0]["uid"] == "pod-uid-1234"
        assert owner_refs[0]["controller"] is True
        assert owner_refs[0]["blockOwnerDeletion"] is True

    @pytest.mark.asyncio
    async def test_happy_path_secret_name_derived_from_pod_name(self):
        """Secret name must be sp-jwt-<pod_name>."""
        from gateway.orchestrator.jwt_secret_lifecycle import create_jwt_secret_with_owner_ref

        core_v1 = _make_core_v1()
        await create_jwt_secret_with_owner_ref(
            core_v1,
            namespace="sp-nb-org1",
            pod_name="nb-mytest",
            session_jwt="jwt-value",
            create_pod_fn=_make_pod_fn(),
        )

        secret_body = core_v1.create_namespaced_secret.call_args[1]["body"]
        assert secret_body.metadata.name == "sp-jwt-nb-mytest"

        patch_name = core_v1.patch_namespaced_secret.call_args[1]["name"]
        assert patch_name == "sp-jwt-nb-mytest"


class TestPodCreateFailure:
    @pytest.mark.asyncio
    async def test_pod_create_failure_deletes_secret_and_reraises(self):
        """Pod-create failure → delete Secret, then re-raise original exception."""
        from gateway.orchestrator.jwt_secret_lifecycle import create_jwt_secret_with_owner_ref

        core_v1 = _make_core_v1()
        create_pod_fn = _make_pod_fn(side_effect=RuntimeError("pod-create-fail"))

        with pytest.raises(RuntimeError, match="pod-create-fail"):
            await create_jwt_secret_with_owner_ref(
                core_v1,
                namespace="sp-nb-org1",
                pod_name="nb-abc",
                session_jwt="jwt",
                create_pod_fn=create_pod_fn,
            )

        core_v1.delete_namespaced_secret.assert_called_once_with(
            name="sp-jwt-nb-abc", namespace="sp-nb-org1"
        )
        core_v1.patch_namespaced_secret.assert_not_called()

    @pytest.mark.asyncio
    async def test_pod_create_failure_also_attempts_pod_delete(self):
        """On any step-(b/c/d) failure, pod deletion is also attempted."""
        from gateway.orchestrator.jwt_secret_lifecycle import create_jwt_secret_with_owner_ref

        core_v1 = _make_core_v1()
        create_pod_fn = _make_pod_fn(side_effect=RuntimeError("pod-fail"))

        with pytest.raises(RuntimeError):
            await create_jwt_secret_with_owner_ref(
                core_v1,
                namespace="sp-nb-org1",
                pod_name="nb-abc",
                session_jwt="jwt",
                create_pod_fn=create_pod_fn,
            )

        core_v1.delete_namespaced_pod.assert_called_once_with(
            name="nb-abc", namespace="sp-nb-org1"
        )


class TestOwnerRefPatchFailure:
    @pytest.mark.asyncio
    async def test_ownerref_patch_failure_deletes_pod_and_secret(self):
        """ownerRef-patch failure → delete both Pod and Secret, then re-raise."""
        from gateway.orchestrator.jwt_secret_lifecycle import create_jwt_secret_with_owner_ref

        core_v1 = _make_core_v1(
            patch_secret_side_effect=RuntimeError("patch-fail"),
        )

        with pytest.raises(RuntimeError, match="patch-fail"):
            await create_jwt_secret_with_owner_ref(
                core_v1,
                namespace="sp-nb-org1",
                pod_name="nb-abc",
                session_jwt="jwt",
                create_pod_fn=_make_pod_fn(),
            )

        core_v1.delete_namespaced_secret.assert_called_once()
        core_v1.delete_namespaced_pod.assert_called_once()


class TestSecretCreateFailure:
    @pytest.mark.asyncio
    async def test_secret_create_failure_no_cleanup(self):
        """Secret-create failure → no cleanup attempted (nothing exists yet)."""
        from gateway.orchestrator.jwt_secret_lifecycle import create_jwt_secret_with_owner_ref

        core_v1 = _make_core_v1(
            create_secret_side_effect=RuntimeError("secret-create-fail"),
        )
        create_pod_fn = _make_pod_fn()

        with pytest.raises(RuntimeError, match="secret-create-fail"):
            await create_jwt_secret_with_owner_ref(
                core_v1,
                namespace="sp-nb-org1",
                pod_name="nb-abc",
                session_jwt="jwt",
                create_pod_fn=create_pod_fn,
            )

        create_pod_fn.assert_not_called()
        core_v1.delete_namespaced_secret.assert_not_called()
        core_v1.delete_namespaced_pod.assert_not_called()
