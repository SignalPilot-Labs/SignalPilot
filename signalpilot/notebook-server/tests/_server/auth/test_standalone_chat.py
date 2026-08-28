from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from starlette.exceptions import HTTPException

from signalpilot._server.auth.standalone_chat import (
    authorize_execution,
    gateway_mcp_config,
    validate_run_id,
)

SECRET = "standalone-chat-test-secret-at-least-32-bytes"
COMMIT = "a" * 40


@pytest.fixture(autouse=True)
def process_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SP_SESSION_JWT_SECRET", SECRET)
    monkeypatch.setenv("SP_SESSION_ID", "session-a")
    monkeypatch.setenv("SP_ORG_ID", "org-a")
    monkeypatch.setenv("SP_CHAT_PROJECT_ID", "project-a")
    monkeypatch.setenv("SP_CHAT_BRANCH", "main")
    monkeypatch.setenv("SP_CHAT_CONNECTION_NAME", "production")
    monkeypatch.setenv("SP_CHAT_COMMIT_SHA", COMMIT)


def _body(
    run_id: str,
    *,
    claim_overrides: dict[str, Any] | None = None,
    request_overrides: dict[str, Any] | None = None,
    secret: str = SECRET,
) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": "signalpilot-notebook-session",
        "aud": "signalpilot-gateway",
        "sub": "user-a",
        "org_id": "org-a",
        "session_id": "session-a",
        "execution_identity": f"chat:{run_id}",
        "project_id": "project-a",
        "branch": "main",
        "connection_name": "production",
        "commit_sha": COMMIT,
        "capabilities": ["query:read"],
        "scopes": ["read", "query", "execute"],
        "iat": now,
        "exp": now + 300,
    }
    claims.update(claim_overrides or {})
    body: dict[str, Any] = {
        "run_id": run_id,
        "project_id": "project-a",
        "branch": "main",
        "connection_name": "production",
        "commit_sha": COMMIT,
        "gateway_session_token": jwt.encode(claims, secret, algorithm="HS256"),
    }
    body.update(request_overrides or {})
    return body


def test_one_warm_process_authorizes_two_distinct_runs() -> None:
    first = authorize_execution(_body("run-11111111"))
    second = authorize_execution(_body("run-22222222"))

    assert first.scope.run_id == "run-11111111"
    assert second.scope.run_id == "run-22222222"


def test_conversation_stable_scope_remains_pinned() -> None:
    with pytest.raises(HTTPException, match="Execution scope mismatch"):
        authorize_execution(
            _body(
                "run-11111111",
                claim_overrides={"connection_name": "warehouse-b"},
                request_overrides={"connection_name": "warehouse-b"},
            )
        )


@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"execution_identity": "chat:run-22222222"},
        {"session_id": "another-session"},
        {"org_id": "another-org"},
        {"scopes": ["read", "query"]},
        {"scopes": ["read", "query", "execute", "write"]},
    ],
)
def test_request_claims_must_match_the_run_and_process(
    claim_overrides: dict[str, Any],
) -> None:
    with pytest.raises(HTTPException):
        authorize_execution(
            _body("run-11111111", claim_overrides=claim_overrides)
        )


def test_token_signature_is_verified() -> None:
    with pytest.raises(HTTPException, match="Invalid scoped gateway identity"):
        authorize_execution(
            _body("run-11111111", secret="wrong-secret-that-is-also-at-least-32-bytes")
        )


def test_missing_verification_secret_is_service_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SP_SESSION_JWT_SECRET")
    with pytest.raises(HTTPException) as exc_info:
        authorize_execution(_body("run-11111111"))
    assert exc_info.value.status_code == 503


def test_gateway_mcp_uses_the_verified_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SP_GATEWAY_INTERNAL_URL", "http://gateway:3300")
    authorization = authorize_execution(_body("run-11111111"))

    server = gateway_mcp_config(authorization)["mcpServers"]["signalpilot"]

    assert server["url"] == "http://gateway:3300/mcp"
    assert server["headers"]["Authorization"] == (
        f"Bearer {authorization.gateway_token}"
    )


@pytest.mark.parametrize("run_id", ["", "short", "bad/run/id"])
def test_cancel_run_ids_use_the_same_syntax_boundary(run_id: str) -> None:
    with pytest.raises(HTTPException, match="Invalid run id"):
        validate_run_id(run_id)
