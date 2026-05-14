"""Tests for main.py lifespan — cloud mode startup checks."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from workspaces_api.config import Settings
from workspaces_api.errors import ClerkConfigMissing
from workspaces_api.main import create_app

_SQLITE_URL = "sqlite+aiosqlite:///:memory:"


def _make_cloud_settings(**overrides) -> Settings:
    base = {
        "SP_DEPLOYMENT_MODE": "cloud",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "WORKSPACES_DATABASE_URL": _SQLITE_URL,
        "SP_USE_SUBPROCESS_SPAWNER": "false",
    }
    base.update(overrides)
    return Settings.model_validate(base)


class TestLifespanCloudConfig:
    async def test_lifespan_raises_clerk_config_missing_when_jwks_url_unset_in_cloud(
        self,
    ) -> None:
        """Cloud mode without SP_CLERK_JWKS_URL must fail at startup."""
        settings = _make_cloud_settings(
            SP_CLERK_ISSUER="https://clerk.example.com",
            # No SP_CLERK_JWKS_URL
        )
        app = create_app()

        with patch("workspaces_api.main.get_settings", return_value=settings):
            with pytest.raises(ClerkConfigMissing, match="SP_CLERK_JWKS_URL"):
                async with app.router.lifespan_context(app):
                    pass

    async def test_lifespan_raises_clerk_config_missing_when_issuer_unset_in_cloud(
        self,
    ) -> None:
        """Cloud mode without SP_CLERK_ISSUER must fail at startup."""
        settings = _make_cloud_settings(
            SP_CLERK_JWKS_URL="https://clerk.example.com/.well-known/jwks.json",
            # No SP_CLERK_ISSUER
        )
        app = create_app()

        with patch("workspaces_api.main.get_settings", return_value=settings):
            with pytest.raises(ClerkConfigMissing, match="SP_CLERK_ISSUER"):
                async with app.router.lifespan_context(app):
                    pass

    async def test_lifespan_passes_in_local_mode_with_no_clerk_settings(
        self,
    ) -> None:
        """Local mode requires no Clerk settings — must start cleanly."""
        settings = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "CLAUDE_CODE_OAUTH_TOKEN": "test-token",
            "WORKSPACES_DATABASE_URL": _SQLITE_URL,
            "SP_USE_SUBPROCESS_SPAWNER": "false",
        })
        app = create_app()

        with patch("workspaces_api.main.get_settings", return_value=settings):
            async with app.router.lifespan_context(app):
                # Startup should complete without error
                assert hasattr(app.state, "jwks_client")
