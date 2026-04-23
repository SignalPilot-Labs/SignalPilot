"""Tests for BYOK Phase 2: migration functions, multi-field encrypt, and key lifecycle.

These tests use LocalBYOKProvider and mocked async sessions — no Postgres required.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.byok import (
    DEKCache,
    LocalBYOKProvider,
    decrypt_envelope,
    encrypt_fields_envelope,
    migrate_to_byok,
    revert_to_managed,
)
from gateway.store import _encrypt, _decrypt_with_migration


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_credential(
    connection_name: str = "test-conn",
    user_id: str = "user1",
    encryption_mode: str = "managed",
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


# ─── encrypt_fields_envelope tests ───────────────────────────────────────────

class TestEncryptFieldsEnvelope:

    @pytest.mark.asyncio
    async def test_single_dek_for_multiple_fields(self):
        """One wrapped_dek must decrypt both ciphertexts."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")

        fields = ["postgresql://user:pass@host/db", '{"key": "value"}']
        ciphertexts, wrapped_dek = await encrypt_fields_envelope(
            provider, "org1", "alias1", fields
        )

        assert len(ciphertexts) == 2
        # Both ciphertexts must decrypt with the same wrapped_dek
        recovered_cs = await decrypt_envelope(
            provider, "org1", "alias1", wrapped_dek, ciphertexts[0]
        )
        recovered_extras = await decrypt_envelope(
            provider, "org1", "alias1", wrapped_dek, ciphertexts[1]
        )

        assert recovered_cs == fields[0]
        assert recovered_extras == fields[1]

    @pytest.mark.asyncio
    async def test_returns_correct_ciphertext_count(self):
        provider = LocalBYOKProvider()
        provider.register_key("org1", "key1")
        fields = ["a", "b", "c"]
        ciphertexts, wrapped_dek = await encrypt_fields_envelope(
            provider, "org1", "key1", fields
        )
        assert len(ciphertexts) == 3
        assert isinstance(wrapped_dek, bytes)

    @pytest.mark.asyncio
    async def test_each_call_produces_different_dek(self):
        """Two calls to encrypt_fields_envelope must produce different wrapped_deks."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")
        fields = ["same-content"]
        _, wrapped_dek_1 = await encrypt_fields_envelope(provider, "org1", "alias1", fields)
        _, wrapped_dek_2 = await encrypt_fields_envelope(provider, "org1", "alias1", fields)
        # Different DEKs → different wrapped DEKs
        assert wrapped_dek_1 != wrapped_dek_2


# ─── migrate_to_byok tests ────────────────────────────────────────────────────

class TestMigrateToByok:

    def _make_session(self, rows: list[tuple]) -> AsyncMock:
        """Build a minimal AsyncMock session that returns rows from execute()."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        session.execute.return_value = mock_result
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_migrate_managed_credential(self):
        """Managed credential is re-encrypted to BYOK mode."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")

        conn_string = "postgresql://user:pass@host/db"
        extras = json.dumps({"key": "val"})

        cred = _make_credential(
            encryption_mode="managed",
            connection_string_enc=_encrypt(conn_string),
            extras_enc=_encrypt(extras),
        )
        conn = _make_connection(org_id="org1")

        session = self._make_session([(cred, conn)])

        migrated, failed, errors = await migrate_to_byok(
            session=session,
            provider=provider,
            org_id="org1",
            key_id="key-id-1",
            key_alias="alias1",
            managed_decrypt=_decrypt_with_migration,
        )

        assert migrated == 1
        assert failed == 0
        assert errors == []
        assert cred.encryption_mode == "byok"
        assert cred.byok_key_id == "key-id-1"
        assert cred.wrapped_dek is not None
        # Verify ciphertext is now BYOK-encrypted (decryptable with provider)
        recovered = await decrypt_envelope(
            provider, "org1", "alias1", cred.wrapped_dek, cred.connection_string_enc
        )
        assert recovered == conn_string

    @pytest.mark.asyncio
    async def test_migrate_credential_without_extras(self):
        """Credential with no extras_enc is migrated safely."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")

        conn_string = "sqlite:///test.db"
        cred = _make_credential(
            encryption_mode="managed",
            connection_string_enc=_encrypt(conn_string),
            extras_enc=None,
        )
        conn = _make_connection(org_id="org1")

        session = self._make_session([(cred, conn)])

        migrated, failed, errors = await migrate_to_byok(
            session=session,
            provider=provider,
            org_id="org1",
            key_id="key-id-2",
            key_alias="alias1",
            managed_decrypt=_decrypt_with_migration,
        )

        assert migrated == 1
        assert failed == 0
        assert cred.encryption_mode == "byok"

    @pytest.mark.asyncio
    async def test_migrate_partial_failure_continues(self):
        """Migration continues after one credential fails; partial results reported."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")

        conn_string = "postgresql://host/db"
        good_cred = _make_credential(
            connection_name="good-conn",
            encryption_mode="managed",
            connection_string_enc=_encrypt(conn_string),
            extras_enc=_encrypt("{}"),
        )
        bad_cred = _make_credential(
            connection_name="bad-conn",
            encryption_mode="managed",
            connection_string_enc=b"garbage-not-fernet",
            extras_enc=None,
        )
        conn1 = _make_connection(name="good-conn", org_id="org1")
        conn2 = _make_connection(name="bad-conn", org_id="org1")

        session = self._make_session([(good_cred, conn1), (bad_cred, conn2)])

        migrated, failed, errors = await migrate_to_byok(
            session=session,
            provider=provider,
            org_id="org1",
            key_id="key-id-3",
            key_alias="alias1",
            managed_decrypt=_decrypt_with_migration,
        )

        assert migrated == 1
        assert failed == 1
        assert len(errors) == 1
        # Error message uses credential ID (not connection name) to avoid info leak (H2)
        assert "bad-conn" not in errors[0]
        assert "migration error" in errors[0]

    @pytest.mark.asyncio
    async def test_migrate_empty_org_returns_zero(self):
        """Org with no managed credentials returns (0, 0, [])."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")

        session = self._make_session([])

        migrated, failed, errors = await migrate_to_byok(
            session=session,
            provider=provider,
            org_id="org1",
            key_id="key-id-4",
            key_alias="alias1",
            managed_decrypt=_decrypt_with_migration,
        )

        assert migrated == 0
        assert failed == 0
        assert errors == []


