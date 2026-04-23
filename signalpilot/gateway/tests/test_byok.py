"""Unit tests for gateway.byok — BYOK envelope encryption, LocalBYOKProvider, and DEKCache.

No database is required for these tests.
"""

from __future__ import annotations

import time
import pytest

from gateway.byok import (
    BYOKKeyError,
    BYOKProvider,
    DEKCache,
    LocalBYOKProvider,
    decrypt_envelope,
    encrypt_envelope,
)


# ─── LocalBYOKProvider tests ─────────────────────────────────────────────────

class TestLocalBYOKProvider:

    @pytest.mark.asyncio
    async def test_wrap_unwrap_roundtrip(self):
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")
        dek = await provider.generate_dek()
        wrapped = await provider.wrap_dek("org1", "alias1", dek)
        unwrapped = await provider.unwrap_dek("org1", "alias1", wrapped)
        assert unwrapped == dek

    @pytest.mark.asyncio
    async def test_revoked_key_raises(self):
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")
        dek = await provider.generate_dek()
        wrapped = await provider.wrap_dek("org1", "alias1", dek)
        provider.revoke_key("org1", "alias1")
        with pytest.raises(BYOKKeyError) as exc_info:
            await provider.unwrap_dek("org1", "alias1", wrapped)
        assert exc_info.value.org_id == "org1"
        assert exc_info.value.key_alias == "alias1"

    @pytest.mark.asyncio
    async def test_unknown_key_raises(self):
        provider = LocalBYOKProvider()
        with pytest.raises(BYOKKeyError) as exc_info:
            await provider.unwrap_dek("org1", "nonexistent", b"garbage")
        assert exc_info.value.org_id == "org1"
        assert exc_info.value.key_alias == "nonexistent"

    @pytest.mark.asyncio
    async def test_wrap_unknown_key_raises(self):
        provider = LocalBYOKProvider()
        with pytest.raises(BYOKKeyError):
            await provider.wrap_dek("org1", "nonexistent", b"some-dek")

    @pytest.mark.asyncio
    async def test_health_check_returns_true(self):
        provider = LocalBYOKProvider()
        assert await provider.health_check() is True

    @pytest.mark.asyncio
    async def test_generate_dek_is_fernet_key(self):
        """generate_dek() returns a Fernet-format key (44 bytes, base64url-encoded)."""
        from cryptography.fernet import Fernet
        provider = LocalBYOKProvider()
        dek = await provider.generate_dek()
        assert len(dek) == 44
        # Must be usable directly as a Fernet key — raises if invalid
        Fernet(dek)

    @pytest.mark.asyncio
    async def test_register_key_with_explicit_key(self):
        """register_key accepts a pre-generated Fernet key."""
        from cryptography.fernet import Fernet
        provider = LocalBYOKProvider()
        explicit_key = Fernet.generate_key()
        provider.register_key("org1", "alias1", key=explicit_key)
        dek = await provider.generate_dek()
        wrapped = await provider.wrap_dek("org1", "alias1", dek)
        unwrapped = await provider.unwrap_dek("org1", "alias1", wrapped)
        assert unwrapped == dek

    @pytest.mark.asyncio
    async def test_revoke_is_idempotent(self):
        """Revoking an already-revoked (or nonexistent) key does not raise."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")
        provider.revoke_key("org1", "alias1")
        provider.revoke_key("org1", "alias1")  # second call must not raise


# ─── Envelope encryption tests ───────────────────────────────────────────────

class TestEnvelopeEncryption:

    @pytest.mark.asyncio
    async def test_encrypt_decrypt_roundtrip(self):
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")
        plaintext = "postgresql://user:secret@host/db"
        ciphertext, wrapped_dek = await encrypt_envelope(provider, "org1", "alias1", plaintext)
        recovered = await decrypt_envelope(
            provider, "org1", "alias1", wrapped_dek, ciphertext
        )
        assert recovered == plaintext

    @pytest.mark.asyncio
    async def test_cross_provider_isolation(self):
        """Ciphertext from provider A cannot be decrypted by provider B with different key."""
        provider_a = LocalBYOKProvider()
        provider_a.register_key("org1", "alias1")
        provider_b = LocalBYOKProvider()
        provider_b.register_key("org1", "alias1")

        plaintext = "sensitive-connection-string"
        ciphertext, wrapped_dek = await encrypt_envelope(provider_a, "org1", "alias1", plaintext)

        with pytest.raises(BYOKKeyError):
            await decrypt_envelope(provider_b, "org1", "alias1", wrapped_dek, ciphertext)

    @pytest.mark.asyncio
    async def test_revoked_key_post_cache_invalidation(self):
        """After cache invalidation + key revocation, decrypt raises BYOKKeyError."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")
        cache = DEKCache(ttl_seconds=300)
        plaintext = "secret"
        ciphertext, wrapped_dek = await encrypt_envelope(provider, "org1", "alias1", plaintext)

        # First decrypt — populates cache
        cred_id = "cred-001"
        await decrypt_envelope(
            provider, "org1", "alias1", wrapped_dek, ciphertext,
            cache=cache, credential_id=cred_id,
        )

        # Revoke key and invalidate cache
        provider.revoke_key("org1", "alias1")
        cache.invalidate(cred_id)

        with pytest.raises(BYOKKeyError):
            await decrypt_envelope(
                provider, "org1", "alias1", wrapped_dek, ciphertext,
                cache=cache, credential_id=cred_id,
            )

    @pytest.mark.asyncio
    async def test_decrypt_uses_cache_on_second_call(self):
        """provider.unwrap_dek is called only once when cache is warm on second call."""
        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")
        cache = DEKCache(ttl_seconds=300)
        plaintext = "cached-secret"
        ciphertext, wrapped_dek = await encrypt_envelope(provider, "org1", "alias1", plaintext)
        cred_id = "cred-cache-test"

        original_unwrap = provider.unwrap_dek
        call_count = 0

        async def counting_unwrap(org_id: str, key_alias: str, wrapped: bytes) -> bytes:
            nonlocal call_count
            call_count += 1
            return await original_unwrap(org_id, key_alias, wrapped)

        provider.unwrap_dek = counting_unwrap  # type: ignore[method-assign]

        result1 = await decrypt_envelope(
            provider, "org1", "alias1", wrapped_dek, ciphertext,
            cache=cache, credential_id=cred_id,
        )
        result2 = await decrypt_envelope(
            provider, "org1", "alias1", wrapped_dek, ciphertext,
            cache=cache, credential_id=cred_id,
        )

        assert result1 == plaintext
        assert result2 == plaintext
        assert call_count == 1  # second call served from cache


