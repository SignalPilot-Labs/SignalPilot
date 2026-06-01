"""Tests for per-org SandboxClient cache isolation (APP-M-2).

Verifies that get_sandbox_client_with_store returns org-scoped clients and that
cross-org settings cannot leak between organisations.

Imports are deferred inside functions to avoid triggering gateway/api/__init__.py,
which pulls in the full application stack (FastAPI + sqlglot + etc.) unavailable
in the lightweight test environment. This mirrors the pattern in
test_notebook_pvc_subpath.py.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest


def _load_deps():
    """Load gateway.api.deps directly, bypassing the package __init__.py."""
    return importlib.import_module("gateway.api.deps")


def _make_store(org_id: str, url: str, api_key: str) -> MagicMock:
    """Return a mock Store with org_id and async load_settings."""
    from gateway.models import GatewaySettings

    store = MagicMock()
    store.org_id = org_id
    settings = GatewaySettings(sandbox_manager_url=url, sandbox_api_key=api_key)
    store.load_settings = AsyncMock(return_value=settings)
    return store


@pytest.fixture(autouse=True)
def _clear_sandbox_clients():
    """Clear the sandbox client cache before and after each test.

    Directly clears the dict rather than calling reset_sandbox_client() to
    avoid scheduling asyncio.create_task(client.close()) during teardown,
    which can emit unclosed-transport warnings when no real network calls have
    been made.
    """
    deps = _load_deps()
    deps._sandbox_clients.clear()
    yield
    deps._sandbox_clients.clear()


class TestSandboxClientIsolation:
    @pytest.mark.asyncio
    async def test_two_orgs_get_distinct_clients(self) -> None:
        """Two different orgs get distinct SandboxClient instances."""
        deps = _load_deps()
        store_a = _make_store("org-A", "http://sandbox-a.example", "key-a")
        store_b = _make_store("org-B", "http://sandbox-b.example", "key-b")

        client_a = await deps.get_sandbox_client_with_store(store_a)
        client_b = await deps.get_sandbox_client_with_store(store_b)

        assert client_a is not client_b
        assert client_a.base_url == "http://sandbox-a.example"
        assert client_b.base_url == "http://sandbox-b.example"

    @pytest.mark.asyncio
    async def test_same_org_returns_cached_client(self) -> None:
        """Repeated calls for the same org and settings return the same instance."""
        deps = _load_deps()
        store = _make_store("org-A", "http://sandbox-a.example", "key-a")

        client_first = await deps.get_sandbox_client_with_store(store)
        client_second = await deps.get_sandbox_client_with_store(store)

        assert client_first is client_second

    @pytest.mark.asyncio
    async def test_reset_clears_all_orgs(self) -> None:
        """reset_sandbox_client empties the cache for all orgs."""
        deps = _load_deps()
        store_a = _make_store("org-A", "http://sandbox-a.example", "key-a")
        store_b = _make_store("org-B", "http://sandbox-b.example", "key-b")

        await deps.get_sandbox_client_with_store(store_a)
        await deps.get_sandbox_client_with_store(store_b)
        assert len(deps._sandbox_clients) == 2

        deps.reset_sandbox_client()

        assert deps._sandbox_clients == {}

    @pytest.mark.asyncio
    async def test_settings_change_misses_cache(self) -> None:
        """Same org_id but different sandbox_manager_url returns a new client."""
        deps = _load_deps()
        store_original = _make_store("org-A", "http://sandbox-a.example", "key-a")
        store_updated = _make_store("org-A", "http://sandbox-a-new.example", "key-a-new")

        client_original = await deps.get_sandbox_client_with_store(store_original)
        client_updated = await deps.get_sandbox_client_with_store(store_updated)

        assert client_original is not client_updated
        assert client_original.base_url == "http://sandbox-a.example"
        assert client_updated.base_url == "http://sandbox-a-new.example"
        # Old client remains in cache under its original key — confirms dict semantics
        assert len(deps._sandbox_clients) == 2
