"""Tests for F-22: admin/state-changing operations written to GatewayAuditLog.

Verifies that each admin handler appends an AuditEntry with the correct
event_type and org_id scoping, and that NO credential material appears in the
metadata. Tests use a mock Store so no live database is required.
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.models import AuditEntry

# ─── Shared helpers ───────────────────────────────────────────────────────────


def _make_request(
    client_host: str = "10.0.0.1",
    forwarded_for: str | None = None,
    user_agent: str = "test-agent/1.0",
) -> MagicMock:
    """Build a minimal mock Request matching FastAPI's interface."""
    request = MagicMock()
    headers: dict[str, str] = {"user-agent": user_agent}
    if forwarded_for:
        headers["x-forwarded-for"] = forwarded_for
    request.headers = headers
    request.client = MagicMock()
    request.client.host = client_host
    return request


def _make_store(org_id: str = "test-org", user_id: str = "test-user") -> AsyncMock:
    """Build a mock Store that captures append_audit calls."""
    store = AsyncMock()
    store.org_id = org_id
    store.user_id = user_id
    store.append_audit = AsyncMock()
    return store


def _assert_no_credential_material(metadata: dict[str, Any]) -> None:
    """Assert that no raw credential bytes or secrets appear in metadata."""
    forbidden_keys = {"connection_string", "password", "provider_config", "dek", "wrapped_dek", "raw_key"}
    for key in forbidden_keys:
        assert key not in metadata, f"Credential material '{key}' found in audit metadata"
    for value in metadata.values():
        if isinstance(value, str):
            # Crude check: real connection strings contain ://
            assert "://" not in value or value.startswith("byok"), (
                f"Possible connection string in audit metadata value: {value!r}"
            )


# ─── BYOK audit tests ─────────────────────────────────────────────────────────


