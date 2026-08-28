"""Authorization for conversation-warm standalone chat execution.

The notebook process is scoped to one conversation and survives multiple runs.
Conversation-stable project fields are pinned at process start. The current run
is authorized by a fresh, signed gateway JWT on every execute request.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import jwt
from starlette.exceptions import HTTPException

_AUDIENCE = "signalpilot-gateway"
_ISSUER = "signalpilot-notebook-session"
_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9-]{8,80}$")
_REQUIRED_SCOPES = frozenset({"read", "query", "execute"})
_REQUIRED_CLAIMS = (
    "sub",
    "org_id",
    "session_id",
    "execution_identity",
    "project_id",
    "branch",
    "connection_name",
    "commit_sha",
    "scopes",
    "iat",
    "exp",
)


@dataclass(frozen=True)
class ExecutionScope:
    run_id: str
    project_id: str
    branch: str
    connection_name: str
    commit_sha: str

    @classmethod
    def from_request(cls, body: dict[str, Any]) -> ExecutionScope:
        scope = cls(
            run_id=validate_run_id(body.get("run_id")),
            project_id=str(body.get("project_id") or ""),
            branch=str(body.get("branch") or ""),
            connection_name=str(body.get("connection_name") or ""),
            commit_sha=str(body.get("commit_sha") or ""),
        )
        if not re.fullmatch(r"[0-9a-fA-F]{40}", scope.commit_sha):
            raise HTTPException(status_code=400, detail="Invalid commit SHA")
        scope._validate_conversation_boundary()
        return scope

    def _validate_conversation_boundary(self) -> None:
        """Reject requests outside the project context fixed at process boot."""
        expected = {
            "project_id": os.getenv("SP_CHAT_PROJECT_ID"),
            "branch": os.getenv("SP_CHAT_BRANCH"),
            "connection_name": os.getenv("SP_CHAT_CONNECTION_NAME"),
            "commit_sha": os.getenv("SP_CHAT_COMMIT_SHA"),
        }
        for field, value in expected.items():
            if value and getattr(self, field) != value:
                raise HTTPException(status_code=403, detail="Execution scope mismatch")


@dataclass(frozen=True)
class AuthorizedExecution:
    scope: ExecutionScope
    gateway_token: str


def validate_run_id(value: object) -> str:
    run_id = str(value or "")
    if not _RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")
    return run_id


def authorize_execution(body: dict[str, Any]) -> AuthorizedExecution:
    """Validate one execute request and return its trusted execution identity."""
    scope = ExecutionScope.from_request(body)
    token = str(body.get("gateway_session_token") or "").strip()
    if not token:
        raise HTTPException(status_code=403, detail="Scoped gateway identity required")
    claims = _verify_gateway_token(token)
    _validate_claims(claims, scope)
    return AuthorizedExecution(scope=scope, gateway_token=token)


def gateway_mcp_config(authorization: AuthorizedExecution) -> dict[str, Any]:
    """Build the only gateway MCP credential exposed to the chat agent."""
    gateway_url = str(
        os.getenv("SP_GATEWAY_INTERNAL_URL")
        or os.getenv("SP_GATEWAY_URL")
        or "http://gateway:3300"
    ).rstrip("/")
    if not gateway_url.endswith("/mcp"):
        gateway_url = f"{gateway_url}/mcp"
    return {
        "mcpServers": {
            "signalpilot": {
                "type": "http",
                "url": gateway_url,
                "headers": {
                    "Authorization": f"Bearer {authorization.gateway_token}"
                },
            }
        }
    }


def _verify_gateway_token(token: str) -> dict[str, Any]:
    secret = os.getenv("SP_SESSION_JWT_SECRET", "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Scoped gateway identity verification is unavailable",
        )
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=_AUDIENCE,
            issuer=_ISSUER,
            options={"require": list(_REQUIRED_CLAIMS)},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=403, detail="Invalid scoped gateway identity"
        ) from exc
    if not isinstance(claims, dict):
        raise HTTPException(status_code=403, detail="Invalid scoped gateway identity")
    return claims


def _validate_claims(claims: dict[str, Any], scope: ExecutionScope) -> None:
    expected = {
        "execution_identity": f"chat:{scope.run_id}",
        "project_id": scope.project_id,
        "branch": scope.branch,
        "connection_name": scope.connection_name,
        "commit_sha": scope.commit_sha,
    }
    process_identity = {
        "session_id": os.getenv("SP_SESSION_ID"),
        "org_id": os.getenv("SP_ORG_ID"),
    }
    expected.update({key: value for key, value in process_identity.items() if value})
    if any(claims.get(key) != value for key, value in expected.items()):
        raise HTTPException(status_code=403, detail="Scoped gateway identity mismatch")

    raw_scopes = claims.get("scopes")
    if not isinstance(raw_scopes, list) or not all(
        isinstance(value, str) for value in raw_scopes
    ):
        raise HTTPException(status_code=403, detail="Invalid scoped gateway identity")
    scopes = set(raw_scopes)
    if "write" in scopes or not _REQUIRED_SCOPES.issubset(scopes):
        raise HTTPException(status_code=403, detail="Invalid scoped gateway scopes")
