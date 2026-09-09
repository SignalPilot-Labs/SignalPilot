"""Run-bound MCP credentials, also accepted by explicit governed REST adapters."""

import time

import jwt
from sqlalchemy import select

from gateway.auth.jwt_secret import load_session_jwt_secret
from gateway.db.engine import get_session_factory
from gateway.db.models import MCPAgentThread

PREFIX = "spa_"
ISSUER = "signalpilot-mcp-agent"


def mint(thread, ttl: int) -> str:
    now = int(time.time())
    return PREFIX + jwt.encode(
        {
            "iss": ISSUER,
            "aud": "signalpilot-mcp",
            "sub": thread.user_id,
            "org_id": thread.org_id,
            "session_id": thread.id,
            "run_id": thread.run_id,
            "project_id": thread.request["project_id"],
            "branch": thread.request["branch"],
            "connection_name": thread.request["connection_name"],
            "execution_identity": "agent:" + thread.run_id,
            "scopes": ["read", "query"],
            "iat": now,
            "exp": min(now + ttl, int(thread.expires_at)),
        },
        load_session_jwt_secret(),
        algorithm="HS256",
    )


async def verify(token: str) -> dict:
    claims = jwt.decode(
        token.removeprefix(PREFIX),
        load_session_jwt_secret(),
        algorithms=["HS256"],
        issuer=ISSUER,
        audience="signalpilot-mcp",
        options={"require": ["exp", "iat", "sub", "org_id", "session_id", "run_id", "project_id", "connection_name"]},
    )
    async with get_session_factory()() as db:
        row = await db.scalar(
            select(MCPAgentThread).where(
                MCPAgentThread.id == claims["session_id"],
                MCPAgentThread.org_id == claims["org_id"],
                MCPAgentThread.user_id == claims["sub"],
                MCPAgentThread.run_id == claims["run_id"],
                MCPAgentThread.status == "running",
                MCPAgentThread.expires_at > time.time(),
                MCPAgentThread.lease_expires_at > time.time(),
            )
        )
        if (
            row is None
            or row.request["project_id"] != claims["project_id"]
            or row.request["connection_name"] != claims["connection_name"]
            or row.request["branch"] != claims.get("branch")
        ):
            raise jwt.InvalidTokenError("Agent run is no longer active")
    return claims
