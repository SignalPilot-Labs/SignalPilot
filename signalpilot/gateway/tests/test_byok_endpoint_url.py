"""Tests for F-23: BYOK endpoint_url SSRF defence.

Two test classes:
- TestAWSKMSProviderEndpointURL  — provider-constructor layer (DNS path).
- TestBYOKKeyCreateValidation    — Pydantic schema layer (pure-syntactic).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

_VALID_KMS_KEY_ARN = "arn:aws:kms:us-east-1:123456789012:key/abcd1234-ab12-ab12-ab12-abcdef123456"


# ─── Provider-constructor layer ───────────────────────────────────────────────


class TestAWSKMSProviderEndpointURL:
    """Verify AWSKMSProvider.__init__ enforces endpoint_url policy."""

    def _make_provider(self, config: dict, monkeypatch) -> None:  # type: ignore[return]
        """Construct AWSKMSProvider with boto3 import mocked out."""
        import gateway.byok.aws_kms as aws_kms_mod

        fake_boto3 = MagicMock()
        fake_boto3.client.return_value = MagicMock()
        monkeypatch.setattr(aws_kms_mod, "_boto3_module", fake_boto3)
        monkeypatch.setattr(aws_kms_mod, "_BOTO3_AVAILABLE", True)

        from gateway.byok.aws_kms import AWSKMSProvider

        return AWSKMSProvider(config)

    def test_cloud_mode_no_env_endpoint_url_raises(self, monkeypatch):
        """In cloud mode with no opt-in env, endpoint_url must be rejected."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.delenv("SP_BYOK_ALLOW_CUSTOM_ENDPOINT", raising=False)

        with pytest.raises(ValueError, match="SP_BYOK_ALLOW_CUSTOM_ENDPOINT"):
            self._make_provider(
                {"kms_key_arn": _VALID_KMS_KEY_ARN, "endpoint_url": "https://evil.example.com/"},
                monkeypatch,
            )

    def test_local_mode_no_env_endpoint_url_allowed(self, monkeypatch):
        """In local mode (SP_DEPLOYMENT_MODE unset), endpoint_url is allowed by default."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        monkeypatch.delenv("SP_BYOK_ALLOW_CUSTOM_ENDPOINT", raising=False)

        # validate_connection_host resolves DNS — patch it out for this test.
        with patch("gateway.byok.aws_kms.validate_connection_host"):
            provider = self._make_provider(
                {
                    "kms_key_arn": _VALID_KMS_KEY_ARN,
                    "endpoint_url": "http://localhost:4566/",
                },
                monkeypatch,
            )
        assert provider._endpoint_url == "http://localhost:4566/"

    def test_cloud_mode_with_env_opt_in_endpoint_url_allowed(self, monkeypatch):
        """Cloud mode + SP_BYOK_ALLOW_CUSTOM_ENDPOINT=1 allows endpoint_url."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_BYOK_ALLOW_CUSTOM_ENDPOINT", "1")

        vpce = "https://kms.vpce-abc.us-east-1.vpce.amazonaws.com"
        with patch("gateway.byok.aws_kms.validate_connection_host"):
            provider = self._make_provider(
                {"kms_key_arn": _VALID_KMS_KEY_ARN, "endpoint_url": vpce},
                monkeypatch,
            )
        assert provider._endpoint_url == vpce

    def test_allowed_imds_hostname_rejected_by_host_validation(self, monkeypatch):
        """A hostname that resolves to 169.254.169.254 must be rejected by host validation."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_BYOK_ALLOW_CUSTOM_ENDPOINT", "1")

        # In cloud mode only https:// is permitted. Use a hostname (not bare IP)
        # so the scheme check passes and validate_connection_host is reached.
        with patch(
            "gateway.byok.aws_kms.validate_connection_host",
            side_effect=ValueError("blocked internal/private address"),
        ):
            with pytest.raises(ValueError, match="blocked internal/private address"):
                self._make_provider(
                    {
                        "kms_key_arn": _VALID_KMS_KEY_ARN,
                        "endpoint_url": "https://imds.attacker.example/",
                    },
                    monkeypatch,
                )

    def test_allowed_loopback_hostname_rejected_by_host_validation(self, monkeypatch):
        """A hostname resolving to loopback must be rejected by validate_connection_host."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_BYOK_ALLOW_CUSTOM_ENDPOINT", "1")

        with patch(
            "gateway.byok.aws_kms.validate_connection_host",
            side_effect=ValueError("blocked internal/private address"),
        ):
            with pytest.raises(ValueError, match="blocked internal/private address"):
                self._make_provider(
                    {
                        "kms_key_arn": _VALID_KMS_KEY_ARN,
                        "endpoint_url": "https://loopback-attacker.example/",
                    },
                    monkeypatch,
                )

    def test_allowed_vpce_hostname_passes(self, monkeypatch):
        """A legitimate AWS PrivateLink VPCE DNS name is accepted."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_BYOK_ALLOW_CUSTOM_ENDPOINT", "1")

        vpce = "https://kms.vpce-abc.us-east-1.vpce.amazonaws.com"
        with patch("gateway.byok.aws_kms.validate_connection_host"):
            provider = self._make_provider(
                {"kms_key_arn": _VALID_KMS_KEY_ARN, "endpoint_url": vpce},
                monkeypatch,
            )
        assert provider._endpoint_url == vpce

    def test_http_scheme_blocked_in_cloud_mode(self, monkeypatch):
        """http:// endpoint_url is blocked in cloud mode even with the env opt-in."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_BYOK_ALLOW_CUSTOM_ENDPOINT", "1")

        with pytest.raises(ValueError, match="scheme"):
            self._make_provider(
                {
                    "kms_key_arn": _VALID_KMS_KEY_ARN,
                    "endpoint_url": "http://kms.example/",
                },
                monkeypatch,
            )


