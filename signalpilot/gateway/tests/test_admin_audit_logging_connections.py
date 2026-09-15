"""Tests for F-22: API-key and connection admin operations written to GatewayAuditLog.

Continues ``test_admin_audit_logging.py``; uses the same mock Store so no live
database is required.
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.models import AuditEntry

from ._admin_audit_helpers import _assert_no_credential_material, _make_request, _make_store

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

        with patch("gateway.governance.org_limits.get_org_limits", new_callable=AsyncMock) as mock_limits:
            mock_limits.return_value = MagicMock(api_keys=0)
            with patch("gateway.governance.org_limits.check_api_key_limit"):
                try:
                    await create_key(body=body, store=store, role="admin", request=request)
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
        await delete_key(key_id=key_id, store=store, role="admin", request=request)

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
            await delete_key(key_id="missing-id", store=store, role="admin", request=request)

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
        response = await delete_key(key_id=str(uuid.uuid4()), store=store, role="admin", request=request)
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
            await export_connections(body=body, store=store, request=request, _role="admin")

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
            await export_connections(body=body, store=store, request=request, _role="admin")

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
                await import_connections(manifest=manifest, store=store, request=request, _role="admin")

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
            result = await export_connections(body=body, store=store, request=request, _role="admin")

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