# ─── revert_to_managed tests ─────────────────────────────────────────────────

class TestRevertToManaged:

    def _make_session(self, rows: list[tuple]) -> AsyncMock:
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        session.execute.return_value = mock_result
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_revert_byok_credential_to_managed(self):
        """BYOK credential is re-encrypted back to managed mode."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")

        conn_string = "postgresql://user:pass@host/db"
        extras = json.dumps({"port": 5432})

        # Set up a BYOK-encrypted credential
        fields = [conn_string, extras]
        ciphertexts, wrapped_dek = await encrypt_fields_envelope(
            provider, "org1", "alias1", fields
        )

        cred = _make_credential(
            encryption_mode="byok",
            connection_string_enc=ciphertexts[0],
            extras_enc=ciphertexts[1],
            wrapped_dek=wrapped_dek,
            byok_key_id="key-id-1",
        )
        conn = _make_connection(org_id="org1", byok_key_alias="alias1")

        session = self._make_session([(cred, conn)])
        cache = DEKCache(ttl_seconds=300)

        migrated, failed, errors = await revert_to_managed(
            session=session,
            provider=provider,
            org_id="org1",
            managed_encrypt=_encrypt,
            cache=cache,
        )

        assert migrated == 1
        assert failed == 0
        assert errors == []
        assert cred.encryption_mode == "managed"
        assert cred.wrapped_dek is None
        assert cred.byok_key_id is None
        # Verify the re-encrypted ciphertext is valid managed Fernet
        recovered_cs, _ = _decrypt_with_migration(cred.connection_string_enc)
        assert recovered_cs == conn_string
        recovered_ex, _ = _decrypt_with_migration(cred.extras_enc)
        assert recovered_ex == extras

    @pytest.mark.asyncio
    async def test_revert_clears_dek_cache(self):
        """After revert, the DEK cache entry for the credential is invalidated."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")

        conn_string = "mysql://host/db"
        fields = [conn_string, "{}"]
        ciphertexts, wrapped_dek = await encrypt_fields_envelope(
            provider, "org1", "alias1", fields
        )

        cred = _make_credential(
            encryption_mode="byok",
            connection_string_enc=ciphertexts[0],
            extras_enc=ciphertexts[1],
            wrapped_dek=wrapped_dek,
        )
        conn = _make_connection(org_id="org1", byok_key_alias="alias1")

        cache = DEKCache(ttl_seconds=300)
        # Pre-populate cache with the actual DEK (as if it was cached from a prior decrypt)
        actual_dek = await provider.unwrap_dek("org1", "alias1", wrapped_dek)
        cache.put(cred.id, actual_dek)
        assert cache.get(cred.id) is not None

        session = self._make_session([(cred, conn)])

        await revert_to_managed(
            session=session,
            provider=provider,
            org_id="org1",
            managed_encrypt=_encrypt,
            cache=cache,
        )

        assert cache.get(cred.id) is None

    @pytest.mark.asyncio
    async def test_revert_missing_wrapped_dek_fails(self):
        """Credential in BYOK mode but missing wrapped_dek is counted as failed."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")

        cred = _make_credential(
            encryption_mode="byok",
            connection_string_enc=b"something",
            wrapped_dek=None,
        )
        conn = _make_connection(org_id="org1", byok_key_alias="alias1")

        session = self._make_session([(cred, conn)])

        migrated, failed, errors = await revert_to_managed(
            session=session,
            provider=provider,
            org_id="org1",
            managed_encrypt=_encrypt,
        )

        assert migrated == 0
        assert failed == 1
        assert len(errors) == 1

    @pytest.mark.asyncio
    async def test_revert_empty_org_returns_zero(self):
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")

        session = self._make_session([])

        migrated, failed, errors = await revert_to_managed(
            session=session,
            provider=provider,
            org_id="org1",
            managed_encrypt=_encrypt,
        )

        assert migrated == 0
        assert failed == 0
        assert errors == []


# ─── Migrate + Revert roundtrip ───────────────────────────────────────────────

class TestMigrateRevertRoundtrip:

    @pytest.mark.asyncio
    async def test_migrate_then_revert_recovers_plaintext(self):
        """Full roundtrip: managed → BYOK → managed preserves data."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")

        conn_string = "postgresql://user:pass@host/db"
        extras = json.dumps({"ssh_tunnel": {"enabled": True}})

        cred = _make_credential(
            encryption_mode="managed",
            connection_string_enc=_encrypt(conn_string),
            extras_enc=_encrypt(extras),
        )
        conn = _make_connection(org_id="org1")

        # ── Phase 1: migrate to BYOK ──

        migrate_session = AsyncMock()
        mock_result_1 = MagicMock()
        mock_result_1.all.return_value = [(cred, conn)]
        migrate_session.execute.return_value = mock_result_1
        migrate_session.commit = AsyncMock()
        migrate_session.rollback = AsyncMock()

        migrated, failed, _ = await migrate_to_byok(
            session=migrate_session,
            provider=provider,
            org_id="org1",
            key_id="key-id-1",
            key_alias="alias1",
            managed_decrypt=_decrypt_with_migration,
        )
        assert migrated == 1
        assert failed == 0
        assert cred.encryption_mode == "byok"

        # Verify BYOK decryption works
        recovered_cs = await decrypt_envelope(
            provider, "org1", conn.byok_key_alias, cred.wrapped_dek, cred.connection_string_enc
        )
        assert recovered_cs == conn_string

        # ── Phase 2: revert to managed ──

        revert_session = AsyncMock()
        mock_result_2 = MagicMock()
        mock_result_2.all.return_value = [(cred, conn)]
        revert_session.execute.return_value = mock_result_2
        revert_session.commit = AsyncMock()
        revert_session.rollback = AsyncMock()

        migrated, failed, _ = await revert_to_managed(
            session=revert_session,
            provider=provider,
            org_id="org1",
            managed_encrypt=_encrypt,
        )
        assert migrated == 1
        assert failed == 0
        assert cred.encryption_mode == "managed"
        assert cred.wrapped_dek is None

        # Verify managed decryption still works
        final_cs, _ = _decrypt_with_migration(cred.connection_string_enc)
        assert final_cs == conn_string
        final_ex, _ = _decrypt_with_migration(cred.extras_enc)
        assert final_ex == extras