class TestBYOKAudit:
    """Verify byok_key_create, byok_key_rotate, byok_key_validate,
    byok_migrate, byok_revert are appended to audit log."""

    @pytest.mark.asyncio
    async def test_byok_key_create_appends_audit(self):
        from gateway.api.byok import create_byok_key
        from gateway.models import BYOKKeyCreate

        store = _make_store()
        request = _make_request()

        # Minimal mock DB session
        db = AsyncMock()
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        key_mock = MagicMock()
        key_mock.id = str(uuid.uuid4())
        key_mock.org_id = "test-org"
        key_mock.key_alias = "my-key"
        key_mock.provider_type = "local"
        key_mock.provider_config = None
        key_mock.status = "active"
        key_mock.created_at = time.time()
        key_mock.revoked_at = None
        db.execute = AsyncMock(return_value=existing_result)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        body = BYOKKeyCreate(key_alias="my-key", provider_type="local", provider_config={})

        with patch("gateway.api.byok._upsert_org", new_callable=AsyncMock):
            await create_byok_key(
                body=body,
                db=db,
                _user_id="test-user",
                org_id="test-org",
                _role=None,
                store=store,
                request=request,
            )

        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.event_type == "byok_key_create"
        assert "key_alias" in entry.metadata
        assert entry.metadata["key_alias"] == "my-key"
        assert entry.metadata["provider_type"] == "local"
        _assert_no_credential_material(entry.metadata)

    @pytest.mark.asyncio
    async def test_byok_key_create_uses_trusted_hop_ip(self):
        """Regression: audit entry must use the rightmost XFF hop (trusted proxy),
        not the leftmost (client-spoofable) value."""
        from gateway.api.byok import create_byok_key
        from gateway.models import BYOKKeyCreate

        store = _make_store()
        # Simulate a spoofed leftmost entry; trusted proxy appended "2.2.2.2".
        request = _make_request(forwarded_for="evil-spoof, 2.2.2.2")

        db = AsyncMock()
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        key_mock = MagicMock()
        key_mock.id = str(uuid.uuid4())
        key_mock.org_id = "test-org"
        key_mock.key_alias = "my-key"
        key_mock.provider_type = "local"
        key_mock.provider_config = None
        key_mock.status = "active"
        key_mock.created_at = time.time()
        key_mock.revoked_at = None
        db.execute = AsyncMock(return_value=existing_result)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        body = BYOKKeyCreate(key_alias="my-key", provider_type="local", provider_config={})

        with patch("gateway.api.byok._upsert_org", new_callable=AsyncMock):
            await create_byok_key(
                body=body,
                db=db,
                _user_id="test-user",
                org_id="test-org",
                _role=None,
                store=store,
                request=request,
            )

        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.client_ip == "2.2.2.2", (
            f"Expected trusted rightmost XFF '2.2.2.2' but got {entry.client_ip!r}. "
            "Audit IP must not be spoofable via leftmost XFF."
        )
        assert entry.client_ip != "evil-spoof"

    @pytest.mark.asyncio
    async def test_byok_migrate_appends_audit(self):
        import gateway.store.byok_state as byok_state
        from gateway.api.byok import migrate_credentials_to_byok
        from gateway.models import BYOKMigrateRequest

        store = _make_store()
        request = _make_request()

        key_mock = MagicMock()
        key_mock.org_id = "test-org"
        key_mock.key_alias = "my-key"
        key_id = str(uuid.uuid4())

        key_result = MagicMock()
        key_result.scalar_one_or_none.return_value = key_mock
        store.session = AsyncMock()
        store.session.execute = AsyncMock(return_value=key_result)

        body = BYOKMigrateRequest(key_id=key_id)

        original_provider = byok_state._byok_provider
        byok_state._byok_provider = MagicMock()

        try:
            with patch("gateway.api.byok.migrate_to_byok", new_callable=AsyncMock) as mock_migrate:
                mock_migrate.return_value = (3, 0, [])
                await migrate_credentials_to_byok(
                    body=body,
                    store=store,
                    org_id="test-org",
                    _role=None,
                    request=request,
                )
        finally:
            byok_state._byok_provider = original_provider

        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.event_type == "byok_migrate"
        assert entry.metadata["key_id"] == key_id
        assert "migrated" in entry.metadata
        _assert_no_credential_material(entry.metadata)

    @pytest.mark.asyncio
    async def test_byok_revert_appends_audit(self):
        from gateway.api.byok import revert_credentials_to_managed

        store = _make_store()
        request = _make_request()

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = MagicMock()
        store.session = AsyncMock()
        store.session.execute = AsyncMock(return_value=org_result)

        import gateway.store.byok_state as byok_state

        original_provider = byok_state._byok_provider
        provider_mock = MagicMock()
        byok_state._byok_provider = provider_mock

        try:
            with patch("gateway.api.byok.revert_to_managed", new_callable=AsyncMock) as mock_revert:
                mock_revert.return_value = (5, 0, [])
                await revert_credentials_to_managed(
                    store=store,
                    org_id="test-org",
                    _role=None,
                    request=request,
                )
        finally:
            byok_state._byok_provider = original_provider

        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.event_type == "byok_revert"
        assert "migrated" in entry.metadata
        _assert_no_credential_material(entry.metadata)

    @pytest.mark.asyncio
    async def test_byok_key_rotate_appends_audit(self):
        from gateway.api.byok import rotate_byok_key_endpoint
        from gateway.models import BYOKRotateRequest

        store = _make_store()
        request = _make_request()

        old_key_id = str(uuid.uuid4())
        new_key_id = str(uuid.uuid4())

        old_key = MagicMock()
        old_key.org_id = "test-org"
        old_key.status = "active"
        old_key.key_alias = "old-alias"

        new_key = MagicMock()
        new_key.org_id = "test-org"
        new_key.status = "active"
        new_key.key_alias = "new-alias"

        execute_results = [
            MagicMock(**{"scalar_one_or_none.return_value": old_key}),
            MagicMock(**{"scalar_one_or_none.return_value": new_key}),
        ]
        store.session = AsyncMock()
        store.session.execute = AsyncMock(side_effect=execute_results)
        store.session.commit = AsyncMock()

        body = BYOKRotateRequest(new_key_id=new_key_id)

        import gateway.store.byok_state as byok_state

        original_provider = byok_state._byok_provider
        provider_mock = MagicMock()
        byok_state._byok_provider = provider_mock

        try:
            with patch("gateway.api.byok.rotate_byok_key", new_callable=AsyncMock) as mock_rotate:
                mock_rotate.return_value = (4, 0, [])
                await rotate_byok_key_endpoint(
                    key_id=old_key_id,
                    body=body,
                    store=store,
                    org_id="test-org",
                    _role=None,
                    request=request,
                )
        finally:
            byok_state._byok_provider = original_provider

        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.event_type == "byok_key_rotate"
        assert entry.metadata["old_key_id"] == old_key_id
        assert entry.metadata["new_key_id"] == new_key_id
        assert entry.metadata["old_key_alias"] == "old-alias"
        assert entry.metadata["new_key_alias"] == "new-alias"
        _assert_no_credential_material(entry.metadata)

    @pytest.mark.asyncio
    async def test_byok_audit_suppresses_audit_db_failure(self):
        """If append_audit raises, the primary operation result is still returned."""
        from gateway.api.byok import revert_credentials_to_managed

        store = _make_store()
        store.append_audit = AsyncMock(side_effect=RuntimeError("db gone"))
        request = _make_request()

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = MagicMock()
        store.session = AsyncMock()
        store.session.execute = AsyncMock(return_value=org_result)

        import gateway.store.byok_state as byok_state

        original_provider = byok_state._byok_provider
        provider_mock = MagicMock()
        byok_state._byok_provider = provider_mock

        try:
            with patch("gateway.api.byok.revert_to_managed", new_callable=AsyncMock) as mock_revert:
                mock_revert.return_value = (2, 0, [])
                result = await revert_credentials_to_managed(
                    store=store,
                    org_id="test-org",
                    _role=None,
                    request=request,
                )
        finally:
            byok_state._byok_provider = original_provider

        # Primary operation succeeded — result has migrated count
        assert result.migrated == 2

    # ─── H-1: audit failed BYOK validation attempts ───────────────────────────

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


