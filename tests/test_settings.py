"""Tests for GatewaySettings model — blocked tables and governance defaults."""

import json

from signalpilot.gateway.gateway.models import GatewaySettings


class TestGatewaySettings:
    """Tests for the GatewaySettings Pydantic model."""

    def test_default_blocked_tables_empty(self):
        settings = GatewaySettings()
        assert settings.blocked_tables == []

    def test_blocked_tables_from_dict(self):
        settings = GatewaySettings(blocked_tables=["users_private", "secrets"])
        assert settings.blocked_tables == ["users_private", "secrets"]

    def test_blocked_tables_serialization(self):
        settings = GatewaySettings(blocked_tables=["internal_logs"])
        data = settings.model_dump()
        assert data["blocked_tables"] == ["internal_logs"]

    def test_blocked_tables_json_round_trip(self):
        settings = GatewaySettings(blocked_tables=["creds", "tokens"])
        json_str = settings.model_dump_json()
        restored = GatewaySettings(**json.loads(json_str))
        assert restored.blocked_tables == ["creds", "tokens"]

    def test_default_governance_values(self):
        settings = GatewaySettings()
        assert settings.default_row_limit == 10_000
        assert settings.default_budget_usd == 10.0
        assert settings.default_timeout_seconds == 30
        assert settings.max_concurrent_sandboxes == 10

    def test_api_key_optional(self):
        settings = GatewaySettings()
        assert settings.api_key is None

    def test_settings_with_all_fields(self):
        settings = GatewaySettings(
            sandbox_provider="local",
            sandbox_manager_url="http://test:8180",
            default_row_limit=5000,
            default_budget_usd=5.0,
            default_timeout_seconds=60,
            max_concurrent_sandboxes=20,
            blocked_tables=["secrets", "credentials", "audit_internal"],
            gateway_url="http://test:3300",
            api_key="sp_testkey123",
        )
        assert settings.blocked_tables == ["secrets", "credentials", "audit_internal"]
        assert settings.default_row_limit == 5000
        assert settings.api_key == "sp_testkey123"
