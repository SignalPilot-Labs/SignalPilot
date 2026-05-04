"""Tests for Settings configuration validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from workspaces_api.config import Settings


class TestConfig:
    def test_missing_deployment_mode_raises(self) -> None:
        with pytest.raises(ValidationError):
            Settings.model_validate({"WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:"})

    def test_missing_database_url_raises(self) -> None:
        with pytest.raises(ValidationError):
            Settings.model_validate({"SP_DEPLOYMENT_MODE": "local"})

    def test_valid_local_settings(self) -> None:
        s = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "CLAUDE_CODE_OAUTH_TOKEN": "my-secret-token",
        })
        assert s.sp_deployment_mode == "local"
        assert s.database_url == "sqlite+aiosqlite:///:memory:"

    def test_repr_does_not_contain_token_value(self) -> None:
        s = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "CLAUDE_CODE_OAUTH_TOKEN": "super-secret-oauth-token",
        })
        rep = repr(s)
        assert "super-secret-oauth-token" not in rep

    def test_repr_does_not_contain_api_key(self) -> None:
        s = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "cloud",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "ANTHROPIC_API_KEY": "sk-ant-super-secret",
        })
        rep = repr(s)
        assert "sk-ant-super-secret" not in rep
