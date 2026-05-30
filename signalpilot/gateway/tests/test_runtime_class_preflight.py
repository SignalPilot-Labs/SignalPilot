"""F-5: Tests for runtimeClassName settings validation and pre-flight check.

Covers:
- Cloud mode with empty SP_NOTEBOOK_RUNTIME_CLASS raises ValueError at settings load.
- Local mode with empty SP_NOTEBOOK_RUNTIME_CLASS is accepted.
- Pre-flight: missing RuntimeClass in cloud mode → RuntimeError (fail-closed).
- Pre-flight: missing RuntimeClass in local mode → log warning, continue.
- _pod_manifest includes runtimeClassName when set.
- _pod_manifest omits runtimeClassName when empty.
- Regression: _ensure_client second call also raises in cloud mode after first failure.
- Regression: concurrent _ensure_client calls serialize via lock; read_runtime_class called once.
"""

from __future__ import annotations

import asyncio
import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSettingsRuntimeClass:
    """K8sSettings validates SP_NOTEBOOK_RUNTIME_CLASS per deployment mode."""

    def test_cloud_mode_requires_runtime_class(self, monkeypatch):
        """SP_DEPLOYMENT_MODE=cloud + empty SP_NOTEBOOK_RUNTIME_CLASS → ValueError."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "")
        # Also provide required cloud-mode values
        monkeypatch.setenv("SP_PUBLIC_GATEWAY_URL", "https://gateway.example.com")

        from pydantic import ValidationError

        # Clear the lru_cache so our env changes take effect
        from gateway.config import k8s as k8s_mod
        k8s_mod.get_k8s_settings.cache_clear()

        try:
            with pytest.raises((ValueError, ValidationError)):
                from gateway.config.k8s import K8sSettings
                K8sSettings()
        finally:
            k8s_mod.get_k8s_settings.cache_clear()

    def test_local_mode_empty_runtime_class_ok(self, monkeypatch):
        """Local mode + empty SP_NOTEBOOK_RUNTIME_CLASS → settings load successfully."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "")

        from gateway.config import k8s as k8s_mod
        k8s_mod.get_k8s_settings.cache_clear()

        try:
            from gateway.config.k8s import K8sSettings
            settings = K8sSettings()
            assert settings.sp_notebook_runtime_class == ""
        finally:
            k8s_mod.get_k8s_settings.cache_clear()

    def test_cloud_mode_with_runtime_class_set_ok(self, monkeypatch):
        """Cloud mode + explicit SP_NOTEBOOK_RUNTIME_CLASS → settings load successfully."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "gvisor")
        monkeypatch.setenv("SP_PUBLIC_GATEWAY_URL", "https://gateway.example.com")

        from gateway.config import k8s as k8s_mod
        k8s_mod.get_k8s_settings.cache_clear()

        try:
            from gateway.config.k8s import K8sSettings
            settings = K8sSettings()
            assert settings.sp_notebook_runtime_class == "gvisor"
        finally:
            k8s_mod.get_k8s_settings.cache_clear()

    def test_local_mode_with_runtime_class_set_ok(self, monkeypatch):
        """Local mode with explicit runtime class is also fine."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "gvisor")

        from gateway.config import k8s as k8s_mod
        k8s_mod.get_k8s_settings.cache_clear()

        try:
            from gateway.config.k8s import K8sSettings
            settings = K8sSettings()
            assert settings.sp_notebook_runtime_class == "gvisor"
        finally:
            k8s_mod.get_k8s_settings.cache_clear()


