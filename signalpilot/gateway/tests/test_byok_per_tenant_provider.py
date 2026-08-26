"""Tests that each tenant BYOK key row wraps with its OWN provider.

Before the per-key provider resolution, store encrypt/decrypt and the validate
endpoint all used the single process-wide provider configured from env, so a
tenant that registered its own KMS key had credentials wrapped by the operator's
key while validate reported the tenant key healthy.

Providers are recorded rather than real: make_provider_for_key is patched so a
distinct fake provider is built per KMS ARN, and the assertions are on which
provider/key identifier actually performed each wrap and unwrap.
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.byok import (
    BYOKKeyError,
    DEKCache,
    decrypt_envelope,
    dek_cache_key,
    encrypt_fields_envelope,
    rotate_byok_key,
)
from gateway.db.models import GatewayBase, GatewayBYOKKey, GatewayOrg
from gateway.models import ConnectionCreate
from gateway.store import Store, byok_state

_ARN_A = "arn:aws:kms:us-east-1:111111111111:key/tenant-a"
_ARN_B = "arn:aws:kms:us-east-1:222222222222:key/tenant-b"


# ─── Recording provider ───────────────────────────────────────────────────────


class RecordingProvider:
    """Fernet-backed provider that records every wrap/unwrap it performs."""

    def __init__(self, identifier: str) -> None:
        self._identifier = identifier
        self._kek = Fernet.generate_key()
        self.wraps: list[tuple[str, str]] = []
        self.unwraps: list[tuple[str, str]] = []

    def key_identifier(self) -> str:
        return self._identifier

    async def wrap_dek(self, org_id: str, key_alias: str, dek_plaintext: bytes) -> bytes:
        self.wraps.append((org_id, key_alias))
        return Fernet(self._kek).encrypt(dek_plaintext)

    async def unwrap_dek(self, org_id: str, key_alias: str, wrapped_dek: bytes) -> bytes:
        self.unwraps.append((org_id, key_alias))
        try:
            return Fernet(self._kek).decrypt(wrapped_dek)
        except InvalidToken as exc:
            raise BYOKKeyError(org_id, key_alias, "Failed to unwrap DEK") from exc

    async def generate_dek(self) -> bytes:
        return Fernet.generate_key()

    async def health_check(self) -> bool:
        return True


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def tenant_providers():
    """Patch the factory so each KMS ARN yields its own recording provider."""
    providers: dict[str, RecordingProvider] = {
        _ARN_A: RecordingProvider(_ARN_A),
        _ARN_B: RecordingProvider(_ARN_B),
    }

    def _make(byok_key):
        arn = (byok_key.provider_config or {})["kms_key_arn"]
        return providers[arn]

    byok_state.invalidate_provider_cache()
    with patch("gateway.store.byok_state.make_provider_for_key", side_effect=_make):
        yield providers
    byok_state.invalidate_provider_cache()


@pytest.fixture
def operator_provider():
    """Configure a recording process-wide provider and restore state after."""
    prev_provider = byok_state._byok_provider
    prev_cache = byok_state._dek_cache
    operator = RecordingProvider("operator-kek")
    byok_state.configure_byok(operator, DEKCache(ttl_seconds=300))
    try:
        yield operator
    finally:
        byok_state._byok_provider = prev_provider
        byok_state._dek_cache = prev_cache
        byok_state.invalidate_provider_cache()


async def _register_tenant(session: AsyncSession, org_id: str, alias: str, arn: str) -> GatewayBYOKKey:
    key = GatewayBYOKKey(
        id=str(uuid.uuid4()),
        org_id=org_id,
        key_alias=alias,
        provider_type="aws_kms",
        provider_config={"kms_key_arn": arn},
        status="active",
        created_at=time.time(),
    )
    session.add(key)
    session.add(GatewayOrg(org_id=org_id, byok_enabled=True, default_byok_key_id=key.id, created_at=time.time()))
    await session.commit()
    return key


def _conn(name: str) -> ConnectionCreate:
    return ConnectionCreate(
        name=name,
        db_type="postgres",
        host="db.example.com",
        port=5432,
        database="app",
        username="svc",
        password="pw-for-" + name,
    )


# ─── Two tenants, two KMS keys ────────────────────────────────────────────────


class TestPerTenantProvider:
    @pytest.mark.asyncio
    async def test_each_org_wraps_with_its_own_kms_key(self, db_session, tenant_providers, operator_provider):
        """Each row's credentials are wrapped by the provider for ITS key, not the operator's."""
        await _register_tenant(db_session, "org-a", "alias-a", _ARN_A)
        await _register_tenant(db_session, "org-b", "alias-b", _ARN_B)

        await Store(db_session, org_id="org-a", user_id="u1").create_connection(_conn("conn-a"))
        await Store(db_session, org_id="org-b", user_id="u2").create_connection(_conn("conn-b"))

        assert tenant_providers[_ARN_A].wraps == [("org-a", "alias-a")]
        assert tenant_providers[_ARN_B].wraps == [("org-b", "alias-b")]
        assert operator_provider.wraps == []

    @pytest.mark.asyncio
    async def test_decrypt_uses_the_row_provider(self, db_session, tenant_providers, operator_provider):
        """Reading a credential unwraps with the tenant's key identifier only."""
        await _register_tenant(db_session, "org-a", "alias-a", _ARN_A)
        await _register_tenant(db_session, "org-b", "alias-b", _ARN_B)

        store_a = Store(db_session, org_id="org-a", user_id="u1")
        store_b = Store(db_session, org_id="org-b", user_id="u2")
        await store_a.create_connection(_conn("conn-a"))
        await store_b.create_connection(_conn("conn-b"))

        assert "pw-for-conn-a" in (await store_a.get_connection_string("conn-a"))
        assert "pw-for-conn-b" in (await store_b.get_connection_string("conn-b"))

        assert tenant_providers[_ARN_A].unwraps == [("org-a", "alias-a")]
        assert tenant_providers[_ARN_B].unwraps == [("org-b", "alias-b")]
        assert operator_provider.unwraps == []

    @pytest.mark.asyncio
    async def test_tenant_b_provider_cannot_read_tenant_a_credential(
        self, db_session, tenant_providers, operator_provider
    ):
        """The KEKs really are distinct — B's provider cannot unwrap A's DEK."""
        from sqlalchemy import select

        from gateway.db.models import GatewayCredential

        await _register_tenant(db_session, "org-a", "alias-a", _ARN_A)
        await Store(db_session, org_id="org-a", user_id="u1").create_connection(_conn("conn-a"))

        row = (
            await db_session.execute(select(GatewayCredential).where(GatewayCredential.org_id == "org-a"))
        ).scalar_one()
        with pytest.raises(BYOKKeyError):
            await decrypt_envelope(
                provider=tenant_providers[_ARN_B],
                org_id="org-a",
                key_alias="alias-a",
                wrapped_dek=row.wrapped_dek,
                ciphertext=row.connection_string_enc,
            )

    @pytest.mark.asyncio
    async def test_provider_cache_reuses_one_instance_per_key(self, db_session, tenant_providers, operator_provider):
        """provider_for_key caches by key id + config digest."""
        key = await _register_tenant(db_session, "org-a", "alias-a", _ARN_A)
        first = byok_state.provider_for_key(key)
        second = byok_state.provider_for_key(key)
        assert first is second

        key.provider_config = {"kms_key_arn": _ARN_B}
        assert byok_state.provider_for_key(key) is tenant_providers[_ARN_B]

    @pytest.mark.asyncio
    async def test_invalidate_provider_cache_drops_the_entry(self, db_session, tenant_providers, operator_provider):
        """Rotation/update paths can force a rebuild for one key id."""
        key = await _register_tenant(db_session, "org-a", "alias-a", _ARN_A)
        byok_state.provider_for_key(key)
        with patch("gateway.store.byok_state.make_provider_for_key") as mock_make:
            mock_make.return_value = tenant_providers[_ARN_A]
            byok_state.provider_for_key(key)
            mock_make.assert_not_called()
            byok_state.invalidate_provider_cache(key.id)
            byok_state.provider_for_key(key)
            mock_make.assert_called_once()

    @pytest.mark.asyncio
    async def test_unbuildable_provider_fails_closed(self, db_session, operator_provider):
        """An unsupported provider_type must not silently fall back to the operator key."""
        key = GatewayBYOKKey(
            id=str(uuid.uuid4()),
            org_id="org-c",
            key_alias="alias-c",
            provider_type="gcp_kms",
            provider_config={"key_uri": "projects/x"},
            status="active",
            created_at=time.time(),
        )
        db_session.add(key)
        db_session.add(GatewayOrg(org_id="org-c", byok_enabled=True, default_byok_key_id=key.id, created_at=0.0))
        await db_session.commit()

        with pytest.raises(byok_state.BYOKProviderUnavailable):
            byok_state.provider_for_key(key)
        assert operator_provider.wraps == []


