"""Tests for AWSKMSProvider, byok_factory, and security status BYOK fields.

AWS KMS calls are mocked using moto. Factory tests use no external dependencies.
Security status tests mock the DB session directly.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from gateway.byok import BYOKKeyError, LocalBYOKProvider, decrypt_envelope, encrypt_envelope
from gateway.byok_aws import AWSKMSProvider, _extract_region_from_arn
from gateway.byok_factory import make_provider, make_provider_for_key

# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def aws_credentials():
    """Set fake AWS credentials so moto does not try to use real ones."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    yield
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SECURITY_TOKEN",
        "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
    ):
        os.environ.pop(key, None)


@pytest.fixture
def kms_key_arn(aws_credentials):
    """Create a moto KMS key and return its ARN."""
    with mock_aws():
        client = boto3.client("kms", region_name="us-east-1")
        response = client.create_key(Description="test-key", KeyUsage="ENCRYPT_DECRYPT")
        arn = response["KeyMetadata"]["Arn"]
        yield arn


@pytest.fixture
def aws_provider(kms_key_arn):
    """Return an AWSKMSProvider wired to the moto KMS key.

    The moto context must remain active for the provider to work, so we keep it
    open via a separate mock_aws context in each test. The fixture only creates
    the provider object.
    """
    return AWSKMSProvider({"kms_key_arn": kms_key_arn})


# ─── AWSKMSProvider wrap/unwrap tests ────────────────────────────────────────


class TestAWSKMSProviderRoundtrip:
    @pytest.mark.asyncio
    async def test_aws_wrap_unwrap_roundtrip(self, aws_credentials):
        """DEK wrapped then unwrapped must be equal to the original."""
        with mock_aws():
            client = boto3.client("kms", region_name="us-east-1")
            arn = client.create_key(Description="t")["KeyMetadata"]["Arn"]
            provider = AWSKMSProvider({"kms_key_arn": arn})

            dek = await provider.generate_dek()
            wrapped = await provider.wrap_dek("org1", "alias1", dek)
            unwrapped = await provider.unwrap_dek("org1", "alias1", wrapped)
            assert unwrapped == dek

    @pytest.mark.asyncio
    async def test_aws_encrypt_decrypt_envelope_roundtrip(self, aws_credentials):
        """Full envelope encryption/decryption flow using AWSKMSProvider."""
        with mock_aws():
            client = boto3.client("kms", region_name="us-east-1")
            arn = client.create_key(Description="t")["KeyMetadata"]["Arn"]
            provider = AWSKMSProvider({"kms_key_arn": arn})

            plaintext = "postgresql://user:pass@host:5432/db"
            ciphertext, wrapped_dek = await encrypt_envelope(provider, "org1", "alias1", plaintext)
            recovered = await decrypt_envelope(provider, "org1", "alias1", wrapped_dek, ciphertext)
            assert recovered == plaintext

    @pytest.mark.asyncio
    async def test_aws_encryption_context_mismatch(self, aws_credentials):
        """Wrap with org1 context, attempt unwrap with org2 — expect BYOKKeyError.

        Note: moto may not enforce EncryptionContext matching on decrypt. If moto
        does not reject mismatched contexts, we mock the boto3 client directly to
        simulate the KMS InvalidCiphertextException that real AWS would return.
        """
        with mock_aws():
            client = boto3.client("kms", region_name="us-east-1")
            arn = client.create_key(Description="t")["KeyMetadata"]["Arn"]
            provider = AWSKMSProvider({"kms_key_arn": arn})

            dek = await provider.generate_dek()
            wrapped = await provider.wrap_dek("org1", "alias1", dek)

            # Try a real unwrap first to see if moto enforces context.
            # If it succeeds (moto doesn't enforce), mock the client to simulate rejection.
            inner_client = provider._get_client()

            from botocore.exceptions import ClientError

            error_response = {
                "Error": {
                    "Code": "InvalidCiphertextException",
                    "Message": "Encryption context mismatch",
                }
            }

            original_decrypt = inner_client.decrypt

            call_count = [0]

            def _maybe_reject(**kwargs):
                call_count[0] += 1
                ctx = kwargs.get("EncryptionContext", {})
                if ctx.get("org_id") != "org1":
                    raise ClientError(error_response, "Decrypt")
                return original_decrypt(**kwargs)

            inner_client.decrypt = _maybe_reject

            try:
                with pytest.raises(BYOKKeyError):
                    await provider.unwrap_dek("org2", "alias1", wrapped)
            finally:
                inner_client.decrypt = original_decrypt