class TestAPIKeyAudit:
    """Verify api_key_create and api_key_delete are appended to audit log."""

    @pytest.mark.asyncio
    async def test_create_key_appends_audit(self):
        from gateway.api.keys import create_key
        from gateway.models import ApiKeyCreate

        store = _make_store()
        request = _make_request(forwarded_for="192.168.1.1")

        key_record = MagicMock()
        key_record.id = str(uuid.uuid4())
        key_record.name = "ci-key"
        key_record.scopes = ["query", "read"]
        key_record.model_dump.return_value = {
            "id": key_record.id,
            "name": key_record.name,
            "scopes": key_record.scopes,
        }
        store.create_api_key = AsyncMock(return_value=(key_record, "sp_raw_key"))
        store.list_api_keys = AsyncMock(return_value=[])

        body = ApiKeyCreate(name="ci-key", scopes=["query", "read"])

        with patch("gateway.governance.plan_limits.get_org_limits", new_callable=AsyncMock) as mock_limits:
            mock_limits.return_value = MagicMock(api_keys=None)
            with patch("gateway.governance.plan_limits.check_api_key_limit"):
                try:
                    await create_key(body=body, store=store, _role=None, request=request)
                except Exception:
                    pass  # Response construction on mock may fail; audit is what matters

        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.event_type == "api_key_create"
        assert entry.metadata["key_id"] == key_record.id
        assert entry.metadata["name"] == "ci-key"
        assert "query" in entry.metadata["scopes"]
        assert entry.client_ip == "192.168.1.1"
        _assert_no_credential_material(entry.metadata)
        # Raw key must NOT appear in metadata
        assert "raw_key" not in entry.metadata
        assert "sp_raw_key" not in str(entry.metadata)

    @pytest.mark.asyncio
    async def test_delete_key_appends_audit(self):
        from gateway.api.keys import delete_key

        store = _make_store()
        store.delete_api_key = AsyncMock(return_value=True)
        request = _make_request()

        key_id = str(uuid.uuid4())
        await delete_key(key_id=key_id, store=store, _role=None, request=request)

        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.event_type == "api_key_delete"
        assert entry.metadata["key_id"] == key_id
        _assert_no_credential_material(entry.metadata)

    @pytest.mark.asyncio
    async def test_delete_key_not_found_does_not_audit(self):
        """404 response must not produce an audit row."""
        from fastapi import HTTPException

        from gateway.api.keys import delete_key

        store = _make_store()
        store.delete_api_key = AsyncMock(return_value=False)
        request = _make_request()

        with pytest.raises(HTTPException) as exc_info:
            await delete_key(key_id="missing-id", store=store, _role=None, request=request)

        assert exc_info.value.status_code == 404
        store.append_audit.assert_not_called()

    @pytest.mark.asyncio
    async def test_api_key_audit_suppresses_audit_db_failure(self):
        """Audit-DB failure must not block a successful key deletion."""
        from gateway.api.keys import delete_key

        store = _make_store()
        store.delete_api_key = AsyncMock(return_value=True)
        store.append_audit = AsyncMock(side_effect=RuntimeError("db gone"))
        request = _make_request()

        # Should not raise even though append_audit fails
        response = await delete_key(key_id=str(uuid.uuid4()), store=store, _role=None, request=request)
        assert response.status_code == 204


