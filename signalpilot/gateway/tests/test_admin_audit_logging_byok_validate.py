"""Tests for F-22 (H-1): failed and successful BYOK validation attempts are audited.

Continues ``test_admin_audit_logging.py``; uses the same mock Store so no live
database is required.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.models import AuditEntry

from ._admin_audit_helpers import _assert_no_credential_material, _make_request, _make_store


class TestBYOKAudit:
    """Verify byok_key_validate writes an audit row for every outcome."""

    @pytest.mark.asyncio
    async def test_byok_validate_invalid_key_writes_audit_with_validation_failed(self):
        """BYOKKeyError during validation must produce an audit row with validation_failed."""
        from gateway.api.byok import validate_byok_key
        from gateway.byok import BYOKKeyError

        store = _make_store()
        request = _make_request()
        key_id = str(uuid.uuid4())

        key_mock = MagicMock()
        key_mock.id = key_id
        key_mock.org_id = "test-org"
        key_mock.key_alias = "my-key"
        key_mock.provider_type = "aws_kms"
        key_mock.provider_config = {"kms_key_arn": "arn:aws:kms:us-east-1:123456789012:key/test"}

        db = AsyncMock()
        key_result = MagicMock()
        key_result.scalar_one_or_none.return_value = key_mock
        db.execute = AsyncMock(return_value=key_result)

        import gateway.store.byok_state as byok_state

        original_provider = byok_state._byok_provider
        byok_state._byok_provider = MagicMock()

        try:
            with patch(
                "gateway.api.byok.decrypt_envelope",
                new_callable=AsyncMock,
                side_effect=BYOKKeyError("test-org", "my-key", "access denied"),
            ):
                with patch("gateway.api.byok.encrypt_envelope", new_callable=AsyncMock) as mock_enc:
                    mock_enc.return_value = (b"cipher", b"wrapped")
                    result = await validate_byok_key(
                        key_id=key_id,
                        db=db,
                        _user_id="test-user",
                        org_id="test-org",
                        _role=None,
                        store=store,
                        request=request,
                    )
        finally:
            byok_state._byok_provider = original_provider

        assert result["valid"] is False
        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.event_type == "byok_key_validate"
        assert entry.metadata["result"] == "error"
        assert entry.metadata["reason"] == "validation_failed"
        assert "key_alias" in entry.metadata
        assert entry.metadata["key_alias"] == "my-key"

    @pytest.mark.asyncio
    async def test_byok_validate_internal_error_writes_audit_with_validation_failed(self):
        """RuntimeError during validation must produce audit with validation_failed; exception msg excluded."""
        from gateway.api.byok import validate_byok_key

        store = _make_store()
        request = _make_request()
        key_id = str(uuid.uuid4())

        key_mock = MagicMock()
        key_mock.id = key_id
        key_mock.org_id = "test-org"
        key_mock.key_alias = "my-key"
        key_mock.provider_type = "aws_kms"
        key_mock.provider_config = {"kms_key_arn": "arn:aws:kms:us-east-1:123456789012:key/test"}

        db = AsyncMock()
        key_result = MagicMock()
        key_result.scalar_one_or_none.return_value = key_mock
        db.execute = AsyncMock(return_value=key_result)

        import gateway.store.byok_state as byok_state

        original_provider = byok_state._byok_provider
        byok_state._byok_provider = MagicMock()

        try:
            with patch(
                "gateway.api.byok.encrypt_envelope",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ):
                result = await validate_byok_key(
                    key_id=key_id,
                    db=db,
                    _user_id="test-user",
                    org_id="test-org",
                    _role=None,
                    store=store,
                    request=request,
                )
        finally:
            byok_state._byok_provider = original_provider

        assert result["valid"] is False
        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.metadata["reason"] == "validation_failed"
        # Exception message must not appear in audit metadata
        assert "boom" not in str(entry.metadata)

    @pytest.mark.asyncio
    async def test_byok_validate_provider_unconfigured_writes_audit(self):
        """When provider is None (503), audit row must be written before raising."""
        from fastapi import HTTPException

        from gateway.api.byok import validate_byok_key

        store = _make_store()
        request = _make_request()
        key_id = str(uuid.uuid4())

        db = AsyncMock()

        import gateway.store.byok_state as byok_state

        original_provider = byok_state._byok_provider
        byok_state._byok_provider = None

        try:
            with pytest.raises(HTTPException) as exc_info:
                await validate_byok_key(
                    key_id=key_id,
                    db=db,
                    _user_id="test-user",
                    org_id="test-org",
                    _role=None,
                    store=store,
                    request=request,
                )
        finally:
            byok_state._byok_provider = original_provider

        assert exc_info.value.status_code == 503
        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.metadata["result"] == "error"
        assert entry.metadata["reason"] == "provider_not_found"
        assert entry.metadata["provider_type"] == "unknown"
        assert "key_alias" not in entry.metadata

    @pytest.mark.asyncio
    async def test_validate_byok_key_unknown_id_emits_audit_row(self):
        """POST to unknown key_id must 404 AND emit one audit row with key_not_found reason."""
        from fastapi import HTTPException

        from gateway.api.byok import validate_byok_key

        store = _make_store()
        request = _make_request()
        key_id = str(uuid.uuid4())

        db = AsyncMock()
        key_result = MagicMock()
        key_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=key_result)

        import gateway.store.byok_state as byok_state

        original_provider = byok_state._byok_provider
        byok_state._byok_provider = MagicMock()

        try:
            with pytest.raises(HTTPException) as exc_info:
                await validate_byok_key(
                    key_id=key_id,
                    db=db,
                    _user_id="test-user",
                    org_id="test-org",
                    _role=None,
                    store=store,
                    request=request,
                )
        finally:
            byok_state._byok_provider = original_provider

        assert exc_info.value.status_code == 404
        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.event_type == "byok_key_validate"
        assert entry.metadata["result"] == "error"
        assert entry.metadata["reason"] == "key_not_found"
        assert entry.metadata["provider_type"] == "unknown"
        assert entry.metadata["key_id"] == key_id
        assert "key_alias" not in entry.metadata

    @pytest.mark.asyncio
    async def test_byok_validate_success_writes_audit_with_success(self):
        """Happy-path validation must produce audit row with result=success."""
        from gateway.api.byok import BYOK_HEALTH_CHECK_PLAINTEXT, validate_byok_key

        store = _make_store()
        request = _make_request()
        key_id = str(uuid.uuid4())

        key_mock = MagicMock()
        key_mock.id = key_id
        key_mock.org_id = "test-org"
        key_mock.key_alias = "my-key"
        key_mock.provider_type = "local"
        key_mock.provider_config = None

        db = AsyncMock()
        key_result = MagicMock()
        key_result.scalar_one_or_none.return_value = key_mock
        db.execute = AsyncMock(return_value=key_result)

        import gateway.store.byok_state as byok_state

        original_provider = byok_state._byok_provider
        byok_state._byok_provider = MagicMock()

        try:
            with patch("gateway.api.byok.encrypt_envelope", new_callable=AsyncMock) as mock_enc:
                mock_enc.return_value = (b"cipher", b"wrapped")
                with patch("gateway.api.byok.decrypt_envelope", new_callable=AsyncMock) as mock_dec:
                    mock_dec.return_value = BYOK_HEALTH_CHECK_PLAINTEXT
                    result = await validate_byok_key(
                        key_id=key_id,
                        db=db,
                        _user_id="test-user",
                        org_id="test-org",
                        _role=None,
                        store=store,
                        request=request,
                    )
        finally:
            byok_state._byok_provider = original_provider

        assert result["valid"] is True
        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.metadata["result"] == "success"
        assert entry.metadata["reason"] == "success"


# ─── API key audit tests ──────────────────────────────────────────────────────
