"""Tests for the eval per-pod credential Secret + Pod creation lifecycle.

The three-step contract (Secret -> Pod -> ownerRef patch) must hold on the
happy path, and every failure mode must clean up and re-raise.
"""

from __future__ import annotations

import base64
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.orchestrator.secret_lifecycle import create_secret_with_owner_ref


def _fake_core(pod_uid: str = "uid-1"):
    core = MagicMock()
    core.delete_namespaced_secret = AsyncMock()
    core.create_namespaced_secret = AsyncMock()
    core.patch_namespaced_secret = AsyncMock()
    core.delete_namespaced_pod = AsyncMock()
    pod = MagicMock()
    pod.metadata.name = "sp-eval-abc"
    pod.metadata.uid = pod_uid
    core.read_namespaced_pod = AsyncMock(return_value=pod)
    return core


def _stub_k8s_modules(monkeypatch):
    """The module imports kubernetes_asyncio lazily; stub just what it uses."""
    k8s = MagicMock()

    class _ApiException(Exception):
        def __init__(self, status=404):
            self.status = status

    k8s.client.V1Secret = lambda **kw: {"secret": kw}
    k8s.client.V1ObjectMeta = lambda **kw: kw
    exceptions = MagicMock()
    exceptions.ApiException = _ApiException
    monkeypatch.setitem(sys.modules, "kubernetes_asyncio", k8s)
    monkeypatch.setitem(sys.modules, "kubernetes_asyncio.client", k8s.client)
    monkeypatch.setitem(sys.modules, "kubernetes_asyncio.client.exceptions", exceptions)
    return _ApiException


@pytest.mark.asyncio
async def test_happy_path_creates_secret_pod_and_patches_ownerref(monkeypatch):
    exc_type = _stub_k8s_modules(monkeypatch)
    core = _fake_core()
    core.delete_namespaced_secret.side_effect = exc_type(404)  # no stale secret
    create_pod = AsyncMock(return_value={"pod": True})

    result = await create_secret_with_owner_ref(
        core,
        namespace="sp-nb-x",
        secret_name="sp-eval-env-sp-eval-abc",
        values={"PGPASSWORD": "hunter2"},
        pod_name="sp-eval-abc",
        create_pod_fn=create_pod,
    )
    assert result == {"pod": True}
    created = core.create_namespaced_secret.await_args.kwargs["body"]["secret"]
    assert created["data"]["PGPASSWORD"] == base64.b64encode(b"hunter2").decode()
    patch = core.patch_namespaced_secret.await_args.kwargs["body"]
    owner = patch["metadata"]["ownerReferences"][0]
    assert owner["uid"] == "uid-1" and owner["kind"] == "Pod"


@pytest.mark.asyncio
async def test_pod_create_failure_cleans_up_secret_and_pod_then_reraises(monkeypatch):
    exc_type = _stub_k8s_modules(monkeypatch)
    core = _fake_core()
    core.delete_namespaced_secret.side_effect = [exc_type(404), None]
    boom = RuntimeError("pod create failed")

    with pytest.raises(RuntimeError, match="pod create failed"):
        await create_secret_with_owner_ref(
            core,
            namespace="ns",
            secret_name="s",
            values={"A": "1"},
            pod_name="p",
            create_pod_fn=AsyncMock(side_effect=boom),
        )
    assert core.delete_namespaced_secret.await_count == 2  # stale check + cleanup
    core.delete_namespaced_pod.assert_awaited_once()


@pytest.mark.asyncio
async def test_secret_create_failure_performs_no_cleanup(monkeypatch):
    exc_type = _stub_k8s_modules(monkeypatch)
    core = _fake_core()
    core.delete_namespaced_secret.side_effect = exc_type(404)
    core.create_namespaced_secret.side_effect = RuntimeError("quota")

    with pytest.raises(RuntimeError, match="quota"):
        await create_secret_with_owner_ref(
            core,
            namespace="ns",
            secret_name="s",
            values={"A": "1"},
            pod_name="p",
            create_pod_fn=AsyncMock(),
        )
    core.delete_namespaced_pod.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_secret_is_deleted_before_create(monkeypatch):
    _stub_k8s_modules(monkeypatch)
    core = _fake_core()  # delete succeeds -> stale secret existed
    await create_secret_with_owner_ref(
        core,
        namespace="ns",
        secret_name="s",
        values={"A": "1"},
        pod_name="p",
        create_pod_fn=AsyncMock(return_value={}),
    )
    assert core.delete_namespaced_secret.await_args_list[0].kwargs["name"] == "s"
    core.create_namespaced_secret.assert_awaited_once()