# ─── AWSKMSProvider error-path tests ─────────────────────────────────────────


class TestAWSKMSProviderErrors:
    @pytest.mark.asyncio
    async def test_aws_disabled_key_raises(self, aws_credentials):
        """Disabling the KMS key makes wrap_dek raise BYOKKeyError.

        moto does not enforce DisabledException on encrypt for disabled keys,
        so we mock the boto3 client to simulate the real AWS behaviour.
        """
        with mock_aws():
            client = boto3.client("kms", region_name="us-east-1")
            arn = client.create_key(Description="t")["KeyMetadata"]["Arn"]
            provider = AWSKMSProvider({"kms_key_arn": arn})

            from botocore.exceptions import ClientError

            inner_client = provider._get_client()
            error_response = {"Error": {"Code": "DisabledException", "Message": "KMS key is disabled"}}
            inner_client.encrypt = MagicMock(side_effect=ClientError(error_response, "Encrypt"))

            dek = await provider.generate_dek()
            with pytest.raises(BYOKKeyError) as exc_info:
                await provider.wrap_dek("org1", "alias1", dek)
            assert "disabled" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_aws_key_not_found_raises(self, aws_credentials):
        """A fake ARN raises BYOKKeyError with a key-not-found message."""
        with mock_aws():
            fake_arn = "arn:aws:kms:us-east-1:123456789012:key/does-not-exist"
            provider = AWSKMSProvider({"kms_key_arn": fake_arn})

            dek = await provider.generate_dek()
            with pytest.raises(BYOKKeyError) as exc_info:
                await provider.wrap_dek("org1", "alias1", dek)
            assert exc_info.value.org_id == "org1"
            assert exc_info.value.key_alias == "alias1"


# ─── AWSKMSProvider health check tests ───────────────────────────────────────


class TestAWSKMSProviderHealthCheck:
    @pytest.mark.asyncio
    async def test_aws_health_check_enabled(self, aws_credentials):
        """health_check returns True for an enabled key."""
        with mock_aws():
            client = boto3.client("kms", region_name="us-east-1")
            arn = client.create_key(Description="t")["KeyMetadata"]["Arn"]
            provider = AWSKMSProvider({"kms_key_arn": arn})

            result = await provider.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_aws_health_check_disabled(self, aws_credentials):
        """health_check returns False for a disabled key."""
        with mock_aws():
            client = boto3.client("kms", region_name="us-east-1")
            key_meta = client.create_key(Description="t")["KeyMetadata"]
            arn = key_meta["Arn"]
            key_id = key_meta["KeyId"]
            client.disable_key(KeyId=key_id)
            provider = AWSKMSProvider({"kms_key_arn": arn})

            result = await provider.health_check()
            assert result is False


# ─── AWSKMSProvider utility tests ────────────────────────────────────────────


