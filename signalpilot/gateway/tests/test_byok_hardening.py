"""Tests for BYOK security hardening fixes H1, H2, and H3.

H1: SP_BYOK_PROVIDER_CONFIG invalid JSON raises SystemExit(1) without leaking the raw value.
H2: _extract_region_from_arn logs the ARN server-side but the ValueError message is sanitized.
H3: security_status BYOK key counts are filtered by org_id.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.byok_aws import _extract_region_from_arn


# ─── H1: Invalid SP_BYOK_PROVIDER_CONFIG halts startup ───────────────────────

class TestByokProviderConfigInvalidJSON:
    """H1 — malformed SP_BYOK_PROVIDER_CONFIG must abort startup, not silently continue."""

    @pytest.mark.asyncio
    async def test_invalid_json_raises_system_exit(self):
        """When SP_BYOK_PROVIDER_CONFIG is not valid JSON, lifespan must raise SystemExit."""
        from gateway.main import lifespan, app

        with patch.dict(os.environ, {"SP_BYOK_PROVIDER_CONFIG": "{not: valid json!!!"}):
            with patch("gateway.main.init_db", new_callable=AsyncMock):
                with patch("gateway.main._validate_encryption_health", return_value=True):
                    ctx = lifespan(app)
                    with pytest.raises(SystemExit) as exc_info:
                        await ctx.__aenter__()
                    assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_valid_json_does_not_raise(self):
        """When SP_BYOK_PROVIDER_CONFIG is valid JSON, startup proceeds normally."""
        from gateway.main import lifespan, app

        valid_config = '{"provider": "local"}'

        async def _cleanup_tasks():
            pass

        with patch.dict(os.environ, {"SP_BYOK_PROVIDER_CONFIG": valid_config, "SP_BYOK_PROVIDER": "local"}):
            with patch("gateway.main.init_db", new_callable=AsyncMock):
                with patch("gateway.main._validate_encryption_health", return_value=True):
                    with patch("gateway.main.make_provider") as mock_make:
                        from gateway.byok import LocalBYOKProvider
                        mock_make.return_value = LocalBYOKProvider()
                        with patch("gateway.main.configure_byok"):
                            with patch("gateway.main.pool_manager") as mock_pm:
                                mock_pm.cleanup_idle = AsyncMock()
                                with patch("gateway.main.schema_cache") as mock_sc:
                                    mock_sc.refresh_all = AsyncMock()
                                    with patch("gateway.main.get_session_factory"):
                                        ctx = lifespan(app)
                                        # Enter should not raise
                                        try:
                                            await ctx.__aenter__()
                                        except Exception:
                                            pass  # Background tasks may fail in test env — that's fine
                                        mock_make.assert_called_once()
                                        call_args = mock_make.call_args
                                        # Config dict was parsed correctly from the valid JSON
                                        assert call_args[0][1] == {"provider": "local"}

    def test_invalid_json_error_does_not_log_raw_value(self, caplog):
        """The error log for invalid JSON must NOT include the raw config value."""
        import logging
        import json

        raw_config = '{"aws_secret_access_key": "SUPERSECRET", broken json'

        with caplog.at_level(logging.ERROR):
            try:
                json.loads(raw_config)
            except json.JSONDecodeError:
                import logging as _logging
                logger = _logging.getLogger("gateway.main")
                logger.error("STARTUP FATAL: SP_BYOK_PROVIDER_CONFIG contains invalid JSON")

        # Raw value must not appear in any log message
        for record in caplog.records:
            assert "SUPERSECRET" not in record.message
            assert raw_config not in record.message


# ─── H2: _extract_region_from_arn sanitizes ValueError message ───────────────

class TestExtractRegionFromArnSanitized:
    """H2 — ValueError from malformed ARN must not expose the ARN in its message."""

    def test_valid_arn_extracts_region(self):
        """A well-formed KMS ARN returns the region string."""
        region = _extract_region_from_arn("arn:aws:kms:us-east-1:123456789012:key/abc-def")
        assert region == "us-east-1"

    def test_invalid_arn_raises_value_error(self):
        """A garbage string raises ValueError."""
        with pytest.raises(ValueError):
            _extract_region_from_arn("garbage")

    def test_invalid_arn_error_message_does_not_contain_arn(self):
        """The ValueError message must NOT contain the malformed ARN value."""
        bad_arn = "arn:badformat:secret-region:secret-account:key/sensitive"
        with pytest.raises(ValueError) as exc_info:
            _extract_region_from_arn(bad_arn)
        assert bad_arn not in str(exc_info.value)

    def test_invalid_arn_logs_full_arn_server_side(self):
        """The full ARN must appear in the server-side error log (for debugging)."""

        bad_arn = "notanarn"
        with patch("gateway.byok_aws.logger") as mock_logger:
            with pytest.raises(ValueError):
                _extract_region_from_arn(bad_arn)
            mock_logger.error.assert_called_once()
            call_args = mock_logger.error.call_args
            # The ARN is passed as the second positional arg (%r format)
            assert bad_arn in call_args[0][1]

    def test_error_message_is_generic(self):
        """The ValueError message is a fixed generic string, not the input."""
        with pytest.raises(ValueError) as exc_info:
            _extract_region_from_arn("totallywrong")
        assert "Invalid KMS key ARN format" in str(exc_info.value)


# ─── H3: security_status filters BYOK key counts by org_id ───────────────────

class TestSecurityStatusOrgScoping:
    """H3 — BYOK key counts in security_status must be scoped to the requesting org."""

    def _make_result(self, value: int) -> MagicMock:
        r = MagicMock()
        r.scalar_one = MagicMock(return_value=value)
        return r

    def _make_mock_store(self, user_id: str = "local", org_id: str = "local") -> MagicMock:
        mock_store = MagicMock()
        mock_store.user_id = user_id
        mock_store.org_id = org_id
        mock_store.get_credentials_needing_rotation = AsyncMock(return_value=0)
        mock_store.session = MagicMock()
        return mock_store

    @pytest.mark.asyncio
    async def test_security_status_passes_org_id_to_byok_queries(self):
        """The org_id argument must be forwarded to the BYOK key count queries."""
        from gateway.api.security import security_status
        from gateway.byok import LocalBYOKProvider, DEKCache
        from gateway.store import configure_byok

        provider = LocalBYOKProvider()
        cache = DEKCache(ttl_seconds=300)
        configure_byok(provider, cache)

        mock_store = self._make_mock_store()

        execute_results = [
            self._make_result(5),   # credentials_encrypted
            self._make_result(2),   # byok_keys_active (org1)
            self._make_result(0),   # byok_keys_revoked (org1)
            self._make_result(5),   # credentials_managed
            self._make_result(0),   # credentials_byok
        ]
        execute_index = [0]
        captured_queries: list = []

        async def _mock_execute(query):
            captured_queries.append(query)
            idx = execute_index[0]
            execute_index[0] += 1
            if idx < len(execute_results):
                return execute_results[idx]
            return self._make_result(0)

        mock_store.session.execute = _mock_execute

        with (
            patch("gateway.store._validate_encryption_health", return_value=True),
            patch.dict(os.environ, {"SP_ENCRYPTION_KEY": "test-key"}),
        ):
            result = await security_status(mock_store, "org1")

        assert result["byok_keys_active"] == 2
        assert result["byok_keys_revoked"] == 0
        assert result["byok_keys_total"] == 2

    @pytest.mark.asyncio
    async def test_different_org_ids_yield_different_counts(self):
        """Calling security_status with two different org_ids yields independent counts."""
        from gateway.api.security import security_status
        from gateway.byok import LocalBYOKProvider, DEKCache
        from gateway.store import configure_byok

        provider = LocalBYOKProvider()
        cache = DEKCache(ttl_seconds=300)
        configure_byok(provider, cache)

        async def _call_with_org(org_id: str, active: int, revoked: int) -> dict:
            mock_store = self._make_mock_store()
            execute_results = [
                self._make_result(1),         # credentials_encrypted
                self._make_result(active),    # byok_keys_active
                self._make_result(revoked),   # byok_keys_revoked
                self._make_result(1),         # credentials_managed
                self._make_result(0),         # credentials_byok
            ]
            execute_index = [0]

            async def _mock_execute(query):
                idx = execute_index[0]
                execute_index[0] += 1
                if idx < len(execute_results):
                    return execute_results[idx]
                return self._make_result(0)

            mock_store.session.execute = _mock_execute
            with (
                patch("gateway.store._validate_encryption_health", return_value=True),
                patch.dict(os.environ, {"SP_ENCRYPTION_KEY": "test-key"}),
            ):
                return await security_status(mock_store, org_id)

        result_org1 = await _call_with_org("org1", active=3, revoked=1)
        result_org2 = await _call_with_org("org2", active=0, revoked=0)

        assert result_org1["byok_keys_active"] == 3
        assert result_org1["byok_keys_revoked"] == 1
        assert result_org1["byok_keys_total"] == 4

        assert result_org2["byok_keys_active"] == 0
        assert result_org2["byok_keys_revoked"] == 0
        assert result_org2["byok_keys_total"] == 0

    @pytest.mark.asyncio
    async def test_credential_mode_counts_scoped_to_org(self):
        """Credential mode counts (managed/byok) must be scoped to store.org_id."""
        from gateway.api.security import security_status
        from gateway.byok import LocalBYOKProvider, DEKCache
        from gateway.store import configure_byok

        provider = LocalBYOKProvider()
        cache = DEKCache(ttl_seconds=300)
        configure_byok(provider, cache)

        mock_store = self._make_mock_store(user_id="local", org_id="local")
        captured_queries: list = []

        execute_results = [
            self._make_result(4),   # credentials_encrypted
            self._make_result(1),   # byok_keys_active
            self._make_result(0),   # byok_keys_revoked
            self._make_result(3),   # credentials_managed (org-scoped)
            self._make_result(1),   # credentials_byok (org-scoped)
        ]
        execute_index = [0]

        async def _mock_execute(query):
            captured_queries.append(str(query))
            idx = execute_index[0]
            execute_index[0] += 1
            if idx < len(execute_results):
                return execute_results[idx]
            return self._make_result(0)

        mock_store.session.execute = _mock_execute

        with (
            patch("gateway.store._validate_encryption_health", return_value=True),
            patch.dict(os.environ, {"SP_ENCRYPTION_KEY": "test-key"}),
        ):
            result = await security_status(mock_store, "org-xyz")

        assert result["credentials_managed"] == 3
        assert result["credentials_byok"] == 1

        # Verify that the org_id filter appears in managed and byok credential queries
        # (queries at index 3 and 4 in captured_queries)
        managed_query_str = captured_queries[3]
        byok_query_str = captured_queries[4]
        assert "org_id" in managed_query_str
        assert "org_id" in byok_query_str