# ─── validate endpoint ────────────────────────────────────────────────────────


class TestValidateUsesRowProvider:
    @pytest.fixture
    def admin_client(self):
        from fastapi.testclient import TestClient

        from gateway.auth import resolve_org_id
        from gateway.db.engine import get_db
        from gateway.main import app
        from gateway.store import get_local_api_key

        self.key_row = MagicMock()
        self.key_row.id = "key-a"
        self.key_row.org_id = "org-a"
        self.key_row.key_alias = "alias-a"
        self.key_row.provider_type = "aws_kms"
        self.key_row.provider_config = {"kms_key_arn": _ARN_A}
        self.key_row.status = "active"
        self.key_row.created_at = time.time()
        self.key_row.revoked_at = None

        session = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = self.key_row

        async def _execute(*_a, **_k):
            return result

        session.execute = _execute

        async def _db():
            yield session

        async def _org():
            return "org-a"

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[resolve_org_id] = _org
        try:
            yield TestClient(app, headers={"Authorization": f"Bearer {get_local_api_key()}"})
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(resolve_org_id, None)

    def test_validate_exercises_the_tenant_provider_not_the_operator(
        self, admin_client, tenant_providers, operator_provider
    ):
        """validate for tenant key A must never touch the process-wide provider."""
        resp = admin_client.post("/api/byok/keys/key-a/validate")
        assert resp.status_code == 200
        assert resp.json() == {"valid": True}

        assert tenant_providers[_ARN_A].wraps == [("org-a", "alias-a")]
        assert tenant_providers[_ARN_A].unwraps == [("org-a", "alias-a")]
        assert operator_provider.wraps == []
        assert operator_provider.unwraps == []

    def test_validate_fails_when_the_row_provider_cannot_be_built(self, admin_client, operator_provider):
        """No provider for the row means invalid — not a pass via the operator key."""
        with patch(
            "gateway.store.byok_state.make_provider_for_key",
            side_effect=ImportError("boto3 is required"),
        ):
            resp = admin_client.post("/api/byok/keys/key-a/validate")
        assert resp.status_code == 200
        assert resp.json()["valid"] is False
        assert operator_provider.wraps == []


