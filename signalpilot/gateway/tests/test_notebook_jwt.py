"""Unit tests for notebook session JWT minting and verification."""

from __future__ import annotations

import time

import jwt
import pytest

from gateway.auth.notebook_jwt import (
    NOTEBOOK_SESSION_AUD,
    NOTEBOOK_SESSION_ISS,
    NotebookSessionJWTError,
    mint_session_jwt,
    verify_session_jwt,
)

_TEST_SECRET = "test-secret-for-unit-tests"


def _patch_secret(monkeypatch):
    """Patch load_session_jwt_secret to return a fixed test secret."""
    monkeypatch.setattr("gateway.auth.notebook_jwt.load_session_jwt_secret", lambda: _TEST_SECRET)


def _mint(monkeypatch, **overrides):
    _patch_secret(monkeypatch)
    defaults = dict(
        user_id="user-1",
        org_id="org-1",
        session_id="sess-1",
        branch="main",
        ttl=3600,
    )
    defaults.update(overrides)
    return mint_session_jwt(**defaults)


class TestMintAndVerifyRoundTrip:
    def test_round_trip_with_all_claims(self, monkeypatch):
        _patch_secret(monkeypatch)
        token = _mint(monkeypatch)
        claims = verify_session_jwt(token)
        assert claims["sub"] == "user-1"
        assert claims["org_id"] == "org-1"
        assert claims["session_id"] == "sess-1"
        assert claims["branch"] == "main"
        assert claims["iss"] == NOTEBOOK_SESSION_ISS
        assert claims["aud"] == NOTEBOOK_SESSION_AUD

    def test_claims_contain_iat_and_exp(self, monkeypatch):
        _patch_secret(monkeypatch)
        before = int(time.time())
        token = _mint(monkeypatch, ttl=600)
        claims = verify_session_jwt(token)
        assert claims["exp"] >= before + 599
        assert claims["iat"] >= before


class TestVerifyRejectsInvalidTokens:
    def test_rejects_wrong_aud(self, monkeypatch):
        _patch_secret(monkeypatch)
        payload = {
            "iss": NOTEBOOK_SESSION_ISS,
            "aud": "wrong-audience",
            "sub": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": ["read", "write"],
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, _TEST_SECRET, algorithm="HS256")
        with pytest.raises(NotebookSessionJWTError, match="audience"):
            verify_session_jwt(token)

    def test_rejects_wrong_iss(self, monkeypatch):
        _patch_secret(monkeypatch)
        payload = {
            "iss": "wrong-issuer",
            "aud": NOTEBOOK_SESSION_AUD,
            "sub": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": ["read", "write"],
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, _TEST_SECRET, algorithm="HS256")
        with pytest.raises(NotebookSessionJWTError, match="issuer"):
            verify_session_jwt(token)

    def test_rejects_expired_token(self, monkeypatch):
        _patch_secret(monkeypatch)
        payload = {
            "iss": NOTEBOOK_SESSION_ISS,
            "aud": NOTEBOOK_SESSION_AUD,
            "sub": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": ["read", "write"],
            "iat": int(time.time()) - 7200,
            "exp": int(time.time()) - 3600,
        }
        token = jwt.encode(payload, _TEST_SECRET, algorithm="HS256")
        with pytest.raises(NotebookSessionJWTError, match="expired"):
            verify_session_jwt(token)

    def test_rejects_tampered_signature(self, monkeypatch):
        _patch_secret(monkeypatch)
        token = _mint(monkeypatch)
        # Flip last byte of signature
        parts = token.split(".")
        sig = parts[2]
        # Change first char of signature
        flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
        tampered = ".".join(parts[:2] + [flipped])
        with pytest.raises(NotebookSessionJWTError):
            verify_session_jwt(tampered)

    def test_rejects_bad_signature_different_key(self, monkeypatch):
        _patch_secret(monkeypatch)
        payload = {
            "iss": NOTEBOOK_SESSION_ISS,
            "aud": NOTEBOOK_SESSION_AUD,
            "sub": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": ["read", "write"],
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, "different-secret", algorithm="HS256")
        with pytest.raises(NotebookSessionJWTError, match="[Ss]ignature"):
            verify_session_jwt(token)

    def test_rejects_missing_org_id_claim(self, monkeypatch):
        _patch_secret(monkeypatch)
        # Mint a valid token then decode it without org_id
        payload = {
            "iss": NOTEBOOK_SESSION_ISS,
            "aud": NOTEBOOK_SESSION_AUD,
            "sub": "user-1",
            # org_id deliberately absent
            "session_id": "sess-1",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, _TEST_SECRET, algorithm="HS256")
        with pytest.raises(NotebookSessionJWTError):
            verify_session_jwt(token)

    def test_rejects_malformed_token(self, monkeypatch):
        _patch_secret(monkeypatch)
        with pytest.raises(NotebookSessionJWTError):
            verify_session_jwt("not.a.valid.jwt.at.all")