class TestPreflightRuntimeClass:
    """_preflight_runtime_class verifies the RuntimeClass exists in the cluster."""

    @pytest.mark.asyncio
    async def test_preflight_missing_runtime_class_cloud_fails(self, monkeypatch):
        """Cloud mode: missing RuntimeClass → RuntimeError (fail-closed)."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")

        from gateway.orchestrator.kubernetes import KubernetesOrchestrator

        orch = MagicMock(spec=KubernetesOrchestrator)
        orch._runtime_class = "gvisor"
        orch._runtime_class_verified = False
        orch._client = MagicMock()

        # read_runtime_class raises 404
        mock_node_api = MagicMock()
        mock_node_api.read_runtime_class = AsyncMock(
            side_effect=Exception("404: RuntimeClass not found")
        )

        with patch("kubernetes_asyncio.client.NodeV1Api", return_value=mock_node_api):
            with pytest.raises(RuntimeError, match="RuntimeClass"):
                await KubernetesOrchestrator._preflight_runtime_class(orch)

    @pytest.mark.asyncio
    async def test_preflight_cloud_failure_does_not_set_verified(self, monkeypatch):
        """Cloud mode: after failure, _runtime_class_verified remains False."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")

        from gateway.orchestrator.kubernetes import KubernetesOrchestrator

        orch = MagicMock(spec=KubernetesOrchestrator)
        orch._runtime_class = "gvisor"
        orch._runtime_class_verified = False
        orch._client = MagicMock()

        mock_node_api = MagicMock()
        mock_node_api.read_runtime_class = AsyncMock(
            side_effect=Exception("404: RuntimeClass not found")
        )

        with patch("kubernetes_asyncio.client.NodeV1Api", return_value=mock_node_api):
            with pytest.raises(RuntimeError):
                await KubernetesOrchestrator._preflight_runtime_class(orch)

        # Critical: flag must remain False so the next caller retries.
        assert orch._runtime_class_verified is False

    @pytest.mark.asyncio
    async def test_preflight_missing_runtime_class_local_warns(self, monkeypatch, caplog):
        """Local mode: missing RuntimeClass → log warning, no exception."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")

        from gateway.orchestrator.kubernetes import KubernetesOrchestrator

        orch = MagicMock(spec=KubernetesOrchestrator)
        orch._runtime_class = "gvisor"
        orch._runtime_class_verified = False
        orch._client = MagicMock()

        mock_node_api = MagicMock()
        mock_node_api.read_runtime_class = AsyncMock(
            side_effect=Exception("404: RuntimeClass not found")
        )

        with patch("kubernetes_asyncio.client.NodeV1Api", return_value=mock_node_api):
            with caplog.at_level(logging.WARNING, logger="gateway.orchestrator.kubernetes"):
                # Should not raise
                await KubernetesOrchestrator._preflight_runtime_class(orch)

        assert any("RuntimeClass" in r.message for r in caplog.records), (
            "Expected a warning log about missing RuntimeClass in local mode"
        )

    @pytest.mark.asyncio
    async def test_preflight_no_runtime_class_configured_skips(self):
        """When _runtime_class is None/empty, pre-flight check is skipped entirely."""
        from gateway.orchestrator.kubernetes import KubernetesOrchestrator

        orch = MagicMock(spec=KubernetesOrchestrator)
        orch._runtime_class = None
        orch._runtime_class_verified = False
        orch._client = MagicMock()

        mock_node_api = MagicMock()
        mock_node_api.read_runtime_class = AsyncMock()

        with patch("kubernetes_asyncio.client.NodeV1Api", return_value=mock_node_api):
            # Should not raise and should not call read_runtime_class
            await KubernetesOrchestrator._preflight_runtime_class(orch)

        mock_node_api.read_runtime_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_preflight_cached_after_first_call(self):
        """Pre-flight is not re-executed on subsequent calls."""
        from gateway.orchestrator.kubernetes import KubernetesOrchestrator

        orch = MagicMock(spec=KubernetesOrchestrator)
        orch._runtime_class = "gvisor"
        orch._runtime_class_verified = True  # Already verified
        orch._client = MagicMock()

        mock_node_api = MagicMock()
        mock_node_api.read_runtime_class = AsyncMock()

        with patch("kubernetes_asyncio.client.NodeV1Api", return_value=mock_node_api):
            await KubernetesOrchestrator._preflight_runtime_class(orch)

        mock_node_api.read_runtime_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_preflight_success_logs_info(self, caplog):
        """Successful pre-flight logs an info message."""
        from gateway.orchestrator.kubernetes import KubernetesOrchestrator

        orch = MagicMock(spec=KubernetesOrchestrator)
        orch._runtime_class = "gvisor"
        orch._runtime_class_verified = False
        orch._client = MagicMock()

        mock_node_api = MagicMock()
        mock_node_api.read_runtime_class = AsyncMock(return_value=MagicMock())

        with patch("kubernetes_asyncio.client.NodeV1Api", return_value=mock_node_api):
            with caplog.at_level(logging.INFO, logger="gateway.orchestrator.kubernetes"):
                await KubernetesOrchestrator._preflight_runtime_class(orch)

        assert any("verified" in r.message.lower() or "gvisor" in r.message for r in caplog.records)


class TestPodManifestRuntimeClass:
    """_pod_manifest correctly applies or omits runtimeClassName."""

    def test_pod_manifest_includes_runtime_class(self):
        """When runtime_class is set, spec.runtimeClassName is present."""
        from gateway.orchestrator.kubernetes import _pod_manifest

        manifest = _pod_manifest(
            pod_name="test-pod",
            namespace="test-ns",
            image="test-image:latest",
            user_id="user-1",
            org_id="org-1",
            project_id="proj-1",
            branch="main",
            gateway_url="http://gateway:3300",
            session_jwt_secret_name="sp-jwt-test-pod",
            session_id="sess-1",
            access_token=None,
            runtime_class="gvisor",
        )

        assert manifest["spec"]["runtimeClassName"] == "gvisor"

    def test_pod_manifest_omits_runtime_class_when_empty(self):
        """When runtime_class is None or empty, runtimeClassName is NOT in spec."""
        from gateway.orchestrator.kubernetes import _pod_manifest

        manifest_none = _pod_manifest(
            pod_name="test-pod",
            namespace="test-ns",
            image="test-image:latest",
            user_id="user-1",
            org_id="org-1",
            project_id="proj-1",
            branch="main",
            gateway_url="http://gateway:3300",
            session_jwt_secret_name="sp-jwt-test-pod",
            session_id="sess-1",
            access_token=None,
            runtime_class=None,
        )

        assert "runtimeClassName" not in manifest_none["spec"], (
            "runtimeClassName must not be emitted when runtime_class is None"
        )

    def test_pod_manifest_omits_runtime_class_when_not_provided(self):
        """When runtime_class is not passed (default), runtimeClassName is absent."""
        from gateway.orchestrator.kubernetes import _pod_manifest

        manifest = _pod_manifest(
            pod_name="test-pod",
            namespace="test-ns",
            image="test-image:latest",
            user_id="user-1",
            org_id="org-1",
            project_id="proj-1",
            branch="main",
            gateway_url="http://gateway:3300",
            session_jwt_secret_name="sp-jwt-test-pod",
            session_id="sess-1",
            access_token=None,
        )

        assert "runtimeClassName" not in manifest["spec"]

    def test_pod_manifest_kata_runtime_class(self):
        """Kata runtime class is also applied correctly."""
        from gateway.orchestrator.kubernetes import _pod_manifest

        manifest = _pod_manifest(
            pod_name="test-pod",
            namespace="test-ns",
            image="test-image:latest",
            user_id="user-1",
            org_id="org-1",
            project_id="proj-1",
            branch="main",
            gateway_url="http://gateway:3300",
            session_jwt_secret_name="sp-jwt-test-pod",
            session_id="sess-1",
            access_token=None,
            runtime_class="kata",
        )

        assert manifest["spec"]["runtimeClassName"] == "kata"


class TestEnsureClientFailClosedRegression:
    """Regression tests: _ensure_client must remain fail-closed across retries and concurrent callers.

    These tests exercise the full _ensure_client path (not _preflight_runtime_class directly)
    to catch the race where self._client was assigned before preflight — meaning the second
    caller saw self._client != None and returned success without re-running the preflight.
    """

    def _make_orch(self, monkeypatch, runtime_class: str = "gvisor") -> object:
        """Return a KubernetesOrchestrator instance with settings pre-loaded."""
        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")
        from gateway.orchestrator.kubernetes import KubernetesOrchestrator

        orch = KubernetesOrchestrator.__new__(KubernetesOrchestrator)
        # Manually set the fields _ensure_client needs.
        orch._image = "test-image:latest"
        orch._client = None
        orch._core_api = None
        orch._networking_api = None
        orch._rbac_api = None
        orch._namespace_prefix = "sp"
        orch._gateway_namespace = "signalpilot"
        orch._gateway_pod_selector = {"app": "gateway"}
        orch._gateway_port = 3300
        orch._egress_cidr = None
        orch._gateway_service_account = "signalpilot-gateway"
        orch._runtime_class = runtime_class
        orch._runtime_class_verified = False
        orch._init_lock = None
        return orch  # type: ignore[return-value]

    @pytest.mark.asyncio
    async def test_ensure_client_second_call_also_raises_in_cloud_mode(self, monkeypatch):
        """Cloud mode: second _ensure_client call also raises when preflight always fails.

        Regression for: self._client was set before preflight, so the second call
        returned without raising because self._client was already set.
        """
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        orch = self._make_orch(monkeypatch)

        mock_client_api = MagicMock()
        mock_node_api = MagicMock()
        mock_node_api.read_runtime_class = AsyncMock(
            side_effect=Exception("404: RuntimeClass not found")
        )

        with (
            patch("gateway.orchestrator.kubernetes.KubernetesOrchestrator._load_settings"),
            patch("kubernetes_asyncio.config.load_incluster_config"),
            patch("kubernetes_asyncio.client.ApiClient", return_value=mock_client_api),
            patch("kubernetes_asyncio.client.CoreV1Api", return_value=MagicMock()),
            patch("kubernetes_asyncio.client.NetworkingV1Api", return_value=MagicMock()),
            patch("kubernetes_asyncio.client.RbacAuthorizationV1Api", return_value=MagicMock()),
            patch("kubernetes_asyncio.client.NodeV1Api", return_value=mock_node_api),
        ):
            # First call must raise.
            with pytest.raises(RuntimeError, match="RuntimeClass"):
                await orch._ensure_client()

            # self._client must not be set after a failed preflight.
            assert orch._client is None, (
                "self._client must remain None after preflight failure — "
                "otherwise the second call skips preflight and proceeds fail-open"
            )

            # Second call must also raise — not silently succeed.
            with pytest.raises(RuntimeError, match="RuntimeClass"):
                await orch._ensure_client()

    @pytest.mark.asyncio
    async def test_ensure_client_pod_creation_blocked_after_failed_init(self, monkeypatch):
        """After _ensure_client fails, create_pod raises 'not available'."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        orch = self._make_orch(monkeypatch)

        mock_client_api = MagicMock()
        mock_node_api = MagicMock()
        mock_node_api.read_runtime_class = AsyncMock(
            side_effect=Exception("404: RuntimeClass not found")
        )

        with (
            patch("gateway.orchestrator.kubernetes.KubernetesOrchestrator._load_settings"),
            patch("kubernetes_asyncio.config.load_incluster_config"),
            patch("kubernetes_asyncio.client.ApiClient", return_value=mock_client_api),
            patch("kubernetes_asyncio.client.CoreV1Api", return_value=MagicMock()),
            patch("kubernetes_asyncio.client.NetworkingV1Api", return_value=MagicMock()),
            patch("kubernetes_asyncio.client.RbacAuthorizationV1Api", return_value=MagicMock()),
            patch("kubernetes_asyncio.client.NodeV1Api", return_value=mock_node_api),
        ):
            # _ensure_client raises in cloud mode due to preflight failure.
            with pytest.raises(RuntimeError):
                await orch.create_pod(
                    pod_name="test-pod",
                    user_id="u1",
                    org_id="org1",
                    project_id="proj1",
                    branch="main",
                    image="img:latest",
                    gateway_url="http://gw",
                    session_jwt_secret_name="sp-jwt-test-pod",
                    session_id="sess1",
                    access_token=None,
                )

        # self._client must be None — pod creation did not proceed.
        assert orch._client is None

    @pytest.mark.asyncio
    async def test_ensure_client_concurrent_calls_serialize(self, monkeypatch):
        """Concurrent _ensure_client calls serialize; read_runtime_class called exactly once.

        Two concurrent callers race to init. With the asyncio.Lock, only one enters
        the init body; the second sees self._client is set on lock release and returns.
        """
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        orch = self._make_orch(monkeypatch)

        call_count = 0

        async def delayed_read_runtime_class(name: str) -> MagicMock:
            nonlocal call_count
            call_count += 1
            # Yield to let the second coroutine try to enter — it must block on the lock.
            await asyncio.sleep(0)
            return MagicMock()

        mock_client_api = MagicMock()
        mock_node_api = MagicMock()
        mock_node_api.read_runtime_class = delayed_read_runtime_class

        with (
            patch("gateway.orchestrator.kubernetes.KubernetesOrchestrator._load_settings"),
            patch("kubernetes_asyncio.config.load_incluster_config"),
            patch("kubernetes_asyncio.client.ApiClient", return_value=mock_client_api),
            patch("kubernetes_asyncio.client.CoreV1Api", return_value=MagicMock()),
            patch("kubernetes_asyncio.client.NetworkingV1Api", return_value=MagicMock()),
            patch("kubernetes_asyncio.client.RbacAuthorizationV1Api", return_value=MagicMock()),
            patch("kubernetes_asyncio.client.NodeV1Api", return_value=mock_node_api),
        ):
            await asyncio.gather(orch._ensure_client(), orch._ensure_client())

        # read_runtime_class must be called exactly once — not twice.
        assert call_count == 1, (
            f"read_runtime_class called {call_count} times — expected 1. "
            "Concurrent callers must serialize via the asyncio.Lock."
        )
        # Both coroutines succeeded, so client must be set.
        assert orch._client is not None