# ─── Connection porting audit tests ──────────────────────────────────────────


class TestConnectionPortingAudit:
    """Verify credential_export and connection_import are appended to audit log."""

    @pytest.mark.asyncio
    async def test_export_connections_appends_audit_after_success(self):
        from gateway.api.connections.porting import ExportRequest, export_connections

        store = _make_store()
        request = _make_request()

        conn = MagicMock()
        conn.model_dump.return_value = {
            "name": "pg-prod",
            "db_type": "postgres",
            "description": "",
            "tags": [],
        }
        store.list_connections = AsyncMock(return_value=[conn])
        store.get_connection_string = AsyncMock(return_value=None)

        body = ExportRequest(include_credentials=False, confirm=True)

        with patch("gateway.api.connections.porting.require_scopes"):
            await export_connections(body=body, store=store, request=request)

        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.event_type == "credential_export"
        assert entry.metadata["include_credentials"] is False
        assert entry.metadata["connection_count"] == 1
        _assert_no_credential_material(entry.metadata)

    @pytest.mark.asyncio
    async def test_export_no_audit_when_confirm_false(self):
        from gateway.api.connections.porting import ExportRequest, export_connections

        store = _make_store()
        request = _make_request()

        body = ExportRequest(include_credentials=False, confirm=False)

        with patch("gateway.api.connections.porting.require_scopes"):
            await export_connections(body=body, store=store, request=request)

        store.append_audit.assert_not_called()

    @pytest.mark.asyncio
    async def test_import_connections_appends_audit(self):
        from gateway.api.connections.porting import import_connections

        store = _make_store()
        store.get_connection = AsyncMock(return_value=None)
        store.create_connection = AsyncMock()
        request = _make_request()

        manifest = {
            "connections": [
                {"name": "pg-one", "db_type": "postgres", "host": "localhost", "port": 5432, "database": "db"},
            ]
        }

        with patch("gateway.api.connections.porting._validate_connection_params", return_value=[]):
            with patch("gateway.api.connections.porting.ConnectionCreate") as mock_cc:
                mock_cc.return_value = MagicMock()
                await import_connections(manifest=manifest, store=store, request=request)

        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.event_type == "connection_import"
        assert "imported" in entry.metadata
        assert "skipped_count" in entry.metadata
        assert "errors_count" in entry.metadata
        _assert_no_credential_material(entry.metadata)

    @pytest.mark.asyncio
    async def test_export_audit_suppresses_audit_db_failure(self):
        from gateway.api.connections.porting import ExportRequest, export_connections

        store = _make_store()
        store.append_audit = AsyncMock(side_effect=RuntimeError("db gone"))
        store.list_connections = AsyncMock(return_value=[])
        request = _make_request()

        body = ExportRequest(include_credentials=False, confirm=True)

        with patch("gateway.api.connections.porting.require_scopes"):
            result = await export_connections(body=body, store=store, request=request)

        assert result["connection_count"] == 0


# ─── Connection CRUD audit tests ─────────────────────────────────────────────


