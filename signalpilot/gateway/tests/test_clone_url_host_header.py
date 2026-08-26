"""R11-S-1: Clone URL uses SP_PUBLIC_GATEWAY_URL in cloud mode, not request Host.

Tests that in cloud mode the configured public gateway URL is used for the
git clone URL, and that a spoofed Host header cannot influence the result.
In local mode with the compose default, the Host header fallback is used.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_request(host: str = "localhost:3300", scheme: str = "http") -> MagicMock:
    """Build a minimal FastAPI Request mock."""
    request = MagicMock()
    # Use a real dict-like object so .get() works correctly
    headers: dict[str, str] = {"host": host}
    request.headers = MagicMock()
    request.headers.get = lambda key, default="": headers.get(key, default)
    request.url = MagicMock()
    request.url.scheme = scheme
    request.state = MagicMock()
    request.state.auth = {"auth_method": "api_key"}
    return request


def _make_project() -> MagicMock:
    """Build a minimal workspace project mock."""
    proj = MagicMock()
    proj.default_branch = "main"
    proj.source = "managed"
    return proj


# ─── Tests ───────────────────────────────────────────────────────────────────


class TestCloneUrlHostHeader:
    """R11-S-1: Clone URL base is derived from SP_PUBLIC_GATEWAY_URL in cloud mode."""

    @pytest.mark.asyncio
    async def test_clone_url_ignores_spoofed_host_in_cloud_mode(self, monkeypatch) -> None:
        """Cloud mode: clone URL uses configured gateway URL; Host header is ignored."""
        from gateway.api.workspace_projects import get_clone_url
        from gateway.config.k8s import K8sSettings

        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")

        fake_settings = MagicMock(spec=K8sSettings)
        fake_settings.sp_public_gateway_url = "https://configured-gw.example.com"

        fake_store = MagicMock()
        fake_store.get_workspace_project = AsyncMock(return_value=_make_project())

        request = _make_request(host="attacker.evil", scheme="https")

        with patch("gateway.api.workspace_projects.get_k8s_settings", return_value=fake_settings), \
             patch("gateway.api.workspace_projects.is_cloud_mode", return_value=True), \
             patch("gateway.git.repos.repo_exists", return_value=True):
            result = await get_clone_url(
                project_id="proj-test-123",
                store=fake_store,
                request=request,
            )

        assert result["clone_url"].startswith("https://configured-gw.example.com/git/")
        assert "attacker.evil" not in result["clone_url"]

    @pytest.mark.asyncio
    async def test_clone_url_uses_host_header_in_local_mode_with_default(self, monkeypatch) -> None:
        """Local mode + compose default: clone URL falls back to inbound Host header."""
        from gateway.api.workspace_projects import get_clone_url
        from gateway.config.k8s import _LOCAL_GATEWAY_URL_DEFAULT, K8sSettings

        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")

        fake_settings = MagicMock(spec=K8sSettings)
        # Simulate the local default — should trigger Host header fallback
        fake_settings.sp_public_gateway_url = _LOCAL_GATEWAY_URL_DEFAULT

        fake_store = MagicMock()
        fake_store.get_workspace_project = AsyncMock(return_value=_make_project())

        request = _make_request(host="localhost:12345", scheme="http")

        with patch("gateway.api.workspace_projects.get_k8s_settings", return_value=fake_settings), \
             patch("gateway.api.workspace_projects.is_cloud_mode", return_value=False), \
             patch("gateway.git.repos.repo_exists", return_value=True):
            result = await get_clone_url(
                project_id="proj-test-456",
                store=fake_store,
                request=request,
            )

        assert "localhost:12345" in result["clone_url"]

    @pytest.mark.asyncio
    async def test_clone_url_uses_host_header_in_local_mode_with_loopback_public_url(self, monkeypatch) -> None:
        """Local Compose: browser public URL is loopback, but notebook clone URL uses gateway host."""
        from gateway.api.workspace_projects import get_clone_url
        from gateway.config.k8s import K8sSettings

        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")

        fake_settings = MagicMock(spec=K8sSettings)
        fake_settings.sp_public_gateway_url = "http://localhost:3300"

        fake_store = MagicMock()
        fake_store.get_workspace_project = AsyncMock(return_value=_make_project())

        request = _make_request(host="gateway:3300", scheme="http")

        with patch("gateway.api.workspace_projects.get_k8s_settings", return_value=fake_settings), \
             patch("gateway.api.workspace_projects.is_cloud_mode", return_value=False), \
             patch("gateway.git.repos.repo_exists", return_value=True):
            result = await get_clone_url(
                project_id="proj-test-789",
                store=fake_store,
                request=request,
            )

        assert result["clone_url"].startswith("http://gateway:3300/git/")
        assert "localhost:3300" not in result["clone_url"]
