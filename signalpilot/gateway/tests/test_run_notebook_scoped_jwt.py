"""Tests for L-3: run_notebook export step uses scoped session JWT, not raw MCP key.

Class: TestRunNotebookPodEnvScopedJWT

Tests the _build_export_invocation helper extracted from run_notebook.
The helper is pure (takes cloud: bool as a parameter) so no k8s or store
mocking is required.
"""

from __future__ import annotations

import jwt
import pytest

from gateway.auth.notebook_jwt import (
    NOTEBOOK_SESSION_AUD,
    NOTEBOOK_SESSION_ISS,
    NOTEBOOK_SESSION_SCOPES,
)
from gateway.mcp.tools.notebook import _build_export_invocation

_TEST_SECRET = "test-scoped-jwt-secret-for-l3-48bytes!!"
_RAW_MCP_KEY = "sp_admin_raw_key_xxx"

_USER_ID = "user-l3"
_ORG_ID = "org-l3"
_SESSION_ID = "sess-l3-abc123"
_PROJECT_ID = "proj-l3"
_BRANCH = "signalpilot-agent/abc123"
_EXPORT_TARGET = "/home/notebook/.sp/projects/proj-l3/analysis.py"


def _patch_secret(monkeypatch) -> None:
    monkeypatch.setattr("gateway.auth.notebook_jwt.load_session_jwt_secret", lambda: _TEST_SECRET)
    monkeypatch.setattr("gateway.auth.jwt_secret._cached_secret", _TEST_SECRET)


def _patch_k8s_settings(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from gateway.config.k8s import K8sSettings

    fake_settings = MagicMock(spec=K8sSettings)
    fake_settings.sp_session_jwt_ttl_seconds = 3600
    monkeypatch.setattr("gateway.mcp.tools.notebook._get_k8s_settings", lambda: fake_settings)


def _invoke_cloud(monkeypatch) -> tuple[list[str], bytes]:
    """Run _build_export_invocation in cloud mode and return (argv, stdin_bytes)."""
    _patch_secret(monkeypatch)
    _patch_k8s_settings(monkeypatch)
    argv, stdin_bytes = _build_export_invocation(
        cloud=True,
        user_id=_USER_ID,
        org_id=_ORG_ID,
        session_id=_SESSION_ID,
        project_id=_PROJECT_ID,
        branch=_BRANCH,
        export_target=_EXPORT_TARGET,
    )
    assert stdin_bytes is not None
    return argv, stdin_bytes


class TestRunNotebookPodEnvScopedJWT:
    """L-3: export step pipes a scoped session JWT — never the caller's raw key."""

    def test_cloud_mode_pod_stdin_contains_session_jwt_not_raw_key(self, monkeypatch):
        """Cloud path: stdin contains a valid JWT, not the raw MCP key."""
        argv, stdin_bytes = _invoke_cloud(monkeypatch)

        # stdin must be a JWT (three dot-separated base64url segments)
        token = stdin_bytes.decode("utf-8").strip()
        assert token.count(".") == 2, "stdin should be a JWT (three parts)"

        # Decode without verifying signature to inspect claims
        claims = jwt.decode(token, options={"verify_signature": False})
        assert isinstance(claims, dict)

        # The raw MCP key must NOT appear anywhere in the stdin bytes
        assert _RAW_MCP_KEY.encode() not in stdin_bytes
        assert b"sp_admin_raw_key_xxx" not in stdin_bytes

    def test_cloud_mode_jwt_scopes_are_exactly_subset(self, monkeypatch):
        """Cloud path: JWT scopes are exactly {read, write, query, execute}."""
        _, stdin_bytes = _invoke_cloud(monkeypatch)
        token = stdin_bytes.decode("utf-8").strip()
        claims = jwt.decode(token, options={"verify_signature": False})

        assert set(claims["scopes"]) == set(NOTEBOOK_SESSION_SCOPES)
        assert set(claims["scopes"]) == {"read", "write", "query", "execute"}

        # Defense-in-depth: exact-set equality already covers these, but explicit
        # negatives document intent (no admin/billing/secret-write escalation).
        assert "admin" not in claims["scopes"]
        assert "write:secret" not in claims["scopes"]
        assert "billing" not in claims["scopes"]

    def test_cloud_mode_jwt_claims_match_session(self, monkeypatch):
        """Cloud path: JWT claims match the session parameters passed in."""
        _, stdin_bytes = _invoke_cloud(monkeypatch)
        token = stdin_bytes.decode("utf-8").strip()

        # Verify with the test secret to get trusted claims
        claims = jwt.decode(
            token,
            _TEST_SECRET,
            algorithms=["HS256"],
            audience=NOTEBOOK_SESSION_AUD,
            issuer=NOTEBOOK_SESSION_ISS,
        )

        assert claims["sub"] == _USER_ID
        assert claims["org_id"] == _ORG_ID
        assert claims["session_id"] == _SESSION_ID
        assert claims["project_id"] == _PROJECT_ID
        assert claims["branch"] == _BRANCH
        assert claims["iss"] == NOTEBOOK_SESSION_ISS
        assert claims["aud"] == NOTEBOOK_SESSION_AUD

    def test_local_mode_no_stdin_no_jwt(self, monkeypatch):
        """Local path: no stdin bytes and argv uses python -m signalpilot form."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

        argv, stdin_bytes = _build_export_invocation(
            cloud=False,
            user_id=_USER_ID,
            org_id=_ORG_ID,
            session_id=_SESSION_ID,
            project_id=_PROJECT_ID,
            branch=_BRANCH,
            export_target=_EXPORT_TARGET,
        )

        assert stdin_bytes is None
        # Must use `python -m signalpilot export` form, NOT `python -c wrapper`
        assert argv[0] == "python"
        assert "-m" in argv
        assert "signalpilot" in argv
        assert "export" in argv
        assert "-c" not in argv

    def test_raw_mcp_key_never_appears_in_pod_invocation(self, monkeypatch):
        """Cloud path: the raw MCP key does not appear in argv or stdin_bytes."""
        argv, stdin_bytes = _invoke_cloud(monkeypatch)

        raw_key = "sp_RAW_KEY_SHOULD_NOT_LEAK"

        # Must not appear in any element of argv
        assert all(raw_key not in arg for arg in argv)

        # Must not appear in the stdin bytes
        assert raw_key.encode() not in stdin_bytes