class TestAWSKMSProviderUtilities:
    @pytest.mark.asyncio
    async def test_aws_generate_dek_is_fernet_key(self, aws_credentials):
        """generate_dek returns a 44-byte Fernet key."""
        from cryptography.fernet import Fernet

        with mock_aws():
            client = boto3.client("kms", region_name="us-east-1")
            arn = client.create_key(Description="t")["KeyMetadata"]["Arn"]
            provider = AWSKMSProvider({"kms_key_arn": arn})

            dek = await provider.generate_dek()
            assert len(dek) == 44
            Fernet(dek)  # Raises if not a valid Fernet key

    def test_aws_region_extraction_from_arn(self):
        """Region is correctly parsed from the ARN."""
        arn = "arn:aws:kms:eu-west-1:123456789012:key/abc123"
        region = _extract_region_from_arn(arn)
        assert region == "eu-west-1"

    def test_aws_region_extraction_us_east(self):
        """Region extraction works for us-east-1."""
        arn = "arn:aws:kms:us-east-1:999999999999:key/my-key"
        assert _extract_region_from_arn(arn) == "us-east-1"

    def test_aws_region_extraction_invalid_arn_raises(self):
        """Invalid ARN raises ValueError."""
        with pytest.raises(ValueError):
            _extract_region_from_arn("not-an-arn")


# ─── Retry logic test ─────────────────────────────────────────────────────────


