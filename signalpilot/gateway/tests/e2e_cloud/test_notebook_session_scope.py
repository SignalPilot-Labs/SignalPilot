"""Notebook-session (pod callback) JWTs must never reach org administration.

`require_scopes` case 4 intersects the token's own `scopes` claim against a hard
allowlist of read/write/query/execute, so a compromised notebook pod cannot mint
itself an admin token. This is the one auth path where the *caller* supplies the
scope list, which makes it the most attractive escalation target in the system.

Tokens here are minted with the same HS256 secret the gateway under test was booted
with, so `verify_session_jwt` accepts them as genuine — only the `scopes` claim is
adversarial.
"""

from __future__ import annotations

import time

import jwt
import pytest

from .conftest import ORG_ID, call
from .routes import ADMIN_PROBE_SKIP, discover

pytestmark = pytest.mark.e2e_cloud

NOTEBOOK_SESSION_ISS = "signalpilot-notebook-session"
NOTEBOOK_SESSION_AUD = "signalpilot-gateway"

ADMIN_ROUTES, _ = discover()
# Routes gated purely by RequireScope("admin"): these are the ones the scopes claim
# could plausibly satisfy, so they are the meaningful targets.
SCOPE_GATED = [r for r in ADMIN_ROUTES
               if 'RequireScope("admin")' in r.guards
               and (r.method, r.path) not in ADMIN_PROBE_SKIP]


def mint_notebook_jwt(secret: str, scopes: list[str], *, org_id: str = ORG_ID,
                      user_id: str = "user_pod", ttl: int = 900) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": NOTEBOOK_SESSION_ISS,
            "aud": NOTEBOOK_SESSION_AUD,
            "sub": user_id,
            "org_id": org_id,
            "session_id": "sess_e2e_pod",
            "project_id": "",
            "branch": "main",
            "scopes": scopes,
            "iat": now,
            "exp": now + ttl,
        },
        secret,
        algorithm="HS256",
    )


@pytest.fixture(scope="module")
def honest_pod_token(gateway) -> str:
    return mint_notebook_jwt(gateway.session_jwt_secret, ["read", "write", "query", "execute"])


@pytest.fixture(scope="module")
def greedy_pod_token(gateway) -> str:
    """A pod token that ASKS for admin. The gateway must refuse to grant it."""
    return mint_notebook_jwt(gateway.session_jwt_secret,
                             ["read", "write", "query", "execute", "admin"])


def test_honest_pod_token_authenticates(client, honest_pod_token):
    """Baseline: the token is genuinely valid, so the denials below are about scope."""
    r = call(client, "GET", "/api/connections", honest_pod_token)
    assert r.status_code == 200, r.text


def test_pod_token_signed_with_wrong_secret_is_401(client):
    r = call(client, "GET", "/api/connections", mint_notebook_jwt("not-the-secret", ["read"]))
    assert r.status_code == 401, r.text


@pytest.mark.parametrize("route", SCOPE_GATED, ids=[r.id for r in SCOPE_GATED])
def test_greedy_pod_token_cannot_escalate(client, greedy_pod_token, route):
    from .conftest import default_body

    r = call(client, route.method, route.url, greedy_pod_token, default_body(route.method))
    assert r.status_code == 403, (
        f"NOTEBOOK POD PRIVILEGE ESCALATION: {route.id} returned {r.status_code} for a "
        f'notebook-session token claiming scopes=[..., "admin"]; expected 403. '
        f"Body: {r.text[:400]}"
    )


def test_greedy_pod_token_cannot_export_credentials(client, greedy_pod_token):
    from .test_exploits import assert_no_credential_material

    r = call(client, "POST", "/api/connections/export", greedy_pod_token,
             {"include_credentials": True, "confirm": True})
    assert r.status_code == 403, (
        f"NOTEBOOK POD CREDENTIAL EXFILTRATION: got {r.status_code}. Body: {r.text[:400]}"
    )
    assert_no_credential_material(r.text)


def test_greedy_pod_token_cannot_mint_api_keys(client, greedy_pod_token):
    r = call(client, "POST", "/api/keys", greedy_pod_token,
             {"name": "e2e-pod-escalation", "scopes": ["admin"]})
    assert r.status_code == 403, r.text
    assert "raw_key" not in r.text


def test_honest_pod_token_is_also_denied_admin(client, honest_pod_token):
    r = call(client, "GET", "/api/keys", honest_pod_token)
    assert r.status_code == 403, r.text