# ─── KMS key identity bound into the encryption context ───────────────────────


class TestAwsEncryptionContextBinding:
    def _provider(self):
        from gateway.byok.aws_kms import AWSKMSProvider

        return AWSKMSProvider({"kms_key_arn": _ARN_A, "region": "us-east-1"})

    @pytest.mark.asyncio
    async def test_wrap_binds_the_kms_key_id(self):
        """New wraps authenticate the KMS key identifier alongside org and alias."""
        provider = self._provider()
        client = MagicMock()
        client.encrypt.return_value = {"CiphertextBlob": b"blob"}

        with patch.object(provider, "_get_client", return_value=client):
            assert await provider.wrap_dek("org-a", "alias-a", b"dek") == b"blob"

        ctx = client.encrypt.call_args.kwargs["EncryptionContext"]
        assert ctx == {"org_id": "org-a", "key_alias": "alias-a", "kms_key_id": _ARN_A}

    @pytest.mark.asyncio
    async def test_legacy_context_ciphertext_still_unwraps(self):
        """DEKs wrapped before the binding must keep decrypting."""
        from botocore.exceptions import ClientError

        provider = self._provider()
        client = MagicMock()
        contexts: list[dict] = []

        def _decrypt(**kwargs):
            ctx = kwargs["EncryptionContext"]
            contexts.append(ctx)
            if "kms_key_id" in ctx:
                raise ClientError(
                    {"Error": {"Code": "InvalidCiphertextException", "Message": "context mismatch"}},
                    "Decrypt",
                )
            return {"Plaintext": b"dek"}

        client.decrypt.side_effect = _decrypt

        with patch.object(provider, "_get_client", return_value=client):
            assert await provider.unwrap_dek("org-a", "alias-a", b"legacy") == b"dek"

        assert len(contexts) == 2
        assert "kms_key_id" in contexts[0]
        assert contexts[1] == {"org_id": "org-a", "key_alias": "alias-a"}

    @pytest.mark.asyncio
    async def test_access_denied_is_not_retried_under_the_legacy_context(self):
        """Only a context mismatch triggers the fallback."""
        from botocore.exceptions import ClientError

        from gateway.byok import BYOKKeyError

        provider = self._provider()
        client = MagicMock()
        client.decrypt.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "Decrypt"
        )

        with patch.object(provider, "_get_client", return_value=client):
            with pytest.raises(BYOKKeyError):
                await provider.unwrap_dek("org-a", "alias-a", b"blob")

        assert client.decrypt.call_count == 1


