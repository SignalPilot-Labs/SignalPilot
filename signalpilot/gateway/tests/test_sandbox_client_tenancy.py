"""Sandbox clients must be per-org, and the platform secret must stay platform-only.

Sandbox endpoint + key are org-scoped settings. A cached client shared across
orgs would route one tenant's code execution to another tenant's endpoint, and
a platform-wide token attached to a tenant-supplied URL hands that tenant the
credential for the platform sandbox.
"""

from __future__ import annotations

import pytest

from gateway.api import deps
from gateway.models import GatewaySettings
from gateway.network.sandbox_client import SandboxClient

PLATFORM_URL = "http://sandbox-manager.internal:8180"
ORG_A_URL = "http://sandbox-a.example.test:8180"
ORG_B_URL = "http://sandbox-b.example.test:8180"
PLATFORM_TOKEN = "platform-shared-secret"


class FakeStore:
    """Minimal stand-in for Store: org id + org-scoped settings."""

    def __init__(self, org_id: str, settings: GatewaySettings):
        self.org_id = org_id
        self._settings = settings

    def set_settings(self, settings: GatewaySettings) -> None:
        self._settings = settings

    async def load_settings(self) -> GatewaySettings:
        return self._settings


def _settings(url: str, api_key: str | None = None) -> GatewaySettings:
    return GatewaySettings(sandbox_manager_url=url, sandbox_api_key=api_key)


@pytest.fixture
def sandbox_env(monkeypatch):
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
    monkeypatch.setenv("SP_SANDBOX_MANAGER_URL", PLATFORM_URL)
    monkeypatch.setenv("SP_SANDBOX_TOKEN", PLATFORM_TOKEN)
    deps._sandbox_clients.clear()
    deps._platform_sandbox_client = None
    yield
    deps._sandbox_clients.clear()
    deps._platform_sandbox_client = None


class TestPerOrgIsolation:
    async def test_each_org_gets_its_own_client_and_url(self, sandbox_env) -> None:
        store_a = FakeStore("org-a", _settings(ORG_A_URL))
        store_b = FakeStore("org-b", _settings(ORG_B_URL))

        client_a = await deps.get_sandbox_client_with_store(store_a)
        client_b = await deps.get_sandbox_client_with_store(store_b)

        assert client_a is not client_b
        assert client_a.base_url == ORG_A_URL
        assert client_b.base_url == ORG_B_URL

    async def test_org_b_never_inherits_org_a_endpoint(self, sandbox_env) -> None:
        """Org A initializing first must not decide org B's endpoint."""
        store_a = FakeStore("org-a", _settings(ORG_A_URL))
        store_b = FakeStore("org-b", _settings(ORG_B_URL))

        await deps.get_sandbox_client_with_store(store_a)
        client_b = await deps.get_sandbox_client_with_store(store_b)

        assert client_b.base_url != ORG_A_URL
        assert client_b.base_url == ORG_B_URL

    async def test_same_org_reuses_client(self, sandbox_env) -> None:
        store = FakeStore("org-a", _settings(ORG_A_URL))
        first = await deps.get_sandbox_client_with_store(store)
        second = await deps.get_sandbox_client_with_store(store)
        assert first is second

    async def test_config_change_rebuilds_client(self, sandbox_env) -> None:
        store = FakeStore("org-a", _settings(ORG_A_URL))
        first = await deps.get_sandbox_client_with_store(store)

        store.set_settings(_settings(ORG_B_URL))
        second = await deps.get_sandbox_client_with_store(store)

        assert second is not first
        assert second.base_url == ORG_B_URL

    async def test_credential_change_rebuilds_client(self, sandbox_env) -> None:
        store = FakeStore("org-a", _settings(ORG_A_URL, "key-one"))
        first = await deps.get_sandbox_client_with_store(store)

        store.set_settings(_settings(ORG_A_URL, "key-two"))
        second = await deps.get_sandbox_client_with_store(store)

        assert second is not first
        assert second._client.headers["Authorization"] == "Bearer key-two"


