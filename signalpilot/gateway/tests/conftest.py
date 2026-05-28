"""Test configuration for the SignalPilot gateway test suite."""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure the gateway package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SP_DEPLOYMENT_MODE", "local")


@pytest.fixture
def test_org_id() -> str:
    return "test-org"


@pytest.fixture(autouse=True)
def _set_governance_org(test_org_id: str):
    """Autouse fixture: set the governance contextvar for every test.

    All governance singletons (BudgetLedger, QueryCache, SchemaCache) require
    current_org_id_var to be set before any method call. This fixture ensures
    every test runs inside a clean org context and resets it afterward.
    """
    from gateway.governance.context import current_org_id_var

    token = current_org_id_var.set(test_org_id)
    yield
    current_org_id_var.reset(token)


@pytest.fixture
def test_user_id() -> str:
    return "test-user"


@pytest.fixture
def fake_k8s_core_api() -> MagicMock:
    """Fake CoreV1Api stub for namespace bootstrap tests."""
    api = MagicMock()
    api.create_namespace = AsyncMock()
    api.create_namespaced_resource_quota = AsyncMock()
    api.create_namespaced_limit_range = AsyncMock()
    api.create_namespaced_pod = AsyncMock()
    api.delete_namespaced_pod = AsyncMock()
    api.read_namespaced_pod = AsyncMock()
    return api


@pytest.fixture
def fake_k8s_networking_api() -> MagicMock:
    """Fake NetworkingV1Api stub for namespace bootstrap tests."""
    api = MagicMock()
    api.create_namespaced_network_policy = AsyncMock()
    return api


@pytest.fixture
def fake_k8s_rbac_api() -> MagicMock:
    """Fake RbacAuthorizationV1Api stub for namespace bootstrap tests."""
    api = MagicMock()
    api.create_namespaced_role = AsyncMock()
    api.create_namespaced_role_binding = AsyncMock()
    return api


def pytest_runtest_setup(item):
    """Reset rate limiter state before each test to prevent 429 bleed-across.

    The in-memory RateLimitMiddleware accumulates hits across tests in the
    same process. When multiple test modules run sequentially with a shared
    app singleton, the accumulated hits from earlier tests can trigger 429
    responses in later tests that expect 403 or 200.

    This hook finds the RateLimitMiddleware instance on the built middleware
    stack (if the app has been started) and clears all hit buckets.
    """
    try:
        from gateway.http import RateLimitMiddleware
        from gateway.main import app

        current = app.middleware_stack
        while current is not None:
            if isinstance(current, RateLimitMiddleware):
                current._general_hits.clear()
                current._expensive_hits.clear()
                current._auth_hits.clear()
                break
            current = getattr(current, "app", None)
    except Exception:
        pass