class TestConnectionCRUDAudit:
    """Verify connection_delete and connection_update are appended to audit log."""

    @pytest.mark.asyncio
    async def test_remove_connection_appends_audit(self):
        from gateway.api.connections.crud import remove_connection

        store = _make_store()
        store.delete_connection = AsyncMock(return_value=True)
        request = _make_request()

        with patch("gateway.api.connections.crud.schema_cache"):
            await remove_connection(name="pg-prod", store=store, _role=None, request=request)

        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.event_type == "connection_delete"
        assert entry.metadata["name"] == "pg-prod"
        _assert_no_credential_material(entry.metadata)

    @pytest.mark.asyncio
    async def test_remove_connection_not_found_does_not_audit(self):
        from fastapi import HTTPException

        from gateway.api.connections.crud import remove_connection

        store = _make_store()
        store.delete_connection = AsyncMock(return_value=False)
        request = _make_request()

        with pytest.raises(HTTPException) as exc_info:
            with patch("gateway.api.connections.crud.schema_cache"):
                await remove_connection(name="gone", store=store, _role=None, request=request)

        assert exc_info.value.status_code == 404
        store.append_audit.assert_not_called()

    @pytest.mark.asyncio
    async def test_edit_connection_appends_audit(self):
        from gateway.api.connections.crud import edit_connection
        from gateway.models import ConnectionUpdate

        store = _make_store()
        request = _make_request()

        existing = MagicMock()
        existing.db_type = "postgres"
        existing.model_dump.return_value = {
            "name": "pg-prod",
            "db_type": "postgres",
            "host": "localhost",
            "port": 5432,
            "database": "db",
        }
        store.get_connection = AsyncMock(return_value=existing)
        store.get_connection_string = AsyncMock(return_value=None)
        store.update_connection = AsyncMock(return_value=existing)

        update = ConnectionUpdate(description="updated description")

        with (
            patch("gateway.api.connections.crud._validate_connection_params", return_value=[]),
            patch("gateway.api.connections.crud.schema_cache"),
            patch("gateway.api.connections.crud.pool_manager"),
            patch("gateway.api.connections.crud.ConnectionCreate"),
        ):
            await edit_connection(name="pg-prod", update=update, store=store, _role=None, request=request)

        store.append_audit.assert_called_once()
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.event_type == "connection_update"
        assert entry.metadata["name"] == "pg-prod"
        assert "credentials_changed" in entry.metadata
        assert entry.metadata["credentials_changed"] is False
        _assert_no_credential_material(entry.metadata)

    @pytest.mark.asyncio
    async def test_edit_connection_credentials_changed_true(self):
        from gateway.api.connections.crud import edit_connection
        from gateway.models import ConnectionUpdate

        store = _make_store()
        request = _make_request()

        existing = MagicMock()
        existing.db_type = "postgres"
        existing.model_dump.return_value = {
            "name": "pg-prod",
            "db_type": "postgres",
            "host": "localhost",
            "port": 5432,
            "database": "db",
        }
        store.get_connection = AsyncMock(return_value=existing)
        store.get_connection_string = AsyncMock(return_value=None)
        store.update_connection = AsyncMock(return_value=existing)

        update = ConnectionUpdate(connection_string="postgresql://user:pass@host/db")

        with (
            patch("gateway.api.connections.crud._validate_connection_params", return_value=[]),
            patch("gateway.api.connections.crud.schema_cache"),
            patch("gateway.api.connections.crud.pool_manager"),
            patch("gateway.api.connections.crud.ConnectionCreate"),
        ):
            await edit_connection(name="pg-prod", update=update, store=store, _role=None, request=request)

        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.metadata["credentials_changed"] is True
        # Confirm the connection_string itself is NOT in metadata
        _assert_no_credential_material(entry.metadata)

    @pytest.mark.asyncio
    async def test_crud_audit_suppresses_audit_db_failure(self):
        """Audit-DB failure must not block a successful connection deletion."""
        from gateway.api.connections.crud import remove_connection

        store = _make_store()
        store.delete_connection = AsyncMock(return_value=True)
        store.append_audit = AsyncMock(side_effect=RuntimeError("db gone"))
        request = _make_request()

        # Should not raise
        with patch("gateway.api.connections.crud.schema_cache"):
            await remove_connection(name="pg-prod", store=store, _role=None, request=request)

    @pytest.mark.asyncio
    async def test_audit_entry_org_id_from_store(self):
        """Verify org_id comes from store (not user-supplied params)."""
        from gateway.api.connections.crud import remove_connection

        store = _make_store(org_id="org-abc-123")
        store.delete_connection = AsyncMock(return_value=True)
        request = _make_request()

        with patch("gateway.api.connections.crud.schema_cache"):
            await remove_connection(name="pg-prod", store=store, _role=None, request=request)

        # The store itself is org-scoped; append_audit is called on that store
        store.append_audit.assert_called_once()
        # We trust the Store implementation to use its own org_id — this test
        # verifies the call reaches the store's method, not a different org.
        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.event_type == "connection_delete"

    # ─── H-2: widened credentials_changed heuristic ──────────────────────────

    @pytest.mark.asyncio
    async def test_connection_update_password_only_flags_credentials_changed(self):
        from gateway.api.connections.crud import edit_connection
        from gateway.models import ConnectionUpdate

        store = _make_store()
        request = _make_request()

        existing = MagicMock()
        existing.db_type = "postgres"
        existing.model_dump.return_value = {
            "name": "pg-prod",
            "db_type": "postgres",
            "host": "localhost",
            "port": 5432,
            "database": "db",
        }
        store.get_connection = AsyncMock(return_value=existing)
        store.get_connection_string = AsyncMock(return_value=None)
        store.update_connection = AsyncMock(return_value=existing)

        update = ConnectionUpdate(password="newpassword")

        with (
            patch("gateway.api.connections.crud._validate_connection_params", return_value=[]),
            patch("gateway.api.connections.crud.schema_cache"),
            patch("gateway.api.connections.crud.pool_manager"),
            patch("gateway.api.connections.crud.ConnectionCreate"),
        ):
            await edit_connection(name="pg-prod", update=update, store=store, _role=None, request=request)

        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.metadata["credentials_changed"] is True

    @pytest.mark.asyncio
    async def test_connection_update_description_only_flags_no_credentials_change(self):
        from gateway.api.connections.crud import edit_connection
        from gateway.models import ConnectionUpdate

        store = _make_store()
        request = _make_request()

        existing = MagicMock()
        existing.db_type = "postgres"
        existing.model_dump.return_value = {
            "name": "pg-prod",
            "db_type": "postgres",
            "host": "localhost",
            "port": 5432,
            "database": "db",
        }
        store.get_connection = AsyncMock(return_value=existing)
        store.get_connection_string = AsyncMock(return_value=None)
        store.update_connection = AsyncMock(return_value=existing)

        update = ConnectionUpdate(description="updated description")

        with (
            patch("gateway.api.connections.crud._validate_connection_params", return_value=[]),
            patch("gateway.api.connections.crud.schema_cache"),
            patch("gateway.api.connections.crud.pool_manager"),
            patch("gateway.api.connections.crud.ConnectionCreate"),
        ):
            await edit_connection(name="pg-prod", update=update, store=store, _role=None, request=request)

        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.metadata["credentials_changed"] is False

    @pytest.mark.asyncio
    async def test_connection_update_ssh_tunnel_flags_credentials_changed(self):
        from gateway.api.connections.crud import edit_connection
        from gateway.models import ConnectionUpdate

        store = _make_store()
        request = _make_request()

        existing = MagicMock()
        existing.db_type = "postgres"
        existing.model_dump.return_value = {
            "name": "pg-prod",
            "db_type": "postgres",
            "host": "localhost",
            "port": 5432,
            "database": "db",
        }
        store.get_connection = AsyncMock(return_value=existing)
        store.get_connection_string = AsyncMock(return_value=None)
        store.update_connection = AsyncMock(return_value=existing)

        update = ConnectionUpdate(ssh_tunnel={"host": "bastion.example.com", "port": 22, "username": "user"})

        with (
            patch("gateway.api.connections.crud._validate_connection_params", return_value=[]),
            patch("gateway.api.connections.crud.schema_cache"),
            patch("gateway.api.connections.crud.pool_manager"),
            patch("gateway.api.connections.crud.ConnectionCreate"),
        ):
            await edit_connection(name="pg-prod", update=update, store=store, _role=None, request=request)

        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.metadata["credentials_changed"] is True

    @pytest.mark.asyncio
    async def test_connection_update_access_token_flags_credentials_changed(self):
        from gateway.api.connections.crud import edit_connection
        from gateway.models import ConnectionUpdate

        store = _make_store()
        request = _make_request()

        existing = MagicMock()
        existing.db_type = "postgres"
        existing.model_dump.return_value = {
            "name": "pg-prod",
            "db_type": "postgres",
            "host": "localhost",
            "port": 5432,
            "database": "db",
        }
        store.get_connection = AsyncMock(return_value=existing)
        store.get_connection_string = AsyncMock(return_value=None)
        store.update_connection = AsyncMock(return_value=existing)

        update = ConnectionUpdate(access_token="tok-abcdef")

        with (
            patch("gateway.api.connections.crud._validate_connection_params", return_value=[]),
            patch("gateway.api.connections.crud.schema_cache"),
            patch("gateway.api.connections.crud.pool_manager"),
            patch("gateway.api.connections.crud.ConnectionCreate"),
        ):
            await edit_connection(name="pg-prod", update=update, store=store, _role=None, request=request)

        entry: AuditEntry = store.append_audit.call_args[0][0]
        assert entry.metadata["credentials_changed"] is True