# ─── Pydantic schema layer ────────────────────────────────────────────────────


class TestBYOKKeyCreateValidation:
    """Verify BYOKKeyCreate.provider_config field_validator is pure-syntactic."""

    def _make(self, provider_type: str, provider_config) -> None:  # type: ignore[return]
        from gateway.models.byok import BYOKKeyCreate

        return BYOKKeyCreate(
            key_alias="test-key",
            provider_type=provider_type,
            provider_config=provider_config,
        )

    def _assert_validation_error(self, provider_type: str, provider_config) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make(provider_type, provider_config)

    def test_aws_kms_none_config_raises(self, monkeypatch):
        """provider_config=None for aws_kms must surface as ValidationError (S2)."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        self._assert_validation_error("aws_kms", None)

    def test_aws_kms_missing_kms_key_arn_raises(self, monkeypatch):
        """endpoint_url without kms_key_arn must fail validation (S5)."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        monkeypatch.setenv("SP_BYOK_ALLOW_CUSTOM_ENDPOINT", "1")
        self._assert_validation_error("aws_kms", {"endpoint_url": "https://x/"})

    def test_aws_kms_invalid_arn_raises(self, monkeypatch):
        """A non-ARN kms_key_arn must be rejected."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        self._assert_validation_error("aws_kms", {"kms_key_arn": "not-an-arn"})

    def test_endpoint_url_blocked_in_cloud_without_env(self, monkeypatch):
        """endpoint_url in cloud mode without opt-in env must be rejected."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.delenv("SP_BYOK_ALLOW_CUSTOM_ENDPOINT", raising=False)
        self._assert_validation_error(
            "aws_kms",
            {"kms_key_arn": _VALID_KMS_KEY_ARN, "endpoint_url": "http://evil/"},
        )

    def test_literal_ip_rejected_even_with_env(self, monkeypatch):
        """Literal IP in endpoint_url is rejected at syntactic layer even when opt-in is set."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_BYOK_ALLOW_CUSTOM_ENDPOINT", "1")
        self._assert_validation_error(
            "aws_kms",
            {"kms_key_arn": _VALID_KMS_KEY_ARN, "endpoint_url": "http://127.0.0.1/"},
        )

    def test_unknown_key_raises(self, monkeypatch):
        """Unrecognised top-level key in provider_config must be rejected."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        self._assert_validation_error(
            "aws_kms",
            {"kms_key_arn": _VALID_KMS_KEY_ARN, "junk_field": 1},
        )

    def test_endpoint_url_too_long_raises(self, monkeypatch):
        """endpoint_url exceeding max_length cap must be rejected."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        monkeypatch.setenv("SP_BYOK_ALLOW_CUSTOM_ENDPOINT", "1")
        self._assert_validation_error(
            "aws_kms",
            {"kms_key_arn": _VALID_KMS_KEY_ARN, "endpoint_url": "https://x.com/" + "x" * 3000},
        )

    def test_local_provider_non_empty_config_raises(self, monkeypatch):
        """Non-empty provider_config for local provider must be rejected."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        self._assert_validation_error("local", {"key": "value"})

    def test_aws_kms_valid_happy_path(self, monkeypatch):
        """Valid aws_kms config must be accepted without error."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        obj = self._make("aws_kms", {"kms_key_arn": _VALID_KMS_KEY_ARN})
        assert obj.provider_config is not None
        assert obj.provider_config["kms_key_arn"] == _VALID_KMS_KEY_ARN

    def test_local_provider_none_config_valid(self, monkeypatch):
        """local provider with provider_config=None must be accepted."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        obj = self._make("local", None)
        assert obj.provider_config is None

    def test_local_provider_empty_dict_config_valid(self, monkeypatch):
        """local provider with provider_config={} must be accepted."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        obj = self._make("local", {})
        assert obj.provider_config == {}

    def test_aws_kms_valid_with_https_endpoint_url(self, monkeypatch):
        """aws_kms config with valid https endpoint_url in local mode must be accepted."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        monkeypatch.setenv("SP_BYOK_ALLOW_CUSTOM_ENDPOINT", "1")
        obj = self._make(
            "aws_kms",
            {"kms_key_arn": _VALID_KMS_KEY_ARN, "endpoint_url": "https://localstack.example.com/"},
        )
        assert obj.provider_config is not None
        assert "endpoint_url" in obj.provider_config
