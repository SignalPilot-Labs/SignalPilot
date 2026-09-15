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

from ._admin_audit_helpers import _assert_no_credential_material, _make_request, _make_store

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
        key_mock.provider_type = "local"
        key_mock.provider_config = None
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
        old_key.provider_type = "local"
        old_key.provider_config = None

        new_key = MagicMock()
        new_key.org_id = "test-org"
        new_key.status = "active"
        new_key.key_alias = "new-alias"
        new_key.provider_type = "local"
        new_key.provider_config = None

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
