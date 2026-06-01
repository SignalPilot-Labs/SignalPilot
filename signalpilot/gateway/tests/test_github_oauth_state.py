"""Tests for GitHub OAuth state token generation and verification.

Covers the public API in ``gateway.api._oauth_state``:
- Key resolution (cloud vs local, cached vs uncached)
- State minting and verification
- Replay prevention via nonce store
- Tamper resistance (signature + payload)
- Ordering guarantee: nonce store NOT mutated for states that fail HMAC
"""

from __future__ import annotations

import time

import pytest

import gateway.api._oauth_state as _oauth_state
from gateway.api._oauth_state import (
    get_state_hmac_key,
    make_state,
    verify_state,
)


@pytest.fixture(autouse=True)
def _reset_oauth_state_module(monkeypatch: pytest.MonkeyPatch):
    """Reset module-level singletons so each test starts clean."""
    monkeypatch.setattr(_oauth_state, "_HMAC_KEY", None)
    # Replace the nonce store with a fresh one so replay state doesn't bleed
    monkeypatch.setattr(_oauth_state, "_NONCE_STORE", _oauth_state._NonceStore())
    yield


@pytest.fixture()
def fixed_key_env(monkeypatch: pytest.MonkeyPatch):
    """Set a fixed SP_ENCRYPTION_KEY and clear cloud mode for deterministic tests."""
    monkeypatch.setenv("SP_ENCRYPTION_KEY", "test-secret-key-for-oauth-state")
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")


class TestGitHubOAuthState:
    # ── Key resolution ────────────────────────────────────────────────────

    def test_cloud_mode_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch):
        """Cloud mode without SP_ENCRYPTION_KEY must raise RuntimeError."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.delenv("SP_ENCRYPTION_KEY", raising=False)
        # _HMAC_KEY already reset by autouse fixture

        with pytest.raises(RuntimeError, match="SP_ENCRYPTION_KEY required in cloud mode"):
            get_state_hmac_key()

    def test_local_mode_missing_key_generates_random(self, monkeypatch: pytest.MonkeyPatch):
        """Local mode without SP_ENCRYPTION_KEY generates a random 32-byte key and caches it."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        monkeypatch.delenv("SP_ENCRYPTION_KEY", raising=False)

        key1 = get_state_hmac_key()
        assert isinstance(key1, bytes)
        assert len(key1) == 32

        # Second call returns the same cached key
        key2 = get_state_hmac_key()
        assert key1 == key2

    # ── verify_state: empty / None inputs ────────────────────────────────

    def test_verify_empty_string_returns_none(self, fixed_key_env: None):
        assert verify_state("") is None

    def test_verify_none_returns_none(self, fixed_key_env: None):
        assert verify_state(None) is None

    # ── verify_state: old format rejection ───────────────────────────────

    def test_old_format_state_rejected(self, fixed_key_env: None):
        """Pre-v2 state format (no v2: prefix) must be rejected."""
        old_state = "orgid:abc123def456789.deadbeef12345678"
        assert verify_state(old_state) is None

    # ── verify_state: expiry ──────────────────────────────────────────────

    def test_expired_state_rejected(self, monkeypatch: pytest.MonkeyPatch, fixed_key_env: None):
        """State past TTL must be rejected."""
        state = make_state("my-org")

        # Advance time past TTL
        original_time = time.time
        monkeypatch.setattr(
            _oauth_state.time,
            "time",
            lambda: original_time() + _oauth_state.STATE_TTL_SECONDS + 1,
        )

        assert verify_state(state) is None

    # ── verify_state: replay ──────────────────────────────────────────────

    def test_replay_rejected(self, fixed_key_env: None):
        """Second use of the same state token must be rejected."""
        state = make_state("my-org")

        result1 = verify_state(state)
        assert result1 == "my-org"

        result2 = verify_state(state)
        assert result2 is None

    def test_replay_after_expiry_rejected(self, monkeypatch: pytest.MonkeyPatch, fixed_key_env: None):
        """After TTL expires the state should still be rejected (expired or replay)."""
        state = make_state("my-org")

        original_time = time.time
        monkeypatch.setattr(
            _oauth_state.time,
            "time",
            lambda: original_time() + _oauth_state.STATE_TTL_SECONDS + 1,
        )

        # Both attempts return None — no exception raised
        assert verify_state(state) is None
        assert verify_state(state) is None

    # ── verify_state: happy path ──────────────────────────────────────────

    def test_happy_path(self, fixed_key_env: None):
        """Minted state immediately verified must return the original org_id."""
        org_id = "acme-corp"
        state = make_state(org_id)
        result = verify_state(state)
        assert result == org_id

    # ── verify_state: tamper resistance ──────────────────────────────────

    def test_tampered_signature_rejected(self, fixed_key_env: None):
        """Flipping a character in the signature must invalidate the state."""
        state = make_state("my-org")
        dot_idx = state.rfind(".")
        payload = state[:dot_idx]
        sig = state[dot_idx + 1:]

        # Flip the first character of the signature
        bad_char = "a" if sig[0] != "a" else "b"
        tampered = f"{payload}.{bad_char}{sig[1:]}"

        assert verify_state(tampered) is None

    def test_tampered_org_rejected(self, fixed_key_env: None):
        """Swapping org_id in the payload while reusing the original signature must fail."""
        state = make_state("my-org")
        dot_idx = state.rfind(".")
        payload = state[:dot_idx]
        sig = state[dot_idx + 1:]

        # Swap org_id in payload — signature will no longer match
        fields = payload.split(":")
        fields[1] = "evil-org"
        tampered_payload = ":".join(fields)
        tampered = f"{tampered_payload}.{sig}"

        assert verify_state(tampered) is None

    # ── nonce-store ordering guarantee ────────────────────────────────────

    def test_reserve_not_called_for_bad_hmac(self, fixed_key_env: None):
        """Nonce must NOT be inserted into the store when HMAC verification fails."""
        state = make_state("my-org")
        dot_idx = state.rfind(".")
        payload = state[:dot_idx]
        sig = state[dot_idx + 1:]

        # Tamper the signature
        bad_char = "a" if sig[0] != "a" else "b"
        tampered = f"{payload}.{bad_char}{sig[1:]}"

        verify_state(tampered)

        # Extract nonce from the original (untampered) payload
        fields = payload.split(":")
        nonce_hex = fields[2]

        # The nonce must NOT be present in the store
        assert nonce_hex not in _oauth_state._NONCE_STORE._entries