class TestResetIsOrgScoped:
    async def test_reset_of_org_a_leaves_org_b_untouched(self, sandbox_env) -> None:
        store_a = FakeStore("org-a", _settings(ORG_A_URL))
        store_b = FakeStore("org-b", _settings(ORG_B_URL))

        await deps.get_sandbox_client_with_store(store_a)
        client_b = await deps.get_sandbox_client_with_store(store_b)

        deps.reset_sandbox_client("org-a")

        assert await deps.get_sandbox_client_with_store(store_b) is client_b
        assert deps._sandbox_clients["org-b"][1].base_url == ORG_B_URL

    async def test_reset_of_org_a_rebuilds_only_org_a(self, sandbox_env) -> None:
        store_a = FakeStore("org-a", _settings(ORG_A_URL))
        client_a = await deps.get_sandbox_client_with_store(store_a)

        deps.reset_sandbox_client("org-a")
        store_a.set_settings(_settings(ORG_B_URL))
        rebuilt = await deps.get_sandbox_client_with_store(store_a)

        assert rebuilt is not client_a
        assert rebuilt.base_url == ORG_B_URL

    async def test_unscoped_reset_does_not_clear_org_entries(self, sandbox_env) -> None:
        store_a = FakeStore("org-a", _settings(ORG_A_URL))
        client_a = await deps.get_sandbox_client_with_store(store_a)

        deps.reset_sandbox_client()

        assert await deps.get_sandbox_client_with_store(store_a) is client_a


class TestPlatformTokenScoping:
    def test_token_not_sent_to_tenant_endpoint(self, sandbox_env) -> None:
        client = SandboxClient(base_url=ORG_A_URL, api_key="tenant-key")
        assert client.is_platform is False
        assert "X-Sandbox-Auth" not in client._client.headers
        assert PLATFORM_TOKEN not in str(dict(client._client.headers))

    def test_tenant_key_is_the_only_credential(self, sandbox_env) -> None:
        client = SandboxClient(base_url=ORG_A_URL, api_key="tenant-key")
        assert client._client.headers["Authorization"] == "Bearer tenant-key"

    def test_tenant_endpoint_without_key_gets_no_credentials(self, sandbox_env) -> None:
        client = SandboxClient(base_url=ORG_A_URL)
        assert "Authorization" not in client._client.headers
        assert "X-Sandbox-Auth" not in client._client.headers

    def test_token_sent_to_platform_endpoint(self, sandbox_env) -> None:
        client = SandboxClient(base_url=PLATFORM_URL)
        assert client.is_platform is True
        assert client._client.headers["X-Sandbox-Auth"] == PLATFORM_TOKEN

    def test_platform_match_ignores_trailing_slash_and_case(self, sandbox_env) -> None:
        client = SandboxClient(base_url="http://SANDBOX-MANAGER.internal:8180/")
        assert client.is_platform is True

    async def test_org_configured_platform_url_still_gets_token(self, sandbox_env) -> None:
        """Default settings point at the platform sandbox — that path keeps the token."""
        store = FakeStore("org-a", _settings(PLATFORM_URL))
        client = await deps.get_sandbox_client_with_store(store)
        assert client._client.headers["X-Sandbox-Auth"] == PLATFORM_TOKEN

    async def test_byos_org_client_carries_no_platform_token(self, sandbox_env) -> None:
        store = FakeStore("org-a", _settings(ORG_A_URL, "tenant-key"))
        client = await deps.get_sandbox_client_with_store(store)
        assert "X-Sandbox-Auth" not in client._client.headers
        assert client._client.headers["Authorization"] == "Bearer tenant-key"


class TestLegacyUnscopedClient:
    async def test_legacy_getter_never_returns_a_tenant_client(self, sandbox_env) -> None:
        store_a = FakeStore("org-a", _settings(ORG_A_URL, "tenant-key"))
        tenant_client = await deps.get_sandbox_client_with_store(store_a)

        legacy = deps.get_sandbox_client()

        assert legacy is not tenant_client
        assert legacy.base_url == PLATFORM_URL
        assert legacy.is_platform is True

    def test_legacy_getter_503_without_platform_url(self, sandbox_env, monkeypatch) -> None:
        from fastapi import HTTPException

        monkeypatch.delenv("SP_SANDBOX_MANAGER_URL", raising=False)
        with pytest.raises(HTTPException) as exc:
            deps.get_sandbox_client()
        assert exc.value.status_code == 503