# ─── GatewayOrg model tests ───────────────────────────────────────────────────

class TestGatewayOrgModel:

    def test_gateway_org_fields(self):
        """GatewayOrg has the expected columns."""
        from gateway.db.models import GatewayOrg
        cols = {c.name for c in GatewayOrg.__table__.columns}
        assert "org_id" in cols
        assert "byok_enabled" in cols
        assert "default_byok_key_id" in cols
        assert "created_at" in cols
        # Ensure the old spec's UUID id and name are NOT present
        assert "id" not in cols
        assert "name" not in cols

    def test_gateway_org_primary_key(self):
        """org_id is the primary key."""
        from gateway.db.models import GatewayOrg
        pk_cols = [c.name for c in GatewayOrg.__table__.primary_key.columns]
        assert pk_cols == ["org_id"]


# ─── ConnectionCreate BYOK fields ────────────────────────────────────────────

class TestConnectionCreateBYOKFields:

    def test_connection_create_accepts_org_id_and_byok_key_alias(self):
        """ConnectionCreate accepts org_id and byok_key_alias fields."""
        from gateway.models import ConnectionCreate, DBType
        conn = ConnectionCreate(
            name="myconn",
            db_type=DBType.duckdb,
            org_id="org1",
            byok_key_alias="my-key",
        )
        assert conn.org_id == "org1"
        assert conn.byok_key_alias == "my-key"

    def test_connection_create_byok_fields_optional(self):
        """org_id and byok_key_alias default to None."""
        from gateway.models import ConnectionCreate, DBType
        conn = ConnectionCreate(name="myconn", db_type=DBType.duckdb)
        assert conn.org_id is None
        assert conn.byok_key_alias is None

    def test_byok_key_alias_pattern_validation(self):
        """byok_key_alias must match [a-zA-Z0-9_-]+."""
        from gateway.models import ConnectionCreate, DBType
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ConnectionCreate(
                name="myconn",
                db_type=DBType.duckdb,
                byok_key_alias="invalid alias!",
            )


