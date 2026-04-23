"""Tests for BYOK key rotation and migration status endpoints.

Unit tests for rotate_byok_key function and API endpoint tests
for the rotation and migration status endpoints.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.byok import (
    DEKCache,
    LocalBYOKProvider,
    decrypt_envelope,
    encrypt_fields_envelope,
    rotate_byok_key,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_credential(
    connection_name: str = "test-conn",
    user_id: str = "user1",
    encryption_mode: str = "byok",
    connection_string_enc: bytes = b"",
    extras_enc: bytes | None = None,
    wrapped_dek: bytes | None = None,
    byok_key_id: str | None = None,
) -> MagicMock:
    cred = MagicMock()
    cred.id = str(uuid.uuid4())
    cred.user_id = user_id
    cred.connection_name = connection_name
    cred.encryption_mode = encryption_mode
    cred.connection_string_enc = connection_string_enc
    cred.extras_enc = extras_enc
    cred.wrapped_dek = wrapped_dek
    cred.byok_key_id = byok_key_id
    return cred


def _make_connection(
    name: str = "test-conn",
    user_id: str = "user1",
    org_id: str = "org1",
    byok_key_alias: str | None = None,
) -> MagicMock:
    conn = MagicMock()
    conn.name = name
    conn.user_id = user_id
    conn.org_id = org_id
    conn.byok_key_alias = byok_key_alias
    return conn


def _make_session(rows: list[tuple]) -> AsyncMock:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    session.execute.return_value = mock_result
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _make_byok_key(
    key_id: str = "key-old",
    org_id: str = "org1",
    key_alias: str = "alias-old",
    status: str = "active",
) -> MagicMock:
    key = MagicMock()
    key.id = key_id
    key.org_id = org_id
    key.key_alias = key_alias
    key.status = status
    return key


# ─── TestRotateByokKey ────────────────────────────────────────────────────────

class TestRotateByokKey:

    @pytest.mark.asyncio
    async def test_rotate_single_credential(self):
        """Single BYOK credential is re-wrapped from old key to new key."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias-old")
        provider.register_key("org1", "alias-new")

        conn_string = "postgresql://user:pass@host/db"
        fields = [conn_string, "{}"]
        ciphertexts, wrapped_dek = await encrypt_fields_envelope(
            provider, "org1", "alias-old", fields
        )

        cred = _make_credential(
            encryption_mode="byok",
            connection_string_enc=ciphertexts[0],
            extras_enc=ciphertexts[1],
            wrapped_dek=wrapped_dek,
            byok_key_id="key-old",
        )
        conn = _make_connection(org_id="org1", byok_key_alias="alias-old")

        session = _make_session([(cred, conn)])

        rotated, failed, errors = await rotate_byok_key(
            session=session,
            provider=provider,
            org_id="org1",
            old_key_id="key-old",
            old_key_alias="alias-old",
            new_key_id="key-new",
            new_key_alias="alias-new",
        )

        assert rotated == 1
        assert failed == 0
        assert errors == []
        assert cred.byok_key_id == "key-new"
        assert conn.byok_key_alias == "alias-new"

        # Verify the new ciphertext is decryptable with the new key
        recovered = await decrypt_envelope(
            provider, "org1", "alias-new", cred.wrapped_dek, cred.connection_string_enc
        )
        assert recovered == conn_string

    @pytest.mark.asyncio
    async def test_rotate_multiple_credentials(self):
        """Two credentials, both re-wrapped to new key."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias-old")
        provider.register_key("org1", "alias-new")

        async def _make_byok_cred(conn_string: str, name: str) -> tuple[MagicMock, MagicMock]:
            ciphertexts, wrapped_dek = await encrypt_fields_envelope(
                provider, "org1", "alias-old", [conn_string, "{}"]
            )
            cred = _make_credential(
                connection_name=name,
                encryption_mode="byok",
                connection_string_enc=ciphertexts[0],
                extras_enc=ciphertexts[1],
                wrapped_dek=wrapped_dek,
                byok_key_id="key-old",
            )
            conn = _make_connection(name=name, org_id="org1", byok_key_alias="alias-old")
            return cred, conn

        cred1, conn1 = await _make_byok_cred("postgresql://host1/db1", "conn1")
        cred2, conn2 = await _make_byok_cred("postgresql://host2/db2", "conn2")

        session = _make_session([(cred1, conn1), (cred2, conn2)])

        rotated, failed, errors = await rotate_byok_key(
            session=session,
            provider=provider,
            org_id="org1",
            old_key_id="key-old",
            old_key_alias="alias-old",
            new_key_id="key-new",
            new_key_alias="alias-new",
        )

        assert rotated == 2
        assert failed == 0
        assert errors == []
        assert cred1.byok_key_id == "key-new"
        assert cred2.byok_key_id == "key-new"

    @pytest.mark.asyncio
    async def test_rotate_skips_managed_credentials(self):
        """Managed credentials are not returned by the query and thus not touched."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias-old")
        provider.register_key("org1", "alias-new")

        # Query filters by encryption_mode=byok so managed creds won't appear in rows.
        # Simulate empty result (as the DB would return).
        session = _make_session([])

        rotated, failed, errors = await rotate_byok_key(
            session=session,
            provider=provider,
            org_id="org1",
            old_key_id="key-old",
            old_key_alias="alias-old",
            new_key_id="key-new",
            new_key_alias="alias-new",
        )

        assert rotated == 0
        assert failed == 0
        assert errors == []

    @pytest.mark.asyncio
    async def test_rotate_partial_failure(self):
        """One credential fails mid-rotation; the other succeeds. Error count reflects this."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias-old")
        provider.register_key("org1", "alias-new")

        conn_string = "postgresql://host/db"
        ciphertexts, wrapped_dek = await encrypt_fields_envelope(
            provider, "org1", "alias-old", [conn_string, "{}"]
        )

        good_cred = _make_credential(
            connection_name="good-conn",
            encryption_mode="byok",
            connection_string_enc=ciphertexts[0],
            extras_enc=ciphertexts[1],
            wrapped_dek=wrapped_dek,
            byok_key_id="key-old",
        )
        good_conn = _make_connection(name="good-conn", org_id="org1", byok_key_alias="alias-old")

        # Bad credential: wrapped_dek is garbage, decryption will fail.
        bad_cred = _make_credential(
            connection_name="bad-conn",
            encryption_mode="byok",
            connection_string_enc=b"garbage",
            wrapped_dek=b"bad-wrapped-dek",
            byok_key_id="key-old",
        )
        bad_conn = _make_connection(name="bad-conn", org_id="org1", byok_key_alias="alias-old")

        session = _make_session([(good_cred, good_conn), (bad_cred, bad_conn)])

        rotated, failed, errors = await rotate_byok_key(
            session=session,
            provider=provider,
            org_id="org1",
            old_key_id="key-old",
            old_key_alias="alias-old",
            new_key_id="key-new",
            new_key_alias="alias-new",
        )

        assert rotated == 1
        assert failed == 1
        assert len(errors) == 1
        assert "bad-conn" not in errors[0]
        assert "rotation error" in errors[0]

    @pytest.mark.asyncio
    async def test_rotate_with_extras(self):
        """Both connection_string_enc and extras_enc are re-encrypted."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias-old")
        provider.register_key("org1", "alias-new")

        conn_string = "postgresql://user:pass@host/db"
        extras = '{"port": 5432}'
        ciphertexts, wrapped_dek = await encrypt_fields_envelope(
            provider, "org1", "alias-old", [conn_string, extras]
        )

        cred = _make_credential(
            encryption_mode="byok",
            connection_string_enc=ciphertexts[0],
            extras_enc=ciphertexts[1],
            wrapped_dek=wrapped_dek,
            byok_key_id="key-old",
        )
        conn = _make_connection(org_id="org1", byok_key_alias="alias-old")

        session = _make_session([(cred, conn)])

        rotated, failed, errors = await rotate_byok_key(
            session=session,
            provider=provider,
            org_id="org1",
            old_key_id="key-old",
            old_key_alias="alias-old",
            new_key_id="key-new",
            new_key_alias="alias-new",
        )

        assert rotated == 1
        assert failed == 0

        # Verify both fields decryptable with new key
        recovered_cs = await decrypt_envelope(
            provider, "org1", "alias-new", cred.wrapped_dek, cred.connection_string_enc
        )
        recovered_extras = await decrypt_envelope(
            provider, "org1", "alias-new", cred.wrapped_dek, cred.extras_enc
        )
        assert recovered_cs == conn_string
        assert recovered_extras == extras

    @pytest.mark.asyncio
    async def test_rotate_invalidates_cache(self):
        """After rotation, the DEK cache entry is invalidated."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias-old")
        provider.register_key("org1", "alias-new")

        conn_string = "postgresql://host/db"
        ciphertexts, wrapped_dek = await encrypt_fields_envelope(
            provider, "org1", "alias-old", [conn_string, "{}"]
        )

        cred = _make_credential(
            encryption_mode="byok",
            connection_string_enc=ciphertexts[0],
            extras_enc=ciphertexts[1],
            wrapped_dek=wrapped_dek,
            byok_key_id="key-old",
        )
        conn = _make_connection(org_id="org1", byok_key_alias="alias-old")

        cache = DEKCache(ttl_seconds=300)
        actual_dek = await provider.unwrap_dek("org1", "alias-old", wrapped_dek)
        cache.put(cred.id, actual_dek)
        assert cache.get(cred.id) is not None

        session = _make_session([(cred, conn)])

        await rotate_byok_key(
            session=session,
            provider=provider,
            org_id="org1",
            old_key_id="key-old",
            old_key_alias="alias-old",
            new_key_id="key-new",
            new_key_alias="alias-new",
            cache=cache,
        )

        assert cache.get(cred.id) is None


# ─── TestRotateEndpoint ───────────────────────────────────────────────────────

class TestRotateEndpoint:
    """API endpoint tests for POST /byok/keys/{key_id}/rotate."""

    def _make_key_result(self, key: MagicMock | None) -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = key
        return result

    def _make_store(self) -> MagicMock:
        store = MagicMock()
        store.session = AsyncMock()
        store.session.commit = AsyncMock()
        return store

    @pytest.mark.asyncio
    async def test_rotate_success(self):
        """Successful rotation returns 200 with rotated count."""
        from gateway.api.byok import rotate_byok_key_endpoint
        from gateway.models import BYOKRotateRequest

        old_key = _make_byok_key(key_id="key-old", org_id="org1", key_alias="alias-old", status="active")
        new_key = _make_byok_key(key_id="key-new", org_id="org1", key_alias="alias-new", status="active")

        store = self._make_store()
        store.session.execute = AsyncMock(
            side_effect=[self._make_key_result(old_key), self._make_key_result(new_key)]
        )

        with patch("gateway.store._byok_provider", new=MagicMock()):
            with patch("gateway.store._dek_cache", new=None):
                with patch("gateway.api.byok.rotate_byok_key", new=AsyncMock(return_value=(2, 0, []))):
                    response = await rotate_byok_key_endpoint(
                        key_id="key-old",
                        body=BYOKRotateRequest(new_key_id="key-new"),
                        store=store,
                        org_id="org1",
                    )

        assert response.rotated == 2
        assert response.failed == 0
        assert response.errors == []

    @pytest.mark.asyncio
    async def test_rotate_old_key_not_found(self):
        """404 when old key does not exist for the org."""
        from fastapi import HTTPException

        from gateway.api.byok import rotate_byok_key_endpoint
        from gateway.models import BYOKRotateRequest

        store = self._make_store()
        store.session.execute = AsyncMock(return_value=self._make_key_result(None))

        with patch("gateway.store._byok_provider", new=MagicMock()):
            with patch("gateway.store._dek_cache", new=None):
                with pytest.raises(HTTPException) as exc_info:
                    await rotate_byok_key_endpoint(
                        key_id="missing-key",
                        body=BYOKRotateRequest(new_key_id="key-new"),
                        store=store,
                        org_id="org1",
                    )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rotate_new_key_not_found(self):
        """404 when target key does not exist for the org."""
        from fastapi import HTTPException

        from gateway.api.byok import rotate_byok_key_endpoint
        from gateway.models import BYOKRotateRequest

        old_key = _make_byok_key(key_id="key-old", org_id="org1", key_alias="alias-old", status="active")

        store = self._make_store()
        store.session.execute = AsyncMock(
            side_effect=[self._make_key_result(old_key), self._make_key_result(None)]
        )

        with patch("gateway.store._byok_provider", new=MagicMock()):
            with patch("gateway.store._dek_cache", new=None):
                with pytest.raises(HTTPException) as exc_info:
                    await rotate_byok_key_endpoint(
                        key_id="key-old",
                        body=BYOKRotateRequest(new_key_id="key-missing"),
                        store=store,
                        org_id="org1",
                    )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rotate_same_key(self):
        """400 when new_key_id == key_id."""
        from fastapi import HTTPException

        from gateway.api.byok import rotate_byok_key_endpoint
        from gateway.models import BYOKRotateRequest

        store = self._make_store()

        with patch("gateway.store._byok_provider", new=MagicMock()):
            with patch("gateway.store._dek_cache", new=None):
                with pytest.raises(HTTPException) as exc_info:
                    await rotate_byok_key_endpoint(
                        key_id="key-same",
                        body=BYOKRotateRequest(new_key_id="key-same"),
                        store=store,
                        org_id="org1",
                    )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_rotate_provider_not_configured(self):
        """503 when BYOK provider is not configured."""
        from fastapi import HTTPException

        from gateway.api.byok import rotate_byok_key_endpoint
        from gateway.models import BYOKRotateRequest

        store = self._make_store()

        with patch("gateway.store._byok_provider", new=None):
            with pytest.raises(HTTPException) as exc_info:
                await rotate_byok_key_endpoint(
                    key_id="key-old",
                    body=BYOKRotateRequest(new_key_id="key-new"),
                    store=store,
                    org_id="org1",
                )

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_rotate_marks_old_key_inactive_on_success(self):
        """Old key status is set to 'inactive' when all credentials rotate successfully."""
        from gateway.api.byok import rotate_byok_key_endpoint
        from gateway.models import BYOKRotateRequest

        old_key = _make_byok_key(key_id="key-old", org_id="org1", key_alias="alias-old", status="active")
        new_key = _make_byok_key(key_id="key-new", org_id="org1", key_alias="alias-new", status="active")

        store = self._make_store()
        store.session.execute = AsyncMock(
            side_effect=[self._make_key_result(old_key), self._make_key_result(new_key)]
        )

        with patch("gateway.store._byok_provider", new=MagicMock()):
            with patch("gateway.store._dek_cache", new=None):
                with patch("gateway.api.byok.rotate_byok_key", new=AsyncMock(return_value=(1, 0, []))):
                    await rotate_byok_key_endpoint(
                        key_id="key-old",
                        body=BYOKRotateRequest(new_key_id="key-new"),
                        store=store,
                        org_id="org1",
                    )

        assert old_key.status == "inactive"

    @pytest.mark.asyncio
    async def test_rotate_leaves_old_key_rotating_on_partial_failure(self):
        """Old key stays 'rotating' when some credentials fail to rotate."""
        from gateway.api.byok import rotate_byok_key_endpoint
        from gateway.models import BYOKRotateRequest

        old_key = _make_byok_key(key_id="key-old", org_id="org1", key_alias="alias-old", status="active")
        new_key = _make_byok_key(key_id="key-new", org_id="org1", key_alias="alias-new", status="active")

        store = self._make_store()
        store.session.execute = AsyncMock(
            side_effect=[self._make_key_result(old_key), self._make_key_result(new_key)]
        )

        with patch("gateway.store._byok_provider", new=MagicMock()):
            with patch("gateway.store._dek_cache", new=None):
                with patch(
                    "gateway.api.byok.rotate_byok_key",
                    new=AsyncMock(return_value=(1, 1, ["Failed to rotate a credential: rotation error"])),
                ):
                    await rotate_byok_key_endpoint(
                        key_id="key-old",
                        body=BYOKRotateRequest(new_key_id="key-new"),
                        store=store,
                        org_id="org1",
                    )

        assert old_key.status == "rotating"

    @pytest.mark.asyncio
    async def test_rotate_reverts_status_on_unhandled_exception(self):
        """Old key status is reverted to 'active' when an unhandled exception is raised."""
        from gateway.api.byok import rotate_byok_key_endpoint
        from gateway.models import BYOKRotateRequest

        old_key = _make_byok_key(key_id="key-old", org_id="org1", key_alias="alias-old", status="active")
        new_key = _make_byok_key(key_id="key-new", org_id="org1", key_alias="alias-new", status="active")

        store = self._make_store()
        store.session.execute = AsyncMock(
            side_effect=[self._make_key_result(old_key), self._make_key_result(new_key)]
        )

        with patch("gateway.store._byok_provider", new=MagicMock()):
            with patch("gateway.store._dek_cache", new=None):
                with patch(
                    "gateway.api.byok.rotate_byok_key",
                    new=AsyncMock(side_effect=RuntimeError("DB connection lost")),
                ):
                    with pytest.raises(RuntimeError, match="DB connection lost"):
                        await rotate_byok_key_endpoint(
                            key_id="key-old",
                            body=BYOKRotateRequest(new_key_id="key-new"),
                            store=store,
                            org_id="org1",
                        )

        assert old_key.status == "active"


# ─── TestMigrationStatusEndpoint ─────────────────────────────────────────────

class TestMigrationStatusEndpoint:
    """API endpoint tests for GET /byok/migrate/status."""

    def _make_db(self, rows: list[tuple[int, str]]) -> AsyncMock:
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        db.execute = AsyncMock(return_value=mock_result)
        return db

    @pytest.mark.asyncio
    async def test_status_all_managed(self):
        """All credentials are managed — status is 'none'."""
        from gateway.api.byok import get_migration_status

        db = self._make_db([(5, "managed")])
        response = await get_migration_status(db=db, _user_id="user1", org_id="org1")

        assert response.total == 5
        assert response.managed == 5
        assert response.byok == 0
        assert response.status == "none"

    @pytest.mark.asyncio
    async def test_status_all_byok(self):
        """All credentials are BYOK — status is 'complete'."""
        from gateway.api.byok import get_migration_status

        db = self._make_db([(3, "byok")])
        response = await get_migration_status(db=db, _user_id="user1", org_id="org1")

        assert response.total == 3
        assert response.byok == 3
        assert response.managed == 0
        assert response.status == "complete"

    @pytest.mark.asyncio
    async def test_status_mixed(self):
        """Mix of managed and BYOK credentials — status is 'partial'."""
        from gateway.api.byok import get_migration_status

        db = self._make_db([(2, "byok"), (4, "managed")])
        response = await get_migration_status(db=db, _user_id="user1", org_id="org1")

        assert response.total == 6
        assert response.byok == 2
        assert response.managed == 4
        assert response.status == "partial"

    @pytest.mark.asyncio
    async def test_status_no_credentials(self):
        """No credentials at all — status is 'none' with zero counts."""
        from gateway.api.byok import get_migration_status

        db = self._make_db([])
        response = await get_migration_status(db=db, _user_id="user1", org_id="org1")

        assert response.total == 0
        assert response.byok == 0
        assert response.managed == 0
        assert response.status == "none"
