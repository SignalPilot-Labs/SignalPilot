"""Unit tests for gateway.orchestrator.jwt_secret_gc.gc_orphan_jwt_secrets.

R7 F-13 (1c).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_secret(
    *,
    name: str,
    age_seconds: int = 1800,
    owner_references=None,
) -> MagicMock:
    """Build a mock Secret object."""
    secret = MagicMock()
    secret.metadata = MagicMock()
    secret.metadata.name = name
    secret.metadata.owner_references = owner_references  # None or []
    now = datetime.now(UTC)
    secret.metadata.creation_timestamp = now - timedelta(seconds=age_seconds)
    return secret


def _make_namespace(name: str) -> MagicMock:
    ns = MagicMock()
    ns.metadata = MagicMock()
    ns.metadata.name = name
    return ns


def _make_api_exception(status: int) -> Exception:
    exc = MagicMock()
    exc.status = status
    return exc


def _make_orch(
    *,
    namespaces: list[str],
    secrets_by_ns: dict[str, list[MagicMock]],
    read_pod_side_effect: dict[str, Exception | None] | None = None,
    delete_secret_side_effect: dict[str, Exception | None] | None = None,
) -> MagicMock:
    """Build a mock KubernetesOrchestrator."""
    orch = MagicMock()
    orch._ensure_client = AsyncMock()

    core_v1 = MagicMock()

    ns_list = MagicMock()
    ns_list.items = [_make_namespace(n) for n in namespaces]
    core_v1.list_namespace = AsyncMock(return_value=ns_list)

    def _secret_list(namespace):
        result = MagicMock()
        result.items = secrets_by_ns.get(namespace, [])
        return result

    core_v1.list_namespaced_secret = AsyncMock(side_effect=_secret_list)

    async def _read_pod(name, namespace):
        if read_pod_side_effect and name in read_pod_side_effect:
            exc = read_pod_side_effect[name]
            if exc is not None:
                raise exc
        pod = MagicMock()
        pod.metadata = MagicMock()
        pod.metadata.name = name
        return pod

    core_v1.read_namespaced_pod = AsyncMock(side_effect=_read_pod)

    async def _delete_secret(name, namespace):
        if delete_secret_side_effect and name in delete_secret_side_effect:
            exc = delete_secret_side_effect[name]
            if exc is not None:
                raise exc

    core_v1.delete_namespaced_secret = AsyncMock(side_effect=_delete_secret)

    orch._core_api = core_v1
    return orch


class TestSkipCriteria:
    @pytest.mark.asyncio
    async def test_skips_secret_with_owner_reference(self):
        """Secret with non-empty ownerReferences is skipped (kube GC handles it)."""
        from gateway.orchestrator.jwt_secret_gc import gc_orphan_jwt_secrets

        owner = MagicMock()
        secret = _make_secret(name="sp-jwt-nb-abc", age_seconds=2000, owner_references=[owner])
        orch = _make_orch(namespaces=["sp-nb-org1"], secrets_by_ns={"sp-nb-org1": [secret]})

        result = await gc_orphan_jwt_secrets(orch)

        assert result == 0
        orch._core_api.delete_namespaced_secret.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_secret_younger_than_max_age(self):
        """Secret younger than max_age_seconds is not deleted even if pod is missing."""
        from kubernetes_asyncio.client.exceptions import ApiException

        from gateway.orchestrator.jwt_secret_gc import gc_orphan_jwt_secrets

        secret = _make_secret(name="sp-jwt-nb-abc", age_seconds=60, owner_references=None)
        not_found = _make_api_exception(404)
        not_found.__class__ = ApiException
        orch = _make_orch(
            namespaces=["sp-nb-org1"],
            secrets_by_ns={"sp-nb-org1": [secret]},
            read_pod_side_effect={"nb-abc": not_found},
        )

        result = await gc_orphan_jwt_secrets(orch, max_age_seconds=900)

        assert result == 0
        orch._core_api.delete_namespaced_secret.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_secret_with_non_matching_prefix(self):
        """Secret whose name does not start with sp-jwt- is unconditionally skipped."""
        from gateway.orchestrator.jwt_secret_gc import gc_orphan_jwt_secrets

        secret = _make_secret(name="not-sp-jwt-foo", age_seconds=9999, owner_references=None)
        orch = _make_orch(namespaces=["sp-nb-org1"], secrets_by_ns={"sp-nb-org1": [secret]})

        result = await gc_orphan_jwt_secrets(orch)

        assert result == 0
        orch._core_api.read_namespaced_pod.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_pod_still_alive(self):
        """Secret older than max_age_seconds, no ownerRef, but pod alive → not deleted."""
        from gateway.orchestrator.jwt_secret_gc import gc_orphan_jwt_secrets

        secret = _make_secret(name="sp-jwt-nb-alive", age_seconds=2000, owner_references=None)
        # read_pod returns successfully (pod alive) — no side_effect entry means "return pod"
        orch = _make_orch(
            namespaces=["sp-nb-org1"],
            secrets_by_ns={"sp-nb-org1": [secret]},
        )

        result = await gc_orphan_jwt_secrets(orch)

        assert result == 0
        orch._core_api.delete_namespaced_secret.assert_not_called()


class TestDeleteBehavior:
    @pytest.mark.asyncio
    async def test_deletes_orphan_when_pod_404(self):
        """Secret older than 15min, no ownerRef, pod returns 404 → deleted."""
        from kubernetes_asyncio.client.exceptions import ApiException

        from gateway.orchestrator.jwt_secret_gc import gc_orphan_jwt_secrets

        secret = _make_secret(name="sp-jwt-nb-dead", age_seconds=2000, owner_references=None)
        not_found = ApiException(status=404)
        orch = _make_orch(
            namespaces=["sp-nb-org1"],
            secrets_by_ns={"sp-nb-org1": [secret]},
            read_pod_side_effect={"nb-dead": not_found},
        )

        result = await gc_orphan_jwt_secrets(orch)

        assert result == 1
        orch._core_api.delete_namespaced_secret.assert_called_once_with(
            name="sp-jwt-nb-dead", namespace="sp-nb-org1"
        )

    @pytest.mark.asyncio
    async def test_treats_delete_404_as_success(self):
        """delete_namespaced_secret raising 404 → counts as deletion (another replica won)."""
        from kubernetes_asyncio.client.exceptions import ApiException

        from gateway.orchestrator.jwt_secret_gc import gc_orphan_jwt_secrets

        secret = _make_secret(name="sp-jwt-nb-dead2", age_seconds=2000, owner_references=None)
        pod_404 = ApiException(status=404)
        delete_404 = ApiException(status=404)
        orch = _make_orch(
            namespaces=["sp-nb-org1"],
            secrets_by_ns={"sp-nb-org1": [secret]},
            read_pod_side_effect={"nb-dead2": pod_404},
            delete_secret_side_effect={"sp-jwt-nb-dead2": delete_404},
        )

        result = await gc_orphan_jwt_secrets(orch)

        assert result == 1

    @pytest.mark.asyncio
    async def test_does_not_silently_swallow_500_on_list(self):
        """list_namespaced_secret raising 500 bubbles up from gc_orphan_jwt_secrets."""
        from kubernetes_asyncio.client.exceptions import ApiException

        from gateway.orchestrator.jwt_secret_gc import gc_orphan_jwt_secrets

        orch = _make_orch(namespaces=["sp-nb-org1"], secrets_by_ns={})
        server_error = ApiException(status=500)
        orch._core_api.list_namespaced_secret = AsyncMock(side_effect=server_error)

        with pytest.raises(ApiException) as exc_info:
            await gc_orphan_jwt_secrets(orch)

        assert exc_info.value.status == 500

    @pytest.mark.asyncio
    async def test_does_not_silently_swallow_500_on_pod_read(self):
        """read_namespaced_pod raising non-404 bubbles up — not treated as 'pod missing'."""
        from kubernetes_asyncio.client.exceptions import ApiException

        from gateway.orchestrator.jwt_secret_gc import gc_orphan_jwt_secrets

        secret = _make_secret(name="sp-jwt-nb-err", age_seconds=2000, owner_references=None)
        server_error = ApiException(status=500)
        orch = _make_orch(
            namespaces=["sp-nb-org1"],
            secrets_by_ns={"sp-nb-org1": [secret]},
            read_pod_side_effect={"nb-err": server_error},
        )

        with pytest.raises(ApiException) as exc_info:
            await gc_orphan_jwt_secrets(orch)

        assert exc_info.value.status == 500
        orch._core_api.delete_namespaced_secret.assert_not_called()


class TestTenantNamespaceScoping:
    @pytest.mark.asyncio
    async def test_iterates_only_tenant_namespaces(self):
        """list_namespace is called with label_selector signalpilot.dev/tenant=user."""
        from gateway.orchestrator.jwt_secret_gc import gc_orphan_jwt_secrets

        orch = _make_orch(namespaces=[], secrets_by_ns={})

        await gc_orphan_jwt_secrets(orch)

        orch._core_api.list_namespace.assert_called_once_with(
            label_selector="signalpilot.dev/tenant=user"
        )

    @pytest.mark.asyncio
    async def test_iterates_multiple_namespaces(self):
        """GC runs per-namespace, deleting orphans in each."""
        from kubernetes_asyncio.client.exceptions import ApiException

        from gateway.orchestrator.jwt_secret_gc import gc_orphan_jwt_secrets

        s1 = _make_secret(name="sp-jwt-nb-x", age_seconds=2000, owner_references=None)
        s2 = _make_secret(name="sp-jwt-nb-y", age_seconds=2000, owner_references=None)
        pod_404 = ApiException(status=404)
        orch = _make_orch(
            namespaces=["sp-nb-org1", "sp-nb-org2"],
            secrets_by_ns={"sp-nb-org1": [s1], "sp-nb-org2": [s2]},
            read_pod_side_effect={"nb-x": pod_404, "nb-y": pod_404},
        )

        result = await gc_orphan_jwt_secrets(orch)

        assert result == 2