# ─── DEKCache tests ───────────────────────────────────────────────────────────

class TestDEKCache:

    def test_cache_hit(self):
        cache = DEKCache(ttl_seconds=300)
        dek = b"a" * 32
        cache.put("cred-1", dek)
        assert cache.get("cred-1") == dek

    def test_cache_miss_unknown_key(self):
        cache = DEKCache(ttl_seconds=300)
        assert cache.get("nonexistent") is None

    def test_cache_expiry(self):
        cache = DEKCache(ttl_seconds=0)
        dek = b"b" * 32
        cache.put("cred-2", dek)
        # TTL is 0 — any subsequent get should see it as expired
        time.sleep(0.05)
        assert cache.get("cred-2") is None

    def test_cache_invalidate(self):
        cache = DEKCache(ttl_seconds=300)
        dek = b"c" * 32
        cache.put("cred-3", dek)
        cache.invalidate("cred-3")
        assert cache.get("cred-3") is None

    def test_cache_invalidate_nonexistent_is_safe(self):
        cache = DEKCache(ttl_seconds=300)
        cache.invalidate("does-not-exist")  # must not raise

    def test_cache_clear(self):
        cache = DEKCache(ttl_seconds=300)
        cache.put("cred-4", b"d" * 32)
        cache.put("cred-5", b"e" * 32)
        cache.clear()
        assert cache.get("cred-4") is None
        assert cache.get("cred-5") is None

    def test_cache_stats(self):
        cache = DEKCache(ttl_seconds=120)
        cache.put("cred-6", b"f" * 32)
        cache.put("cred-7", b"g" * 32)
        stats = cache.stats()
        assert stats["size"] == 2
        assert stats["ttl_seconds"] == 120

    def test_cache_stats_empty(self):
        cache = DEKCache(ttl_seconds=60)
        assert cache.stats() == {"size": 0, "ttl_seconds": 60}

    def test_cache_expiry_removed_from_store(self):
        """Expired entries are removed from _store when accessed."""
        cache = DEKCache(ttl_seconds=0)
        cache.put("cred-8", b"h" * 32)
        time.sleep(0.05)
        cache.get("cred-8")  # triggers removal
        assert cache.stats()["size"] == 0


# ─── BYOKKeyError tests ───────────────────────────────────────────────────────

class TestBYOKKeyError:

    def test_attributes(self):
        err = BYOKKeyError(org_id="org1", key_alias="alias1", message="test error")
        assert err.org_id == "org1"
        assert err.key_alias == "alias1"
        assert err.message == "test error"
        assert str(err) == "test error"

    def test_is_exception_subclass(self):
        err = BYOKKeyError(org_id="org1", key_alias="a", message="msg")
        assert isinstance(err, Exception)


# ─── BYOKProvider protocol conformance ───────────────────────────────────────

class TestBYOKProviderProtocol:

    def test_local_provider_satisfies_protocol(self):
        provider = LocalBYOKProvider()
        assert isinstance(provider, BYOKProvider)