# ─── DEK cache invalidation on rotation ───────────────────────────────────────


class TestDekCacheInvalidation:
    @pytest.mark.asyncio
    async def test_rotation_invalidates_the_cached_dek(self):
        """rotate_byok_key must purge the composite cache entry, not a bare cred id."""
        old_provider = RecordingProvider("kek-old")
        new_provider = RecordingProvider("kek-new")
        ciphertexts, wrapped_dek = await encrypt_fields_envelope(old_provider, "org1", "alias-old", ["dsn", "{}"])

        cred = MagicMock()
        cred.id = "cred-1"
        cred.connection_name = "c"
        cred.encryption_mode = "byok"
        cred.connection_string_enc = ciphertexts[0]
        cred.extras_enc = ciphertexts[1]
        cred.wrapped_dek = wrapped_dek
        cred.byok_key_id = "key-old"
        conn = MagicMock()
        conn.org_id = "org1"
        conn.byok_key_alias = "alias-old"

        cache = DEKCache(ttl_seconds=300)
        await decrypt_envelope(
            provider=old_provider,
            org_id="org1",
            key_alias="alias-old",
            wrapped_dek=wrapped_dek,
            ciphertext=ciphertexts[0],
            cache=cache,
            credential_id=cred.id,
        )
        cached_key = dek_cache_key("org1", cred.id, old_provider)
        assert cache.get(cached_key) is not None

        session = MagicMock()
        result = MagicMock()
        result.all.return_value = [(cred, conn)]

        async def _execute(*_a, **_k):
            return result

        async def _noop():
            return None

        session.execute = _execute
        session.commit = _noop
        session.rollback = _noop

        rotated, failed, _ = await rotate_byok_key(
            session=session,
            provider=new_provider,
            org_id="org1",
            old_key_id="key-old",
            old_key_alias="alias-old",
            new_key_id="key-new",
            new_key_alias="alias-new",
            cache=cache,
            old_provider=old_provider,
        )

        assert (rotated, failed) == (1, 0)
        assert cache.get(cached_key) is None
        assert cache.stats()["size"] == 0
        # Unwrapping happened under the old key, re-wrapping under the new one.
        assert old_provider.unwraps and new_provider.wraps
        assert new_provider.unwraps == []
