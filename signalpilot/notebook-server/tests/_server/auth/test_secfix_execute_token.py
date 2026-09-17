"""SP-01 Option A: authorize_execution checks claims, not the signature.

The runtime holds no gateway signing secret. The execute route is gated by
the per-session access token; the token in the body is only presented back
to the gateway, which verifies it. These tests pin the structural checks.
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from starlette.exceptions import HTTPException

from signalpilot._server.auth.standalone_chat import authorize_execution

COMMIT = "b" * 40
RUN = "run-33333333"


@pytest.fixture(autouse=True)
def process_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SP_SESSION_JWT_SECRET", raising=False)
    monkeypatch.delenv("SP_NOTEBOOK_TOKEN_SECRET", raising=False)
    monkeypatch.setenv("SP_SESSION_ID", "session-x")
    monkeypatch.setenv("SP_ORG_ID", "org-x")
    monkeypatch.setenv("SP_CHAT_PROJECT_ID", "project-x")
    monkeypatch.setenv("SP_CHAT_BRANCH", "main")
    monkeypatch.setenv("SP_CHAT_CONNECTION_NAME", "production")
    monkeypatch.setenv("SP_CHAT_COMMIT_SHA", COMMIT)


def _claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": "signalpilot-notebook-session",
        "aud": "signalpilot-gateway",
        "sub": "user-x",
        "org_id": "org-x",
        "session_id": "session-x",
        "execution_identity": f"chat:{RUN}",
        "project_id": "project-x",
        "branch": "main",
        "connection_name": "production",
        "commit_sha": COMMIT,
        "capabilities": ["query:read"],
        "scopes": ["read", "query", "execute"],
        "iat": now,
        "exp": now + 300,
    }
    claims.update(overrides)
    return claims


def _body(token: str) -> dict[str, Any]:
    return {
        "run_id": RUN,
        "project_id": "project-x",
        "branch": "main",
        "connection_name": "production",
        "commit_sha": COMMIT,
        "gateway_session_token": token,
    }


def test_unsigned_token_with_correct_claims_is_accepted() -> None:
    token = jwt.encode(_claims(), key=None, algorithm="none")
    authorization = authorize_execution(_body(token))
    assert authorization.scope.run_id == RUN
    assert authorization.gateway_token == token


def test_any_signature_with_correct_claims_is_accepted() -> None:
    token = jwt.encode(
        _claims(), "not-the-gateway-secret-not-the-gateway", algorithm="HS256"
    )
    assert authorize_execution(_body(token)).scope.run_id == RUN


def test_wrong_execution_identity_is_rejected() -> None:
    token = jwt.encode(
        _claims(execution_identity="chat:run-99999999"), "k" * 32, algorithm="HS256"
    )
    with pytest.raises(HTTPException, match="Scoped gateway identity mismatch"):
        authorize_execution(_body(token))


def test_expired_token_is_rejected() -> None:
    now = int(time.time())
    token = jwt.encode(_claims(iat=now - 600, exp=now - 120), "k" * 32, algorithm="HS256")
    with pytest.raises(HTTPException, match="Invalid scoped gateway identity") as info:
        authorize_execution(_body(token))
    assert info.value.status_code == 403


def test_wrong_audience_is_rejected() -> None:
    token = jwt.encode(_claims(aud="someone-else"), "k" * 32, algorithm="HS256")
    with pytest.raises(HTTPException, match="Invalid scoped gateway identity"):
        authorize_execution(_body(token))


def test_wrong_issuer_is_rejected() -> None:
    token = jwt.encode(_claims(iss="someone-else"), "k" * 32, algorithm="HS256")
    with pytest.raises(HTTPException, match="Invalid scoped gateway identity"):
        authorize_execution(_body(token))


def test_missing_required_claim_is_rejected() -> None:
    claims = _claims()
    del claims["session_id"]
    token = jwt.encode(claims, "k" * 32, algorithm="HS256")
    with pytest.raises(HTTPException, match="Invalid scoped gateway identity"):
        authorize_execution(_body(token))


def test_garbage_token_is_rejected() -> None:
    with pytest.raises(HTTPException, match="Invalid scoped gateway identity"):
        authorize_execution(_body("not.a.jwt"))
