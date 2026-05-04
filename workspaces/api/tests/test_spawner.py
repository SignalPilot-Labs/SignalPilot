"""Tests for StubSpawner — verifies call recording and token non-leakage.

The no-token-in-logs invariant is enforced HERE (test-time only).
There is no runtime assertion in production code — StubSpawner.spawn
appends the SpawnRequest without any token check.
"""

from __future__ import annotations

import uuid

import pytest

from workspaces_api.agent.inference import InferenceBundle
from workspaces_api.agent.spawner import SpawnRequest, StubSpawner


def _make_bundle(oauth_token: str | None = None, api_key: str | None = None) -> InferenceBundle:
    return InferenceBundle(
        mode="local" if oauth_token else "byo",
        oauth_token=oauth_token,
        api_key=api_key,
        base_url=None,
    )


def _make_request(bundle: InferenceBundle) -> SpawnRequest:
    return SpawnRequest(
        run_id=uuid.uuid4(),
        workspace_id="ws-001",
        prompt="analyse sales data",
        inference=bundle,
        gateway_run_token=None,
        dbt_proxy_host_port=None,
        connector_name=None,
        sandbox_internal_secret="deadbeef" * 8,
    )


class TestStubSpawner:
    async def test_stub_spawner_records_call(self) -> None:
        spawner = StubSpawner()
        bundle = _make_bundle(oauth_token="secret-token")
        req = _make_request(bundle)
        await spawner.spawn(req)
        assert len(spawner.calls) == 1
        assert spawner.calls[0] is req

    async def test_stub_spawner_accumulates_multiple_calls(self) -> None:
        spawner = StubSpawner()
        bundle = _make_bundle(oauth_token="secret-token")
        req1 = _make_request(bundle)
        req2 = _make_request(bundle)
        await spawner.spawn(req1)
        await spawner.spawn(req2)
        assert len(spawner.calls) == 2

    def test_spawn_request_is_frozen(self) -> None:
        bundle = _make_bundle(oauth_token="secret-token")
        req = _make_request(bundle)
        with pytest.raises((AttributeError, TypeError)):
            req.workspace_id = "modified"  # type: ignore[misc]

    def test_formatted_log_line_does_not_contain_oauth_token(self) -> None:
        secret = "my-super-secret-oauth-token"
        bundle = _make_bundle(oauth_token=secret)
        req = _make_request(bundle)
        log_line = f"spawn {req!r}"
        assert secret not in log_line

    def test_formatted_log_line_does_not_contain_api_key(self) -> None:
        secret = "sk-ant-very-secret-key"
        bundle = _make_bundle(api_key=secret)
        req = _make_request(bundle)
        log_line = f"spawn {req!r}"
        assert secret not in log_line

    def test_inference_bundle_repr_masks_oauth_token(self) -> None:
        secret = "oauth-secret-12345"
        bundle = _make_bundle(oauth_token=secret)
        assert secret not in repr(bundle)
        assert "***" in repr(bundle)

    def test_inference_bundle_repr_masks_api_key(self) -> None:
        secret = "sk-ant-api-key-secret"
        bundle = _make_bundle(api_key=secret)
        assert secret not in repr(bundle)
        assert "***" in repr(bundle)

    def test_spawn_request_repr_masks_sandbox_internal_secret(self) -> None:
        secret = "cafebabe" * 8
        bundle = _make_bundle(oauth_token="tok")
        req = SpawnRequest(
            run_id=uuid.uuid4(),
            workspace_id="ws-001",
            prompt="test",
            inference=bundle,
            gateway_run_token=None,
            dbt_proxy_host_port=None,
            connector_name=None,
            sandbox_internal_secret=secret,
        )
        assert secret not in repr(req)
        assert "***" in repr(req)

    def test_spawn_request_repr_masks_gateway_run_token(self) -> None:
        bundle = _make_bundle(oauth_token="tok")
        req = SpawnRequest(
            run_id=uuid.uuid4(),
            workspace_id="ws-001",
            prompt="test",
            inference=bundle,
            gateway_run_token="gateway-secret-token",
            dbt_proxy_host_port=None,
            connector_name=None,
            sandbox_internal_secret="deadbeef" * 8,
        )
        assert "gateway-secret-token" not in repr(req)
        assert "***" in repr(req)