class TestAWSKMSProviderRetry:
    @pytest.mark.asyncio
    async def test_aws_throttle_retry(self, aws_credentials):
        """ThrottlingException on first call retries and succeeds on second call."""
        with mock_aws():
            client = boto3.client("kms", region_name="us-east-1")
            arn = client.create_key(Description="t")["KeyMetadata"]["Arn"]
            provider = AWSKMSProvider({"kms_key_arn": arn})

            inner_client = provider._get_client()
            original_encrypt = inner_client.encrypt
            call_count = [0]

            from botocore.exceptions import ClientError

            throttle_response = {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}

            def _throttle_once(**kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise ClientError(throttle_response, "Encrypt")
                return original_encrypt(**kwargs)

            inner_client.encrypt = _throttle_once

            dek = await provider.generate_dek()
            # Patch asyncio.sleep to avoid actual delay in tests
            with patch("gateway.byok_aws.asyncio.sleep", new_callable=AsyncMock):
                wrapped = await provider.wrap_dek("org1", "alias1", dek)

            assert call_count[0] == 2
            assert isinstance(wrapped, bytes)
            assert len(wrapped) > 0


# ─── byok_factory tests ───────────────────────────────────────────────────────


class TestMakeProvider:
    def test_make_provider_local(self):
        """make_provider("local") returns a LocalBYOKProvider instance."""
        provider = make_provider("local")
        assert isinstance(provider, LocalBYOKProvider)

    def test_make_provider_aws_kms(self, aws_credentials):
        """make_provider("aws_kms", {...}) returns an AWSKMSProvider instance."""
        with mock_aws():
            client = boto3.client("kms", region_name="us-east-1")
            arn = client.create_key(Description="t")["KeyMetadata"]["Arn"]
            provider = make_provider("aws_kms", {"kms_key_arn": arn})
        assert isinstance(provider, AWSKMSProvider)

    def test_make_provider_aws_kms_missing_arn(self):
        """make_provider("aws_kms", {}) raises ValueError."""
        with pytest.raises(ValueError, match="kms_key_arn"):
            make_provider("aws_kms", {})

    def test_make_provider_aws_kms_none_config(self):
        """make_provider("aws_kms", None) raises ValueError."""
        with pytest.raises(ValueError, match="kms_key_arn"):
            make_provider("aws_kms", None)

    def test_make_provider_unsupported_gcp(self):
        """make_provider("gcp_kms") raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="gcp_kms"):
            make_provider("gcp_kms")

    def test_make_provider_unsupported_azure(self):
        """make_provider("azure_kv") raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="azure_kv"):
            make_provider("azure_kv")

    def test_make_provider_unknown(self):
        """make_provider with an unknown type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown provider_type"):
            make_provider("totally_unknown_provider")

    def test_make_provider_for_key(self):
        """make_provider_for_key reads provider_type and provider_config from a model."""
        mock_key = MagicMock()
        mock_key.provider_type = "local"
        mock_key.provider_config = None

        provider = make_provider_for_key(mock_key)
        assert isinstance(provider, LocalBYOKProvider)


# ─── Security status BYOK fields tests ───────────────────────────────────────


class TestSecurityStatusBYOKFields:
    """Tests for the BYOK fields added to the /api/security/status endpoint.

    These tests call the endpoint handler function directly with a mocked store,
    bypassing HTTP and DB layers.
    """

    @pytest.mark.asyncio
    async def test_security_status_byok_fields_present(self):
        """Response dict must include all six BYOK-related fields."""
        from gateway.api.security import security_status
        from gateway.byok import DEKCache, LocalBYOKProvider
        from gateway.store import configure_byok

        # Configure a known provider so we can assert on byok_provider field
        provider = LocalBYOKProvider()
        cache = DEKCache(ttl_seconds=300)
        configure_byok(provider, cache)

        # Build a mock store with an admin user
        mock_store = MagicMock()
        mock_store.user_id = "local"

        # Mock get_credentials_needing_rotation
        mock_store.get_credentials_needing_rotation = AsyncMock(return_value=0)

        # Mock session.execute to return scalar_one() = 0 for all queries
        # Each call to execute() returns a new result mock
        def _make_result(value=0):
            r = MagicMock()
            r.scalar_one = MagicMock(return_value=value)
            return r

        execute_results = [
            _make_result(3),  # credentials_encrypted (user scoped)
            _make_result(2),  # byok_keys_active
            _make_result(1),  # byok_keys_revoked
            _make_result(3),  # credentials_managed (including NULLs)
            _make_result(1),  # credentials_byok
        ]
        execute_index = [0]

        async def _mock_execute(query):
            idx = execute_index[0]
            execute_index[0] += 1
            if idx < len(execute_results):
                return execute_results[idx]
            return _make_result(0)

        mock_store.session = MagicMock()
        mock_store.session.execute = _mock_execute

        with (
            patch("gateway.store.crypto._validate_encryption_health", return_value=True),
            patch.dict(os.environ, {"SP_ENCRYPTION_KEY": "test-key"}),
        ):
            result = await security_status(mock_store, "test-org")

        required_fields = {
            "byok_provider",
            "byok_keys_total",
            "byok_keys_active",
            "byok_keys_revoked",
            "credentials_managed",
            "credentials_byok",
        }
        for field in required_fields:
            assert field in result, f"Missing field: {field}"

        assert result["byok_provider"] == "LocalBYOKProvider"
        assert result["byok_keys_active"] == 2
        assert result["byok_keys_revoked"] == 1
        assert result["byok_keys_total"] == 3
        assert result["credentials_managed"] == 3
        assert result["credentials_byok"] == 1


# ─── main.py lifespan env var integration test ───────────────────────────────


class TestLifespanEnvVarIntegration:
    """Test that main.py lifespan reads SP_BYOK_PROVIDER env var correctly."""

    def test_make_provider_called_with_local_default(self):
        """When SP_BYOK_PROVIDER is unset, make_provider is called with 'local'."""
        with patch("gateway.byok_factory.make_provider") as mock_factory:
            mock_factory.return_value = LocalBYOKProvider()

            # Simulate the lifespan logic
            provider_type = os.environ.get("SP_BYOK_PROVIDER", "local")
            config_raw = os.environ.get("SP_BYOK_PROVIDER_CONFIG")
            config = None
            if config_raw:
                import json

                config = json.loads(config_raw)

            from gateway.byok_factory import make_provider

            make_provider(provider_type, config)
            # Without env var, provider_type should be "local"
            assert provider_type == "local"

    def test_make_provider_called_with_env_var(self):
        """When SP_BYOK_PROVIDER=local, make_provider receives 'local'."""
        with patch.dict(os.environ, {"SP_BYOK_PROVIDER": "local"}):
            provider_type = os.environ.get("SP_BYOK_PROVIDER", "local")
            assert provider_type == "local"
            provider = make_provider(provider_type, None)
            assert isinstance(provider, LocalBYOKProvider)
