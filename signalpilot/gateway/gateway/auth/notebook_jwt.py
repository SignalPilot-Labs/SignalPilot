"""Notebook session JWT minting and verification.

Provides:
- mint_session_jwt(user_id, org_id, session_id, project_id, branch, ttl) -> str
- verify_session_jwt(token) -> dict

Uses HS256 with the secret loaded from auth/jwt_secret.py.
Fixed iss="signalpilot-notebook-session", aud="signalpilot-gateway".
Raises NotebookSessionJWTError on any verification failure.
"""

from __future__ import annotations

import logging
import time

import jwt

from .jwt_secret import load_session_jwt_secret

logger = logging.getLogger(__name__)

NOTEBOOK_SESSION_ISS = "signalpilot-notebook-session"
NOTEBOOK_SESSION_AUD = "signalpilot-gateway"

_REQUIRED_CLAIMS = {"sub", "org_id", "session_id", "iss", "aud", "exp", "iat", "scopes"}

# Scopes granted to notebook session JWTs — read/write only; no admin, no billing.
NOTEBOOK_SESSION_SCOPES: list[str] = ["read", "write"]


class NotebookSessionJWTError(Exception):
    """Raised on any notebook session JWT verification failure."""


def mint_session_jwt(
    *,
    user_id: str,
    org_id: str,
    session_id: str,
    project_id: str | None,
    branch: str,
    ttl: int,
) -> str:
    """Mint a signed HS256 JWT for a notebook session.

    Args:
        user_id: The user who owns the session.
        org_id: The org who owns the session.
        session_id: The DB row id for this session.
        project_id: Associated project id (may be None).
        branch: Associated branch name.
        ttl: Token lifetime in seconds.

    Returns:
        Signed JWT string.
    """
    secret = load_session_jwt_secret()
    now = int(time.time())
    payload: dict = {
        "iss": NOTEBOOK_SESSION_ISS,
        "aud": NOTEBOOK_SESSION_AUD,
        "sub": user_id,
        "org_id": org_id,
        "session_id": session_id,
        "project_id": project_id or "",
        "branch": branch,
        "scopes": NOTEBOOK_SESSION_SCOPES,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_session_jwt(token: str) -> dict:
    """Verify and decode a notebook session JWT.

    Returns the decoded payload dict on success.
    Raises NotebookSessionJWTError on any failure (wrong iss, aud, expired, bad sig,
    malformed, missing required claim).
    """
    secret = load_session_jwt_secret()
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=NOTEBOOK_SESSION_AUD,
            issuer=NOTEBOOK_SESSION_ISS,
            options={"require": list(_REQUIRED_CLAIMS)},
        )
    except jwt.ExpiredSignatureError as e:
        raise NotebookSessionJWTError("Token expired") from e
    except jwt.InvalidAudienceError as e:
        raise NotebookSessionJWTError("Invalid audience") from e
    except jwt.InvalidIssuerError as e:
        raise NotebookSessionJWTError("Invalid issuer") from e
    except jwt.InvalidSignatureError as e:
        raise NotebookSessionJWTError("Invalid signature") from e
    except jwt.MissingRequiredClaimError as e:
        raise NotebookSessionJWTError(f"Missing required claim: {e}") from e
    except jwt.DecodeError as e:
        raise NotebookSessionJWTError(f"Malformed token: {e}") from e
    except jwt.InvalidTokenError as e:
        raise NotebookSessionJWTError(f"Invalid token: {e}") from e

    # Verify required custom claims are present and non-empty
    for claim in ("sub", "org_id", "session_id"):
        if not claims.get(claim):
            raise NotebookSessionJWTError(f"Required claim '{claim}' is missing or empty")

    # Verify scopes claim is a non-empty list of strings
    scopes = claims.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        raise NotebookSessionJWTError("Required claim 'scopes' is missing or not a list")

    return claims