# ─── Pydantic BYOK models ─────────────────────────────────────────────────────

class TestBYOKPydanticModels:

    def test_byok_key_create_valid(self):
        from gateway.models import BYOKKeyCreate
        # org_id is no longer user-supplied in BYOKKeyCreate (derived from JWT)
        obj = BYOKKeyCreate(
            key_alias="my-key",
            provider_type="local",
        )
        assert obj.key_alias == "my-key"
        assert obj.provider_config is None

    def test_byok_key_create_invalid_provider_type(self):
        from gateway.models import BYOKKeyCreate
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            BYOKKeyCreate(org_id="org1", key_alias="k", provider_type="unknown")

    def test_byok_key_update_status_revoked(self):
        from gateway.models import BYOKKeyUpdate
        obj = BYOKKeyUpdate(status="revoked")
        assert obj.status == "revoked"

    def test_byok_key_update_invalid_status(self):
        from gateway.models import BYOKKeyUpdate
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            BYOKKeyUpdate(status="deleted")

    def test_byok_migrate_response(self):
        from gateway.models import BYOKMigrateResponse
        resp = BYOKMigrateResponse(migrated=5, failed=1, errors=["err"])
        assert resp.migrated == 5
        assert resp.failed == 1
        assert resp.errors == ["err"]
