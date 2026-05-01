"""Tests for main.py lifespan — R8/R9 sandbox runtime gate."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from workspaces_api.config import Settings
from workspaces_api.errors import SandboxRuntimeUnavailable
from workspaces_api.main import create_app

_SQLITE_URL = "sqlite+aiosqlite:///:memory:"
_BAD_DB_URL = "postgresql+asyncpg://bad:bad@127.0.0.1:1/bad"


def _local_settings(**overrides) -> Settings:
    base: dict = {
        "SP_DEPLOYMENT_MODE": "local",
        "CLAUDE_CODE_OAUTH_TOKEN": "test-token",
        "WORKSPACES_DATABASE_URL": _SQLITE_URL,
        "SP_USE_SUBPROCESS_SPAWNER": "false",
    }
    base.update(overrides)
    return Settings.model_validate(base)


def _cloud_settings(**overrides) -> Settings:
    base: dict = {
        "SP_DEPLOYMENT_MODE": "cloud",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "WORKSPACES_DATABASE_URL": _SQLITE_URL,
        "SP_USE_SUBPROCESS_SPAWNER": "false",
        "SP_CLERK_JWKS_URL": "https://clerk.example.com/.well-known/jwks.json",
        "SP_CLERK_ISSUER": "https://clerk.example.com",
    }
    base.update(overrides)
    return Settings.model_validate(base)


class TestLifespanRuntimeGate:
    async def test_cloud_mode_none_runtime_raises_before_engine(self) -> None:
        """cloud + SP_SANDBOX_RUNTIME=none must refuse startup before DB pool opens.

        We use a deliberately bad DB URL to confirm the DB is never reached.
        """
        settings = _cloud_settings(
            SP_SANDBOX_RUNTIME="none",
            WORKSPACES_DATABASE_URL=_BAD_DB_URL,
        )
        app = create_app()
        mock_make_engine = MagicMock()

        with patch("workspaces_api.main.get_settings", return_value=settings):
            with patch("workspaces_api.main.make_engine", mock_make_engine):
                with pytest.raises(SandboxRuntimeUnavailable, match="cloud mode requires"):
                    async with app.router.lifespan_context(app):
                        pass

        mock_make_engine.assert_not_called()

    async def test_local_mode_none_runtime_starts_normally(self) -> None:
        """local + SP_SANDBOX_RUNTIME=none (default) must start without runsc."""
        settings = _local_settings(SP_SANDBOX_RUNTIME="none")
        app = create_app()

        with patch("workspaces_api.main.get_settings", return_value=settings):
            async with app.router.lifespan_context(app):
                assert hasattr(app.state, "spawner")

    async def test_cloud_mode_runsc_missing_binary_raises(self) -> None:
        """cloud + SP_SANDBOX_RUNTIME=runsc + missing binary → SandboxRuntimeUnavailable."""
        settings = _cloud_settings(
            SP_SANDBOX_RUNTIME="runsc",
            SP_RUNSC_BINARY="/nonexistent/runsc",
        )
        app = create_app()

        with patch("workspaces_api.main.get_settings", return_value=settings):
            with pytest.raises(SandboxRuntimeUnavailable, match="not found"):
                async with app.router.lifespan_context(app):
                    pass

    async def test_cloud_mode_runsc_bin_true_starts(self) -> None:
        """cloud + SP_SANDBOX_RUNTIME=runsc + /bin/true as binary → app starts."""
        settings = _cloud_settings(
            SP_SANDBOX_RUNTIME="runsc",
            SP_RUNSC_BINARY="/bin/true",
        )
        app = create_app()

        with patch("workspaces_api.main.get_settings", return_value=settings):
            async with app.router.lifespan_context(app):
                assert hasattr(app.state, "spawner")

    async def test_cloud_mode_runc_runtime_raises_at_build_runtime(self) -> None:
        """cloud + SP_SANDBOX_RUNTIME=runc raises SandboxRuntimeUnavailable from
        build_runtime (before the cloud-gate and before engine construction).
        """
        settings = _cloud_settings(
            SP_SANDBOX_RUNTIME="runc",
            WORKSPACES_DATABASE_URL=_BAD_DB_URL,
        )
        app = create_app()
        mock_make_engine = MagicMock()

        with patch("workspaces_api.main.get_settings", return_value=settings):
            with patch("workspaces_api.main.make_engine", mock_make_engine):
                with pytest.raises(SandboxRuntimeUnavailable, match="unknown SP_SANDBOX_RUNTIME"):
                    async with app.router.lifespan_context(app):
                        pass

        mock_make_engine.assert_not_called()

    async def test_cloud_gate_message_includes_received_name(self) -> None:
        """The cloud-gate SandboxRuntimeUnavailable message must include the actual runtime name."""
        settings = _cloud_settings(
            SP_SANDBOX_RUNTIME="none",
            WORKSPACES_DATABASE_URL=_BAD_DB_URL,
        )
        app = create_app()

        with patch("workspaces_api.main.get_settings", return_value=settings):
            with pytest.raises(SandboxRuntimeUnavailable, match="'none'"):
                async with app.router.lifespan_context(app):
                    pass
