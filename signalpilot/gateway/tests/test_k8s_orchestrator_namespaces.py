"""Tests for KubernetesOrchestrator namespace-per-org behavior (R3).

These tests verify:
- create_pod calls ensure_org_namespace and creates pod in org namespace.
- delete_pod targets org namespace.
- No Service is ever created.
- namespace bootstrap failure surfaces as RuntimeError.
- Empty org_id raises ValueError.
- Constructor refuses non-pod_ip upstream mode.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_orchestrator(monkeypatch) -> object:
    """Build a KubernetesOrchestrator with SP_NOTEBOOK_UPSTREAM_MODE=pod_ip."""
    monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")
    # Re-import the module to pick up the monkeypatched env var.
    import importlib

    import gateway.orchestrator.kubernetes as k8s_mod

    importlib.reload(k8s_mod)
    return k8s_mod.KubernetesOrchestrator()


class _K8sObject:
    def __init__(self, data: dict):
        self._data = data

    def to_dict(self) -> dict:
        return self._data


class TestPodDiagnostics:
    @pytest.mark.asyncio
    async def test_wait_for_running_timeout_includes_pod_event_reason(self, monkeypatch):
        orch = _make_orchestrator(monkeypatch)
        orch._client = object()
        orch._namespace_prefix = "sp-nb"

        mock_core = MagicMock()
        mock_core.read_namespaced_pod = AsyncMock(
            return_value=_K8sObject(
                {
                    "status": {
                        "phase": "Pending",
                        "conditions": [
                            {
                                "type": "PodScheduled",
                                "status": "False",
                                "reason": "Unschedulable",
                                "message": "0/2 nodes are available: node selector mismatch.",
                            }
                        ],
                        "container_statuses": [
                            {
                                "name": "notebook",
                                "ready": False,
                                "state": {"waiting": {"reason": "ContainerCreating"}},
                                "restart_count": 0,
                            }
                        ],
                    }
                }
            )
        )
        mock_core.list_namespaced_event = AsyncMock(
            return_value=_K8sObject(
                {
                    "items": [
                        {
                            "type": "Warning",
                            "reason": "FailedScheduling",
                            "message": "0/2 nodes are available: node selector mismatch.",
                        }
                    ]
                }
            )
        )
        orch._core_api = mock_core

        with pytest.raises(TimeoutError, match="FailedScheduling"):
            await orch.wait_for_running("nb-test", org_id="org-1", timeout=0)


class TestOrchestratorRefusesNonPodIpMode:
    def test_orchestrator_refuses_non_pod_ip_mode(self, monkeypatch):
        """Constructing KubernetesOrchestrator with SP_NOTEBOOK_UPSTREAM_MODE=nodeport raises."""
        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "nodeport")

        import importlib

        import gateway.orchestrator.kubernetes as k8s_mod

        importlib.reload(k8s_mod)

        with pytest.raises(RuntimeError, match="pod_ip"):
            k8s_mod.KubernetesOrchestrator()


class TestCreatePodNamespaceBehavior:
    @pytest.mark.asyncio
    async def test_create_pod_creates_namespace_first(self, monkeypatch):
        """create_pod calls ensure_org_namespace before create_namespaced_pod."""
        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")

        import importlib

        import gateway.orchestrator.kubernetes as k8s_mod

        importlib.reload(k8s_mod)

        orch = k8s_mod.KubernetesOrchestrator()

        # Inject fake clients directly.
        mock_core = MagicMock()
        mock_core.create_namespaced_pod = AsyncMock()
        mock_networking = MagicMock()
        mock_rbac = MagicMock()
        orch._core_api = mock_core
        orch._networking_api = mock_networking
        orch._rbac_api = mock_rbac
        orch._namespace_prefix = "sp-nb"
        orch._gateway_namespace = "signalpilot"
        orch._gateway_pod_selector = {"app": "signalpilot-gateway"}
        orch._gateway_port = 3300
        orch._egress_cidr = None
        orch._gateway_service_account = "signalpilot-gateway"

        call_order = []

        async def _fake_ensure(*args, **kwargs):
            call_order.append("ensure_org_namespace")

        async def _fake_create_pod(namespace, body):
            call_order.append("create_namespaced_pod")

        mock_core.create_namespaced_pod = _fake_create_pod

        with patch("gateway.orchestrator.kubernetes.ensure_org_namespace", _fake_ensure):
            await orch.create_pod(
                pod_name="nb-test",
                user_id="user-1",
                org_id="org-1",
                branch="main",
                image="signalpilot-notebook:latest",
                gateway_url="http://gateway:3300",
                session_jwt="jwt",
                session_id="sess-1",
                access_token=None,
            )

        assert call_order[0] == "ensure_org_namespace"
        assert call_order[1] == "create_namespaced_pod"

    @pytest.mark.asyncio
    async def test_create_pod_uses_org_namespace_not_default(self, monkeypatch):
        """create_pod creates the pod in the org-specific namespace, not 'default'."""
        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")

        import importlib

        import gateway.orchestrator.kubernetes as k8s_mod

        importlib.reload(k8s_mod)

        orch = k8s_mod.KubernetesOrchestrator()
        mock_core = MagicMock()
        orch._core_api = mock_core
        orch._networking_api = MagicMock()
        orch._rbac_api = MagicMock()
        orch._namespace_prefix = "sp-nb"
        orch._gateway_namespace = "signalpilot"
        orch._gateway_pod_selector = {"app": "signalpilot-gateway"}
        orch._gateway_port = 3300
        orch._egress_cidr = None
        orch._gateway_service_account = "signalpilot-gateway"

        created_in_namespace = []

        async def _fake_create_pod(namespace, body):
            created_in_namespace.append(namespace)

        mock_core.create_namespaced_pod = _fake_create_pod

        with patch("gateway.orchestrator.kubernetes.ensure_org_namespace", AsyncMock()):
            await orch.create_pod(
                pod_name="nb-test",
                user_id="user-1",
                org_id="org-abc",
                branch="main",
                image="signalpilot-notebook:latest",
                gateway_url="http://gateway:3300",
                session_jwt="jwt",
                session_id="sess-1",
                access_token=None,
            )

        assert len(created_in_namespace) == 1
        ns = created_in_namespace[0]
        assert ns != "default"
        assert ns.startswith("sp-nb-")

    @pytest.mark.asyncio
    async def test_delete_pod_targets_org_namespace(self, monkeypatch):
        """delete_pod deletes from org namespace, not 'default'."""
        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")

        import importlib

        import gateway.orchestrator.kubernetes as k8s_mod

        importlib.reload(k8s_mod)

        orch = k8s_mod.KubernetesOrchestrator()
        mock_core = MagicMock()
        orch._core_api = mock_core
        orch._namespace_prefix = "sp-nb"
        orch._gateway_namespace = "signalpilot"
        orch._gateway_pod_selector = {"app": "signalpilot-gateway"}
        orch._gateway_port = 3300
        orch._egress_cidr = None
        orch._gateway_service_account = "signalpilot-gateway"

        deleted_from_namespace = []

        async def _fake_delete_pod(name, namespace, grace_period_seconds):
            deleted_from_namespace.append(namespace)

        mock_core.delete_namespaced_pod = _fake_delete_pod

        await orch.delete_pod("nb-test", org_id="org-abc")

        assert len(deleted_from_namespace) == 1
        ns = deleted_from_namespace[0]
        assert ns != "default"
        assert ns.startswith("sp-nb-")

    @pytest.mark.asyncio
    async def test_create_pod_no_service_created(self, monkeypatch):
        """create_namespaced_service is NEVER invoked — no NodePort in R3."""
        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")

        import importlib

        import gateway.orchestrator.kubernetes as k8s_mod

        importlib.reload(k8s_mod)

        orch = k8s_mod.KubernetesOrchestrator()
        mock_core = MagicMock()
        mock_core.create_namespaced_pod = AsyncMock()
        mock_core.create_namespaced_service = AsyncMock()
        orch._core_api = mock_core
        orch._networking_api = MagicMock()
        orch._rbac_api = MagicMock()
        orch._namespace_prefix = "sp-nb"
        orch._gateway_namespace = "signalpilot"
        orch._gateway_pod_selector = {"app": "signalpilot-gateway"}
        orch._gateway_port = 3300
        orch._egress_cidr = None
        orch._gateway_service_account = "signalpilot-gateway"

        with patch("gateway.orchestrator.kubernetes.ensure_org_namespace", AsyncMock()):
            await orch.create_pod(
                pod_name="nb-test",
                user_id="user-1",
                org_id="org-1",
                branch="main",
                image="signalpilot-notebook:latest",
                gateway_url="http://gateway:3300",
                session_jwt="jwt",
                session_id="sess-1",
                access_token=None,
            )

        mock_core.create_namespaced_service.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_pod_namespace_create_failure_surfaces_as_runtime_error(self, monkeypatch):
        """If ensure_org_namespace raises a non-409 error, it surfaces to the caller."""
        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")

        import importlib

        import gateway.orchestrator.kubernetes as k8s_mod

        importlib.reload(k8s_mod)

        orch = k8s_mod.KubernetesOrchestrator()
        mock_core = MagicMock()
        orch._core_api = mock_core
        orch._networking_api = MagicMock()
        orch._rbac_api = MagicMock()
        orch._namespace_prefix = "sp-nb"
        orch._gateway_namespace = "signalpilot"
        orch._gateway_pod_selector = {"app": "signalpilot-gateway"}
        orch._gateway_port = 3300
        orch._egress_cidr = None
        orch._gateway_service_account = "signalpilot-gateway"

        with patch(
            "gateway.orchestrator.kubernetes.ensure_org_namespace",
            AsyncMock(side_effect=RuntimeError("Namespace creation permission denied")),
        ):
            with pytest.raises(RuntimeError, match="Namespace creation permission denied"):
                await orch.create_pod(
                    pod_name="nb-test",
                    user_id="user-1",
                    org_id="org-1",
                    branch="main",
                    image="signalpilot-notebook:latest",
                    gateway_url="http://gateway:3300",
                    session_jwt="jwt",
                    session_id="sess-1",
                    access_token=None,
                )

    @pytest.mark.asyncio
    async def test_create_pod_empty_org_id_raises(self, monkeypatch):
        """create_pod with empty org_id raises ValueError immediately."""
        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")

        import importlib

        import gateway.orchestrator.kubernetes as k8s_mod

        importlib.reload(k8s_mod)

        orch = k8s_mod.KubernetesOrchestrator()
        orch._core_api = MagicMock()
        orch._namespace_prefix = "sp-nb"

        with pytest.raises(ValueError, match="org_id must not be empty"):
            await orch.create_pod(
                pod_name="nb-test",
                user_id="user-1",
                org_id="",
                branch="main",
                image="signalpilot-notebook:latest",
                gateway_url="http://gateway:3300",
                session_jwt="jwt",
                session_id="sess-1",
                access_token=None,
            )


class TestPodSpecHardening:
    """R5: PodSpec must set enableServiceLinks=False."""

    @pytest.mark.asyncio
    async def test_create_pod_enable_service_links_false(self, monkeypatch):
        """create_pod must set enableServiceLinks=False on the pod spec."""
        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")

        import importlib

        import gateway.orchestrator.kubernetes as k8s_mod

        importlib.reload(k8s_mod)

        orch = k8s_mod.KubernetesOrchestrator()
        captured_bodies: list[dict] = []

        async def _capture_pod(namespace, body):
            captured_bodies.append(body)

        mock_core = MagicMock()
        mock_core.create_namespaced_pod = _capture_pod
        mock_core.create_namespaced_service = AsyncMock()
        orch._core_api = mock_core
        orch._networking_api = MagicMock()
        orch._rbac_api = MagicMock()
        orch._namespace_prefix = "sp-nb"
        orch._gateway_namespace = "signalpilot"
        orch._gateway_pod_selector = {"app": "signalpilot-gateway"}
        orch._gateway_port = 3300
        orch._egress_cidr = None
        orch._gateway_service_account = "signalpilot-gateway"

        with patch("gateway.orchestrator.kubernetes.ensure_org_namespace", AsyncMock()):
            await orch.create_pod(
                pod_name="nb-test",
                user_id="user-1",
                org_id="org-1",
                branch="main",
                image="signalpilot-notebook:latest",
                gateway_url="http://gateway:3300",
                session_jwt="jwt",
                session_id="sess-1",
                access_token=None,
            )

        assert len(captured_bodies) == 1
        assert captured_bodies[0]["spec"]["enableServiceLinks"] is False


class TestIs409Classification:
    """R5: _is_409 must use exc.status, not str(exc)."""

    def test_returns_true_for_status_409(self):
        from gateway.orchestrator.namespaces import _is_409

        exc = type("E", (Exception,), {})()
        exc.status = 409  # type: ignore[attr-defined]
        assert _is_409(exc) is True

    def test_returns_false_for_status_500(self):
        from gateway.orchestrator.namespaces import _is_409

        exc = type("E", (Exception,), {})()
        exc.status = 500  # type: ignore[attr-defined]
        assert _is_409(exc) is False

    def test_returns_false_for_plain_exception_with_409_in_message(self):
        """Proves we no longer grep — '409' in the message text must not count."""
        from gateway.orchestrator.namespaces import _is_409

        assert _is_409(Exception("409 oops AlreadyExists")) is False
