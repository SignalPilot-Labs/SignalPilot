"""Full-fidelity pass: GENUINE Clerk-signed tokens against the REAL Clerk JWKS.

The synthetic-JWKS suite controls every claim but signs with a key of our own. This
module removes that last caveat for the happy paths: the gateway runs with the real
CLERK_PUBLISHABLE_KEY, derives the real issuer and JWKS URL, fetches Clerk's real
signing keys over the internet, and verifies tokens minted by Clerk itself through
POST /v1/sessions -> POST /v1/sessions/{id}/tokens.

Throwaway resources (2 users, 1 organization, 2 sessions) are created and deleted by
the `real_clerk` fixture. Nothing pre-existing is modified.

Skips cleanly when the Clerk credentials or network are unavailable.
"""

from __future__ import annotations

import pytest

from .clerk_backend import decode_claims
from .conftest import call, default_body
from .routes import ADMIN_PROBE_SKIP, discover, is_staff_only

pytestmark = pytest.mark.e2e_cloud

ADMIN_ROUTES, _ = discover()

# The concrete pre-fix exploits, re-run with real tokens.
EXPLOIT_SURFACES = [
    ("POST", "/api/connections/export", {"include_credentials": True, "confirm": True}),
    ("POST", "/api/connections/import", {"connections": [], "version": 1}),
    ("POST", "/api/connections/e2e-nonexistent/clone", {"new_name": "e2e-real-clone"}),
    ("GET", "/api/audit/export", None),
    ("PUT", "/api/evals/config", {}),
    ("PUT", "/api/settings", {}),
    ("GET", "/api/byok/keys", None),
    ("GET", "/api/keys", None),
    ("POST", "/api/keys", {"name": "e2e-real-escalation", "scopes": ["admin"]}),
    ("GET", "/api/network/info", None),
]
EXPLOIT_IDS = [f"{m} {p}" for m, p, _ in EXPLOIT_SURFACES]


# ── ground truth about the tokens Clerk actually issues ───────────────────────


def test_real_admin_token_claim_shape(real_clerk):
    """Document and lock in the production claim shape."""
    claims = real_clerk.admin_claims
    assert claims["iss"].startswith("https://"), claims["iss"]
    assert "org_role" not in claims, (
        "a real Clerk token unexpectedly carried a flat org_role claim; "
        "the short-claim path may no longer be the only production path"
    )
    assert isinstance(claims.get("o"), dict), claims.keys()
    assert claims["o"]["rol"] == "admin", claims["o"]
    assert claims["o"]["id"] == real_clerk.org_id
    assert claims["org_id"] == real_clerk.org_id
    assert "azp" not in claims, "real token now carries azp - SP_EXPECTED_AZP config changes"


def test_real_member_token_claim_shape(real_clerk):
    """The non-privileged role key on this instance is org:member -> o.rol == "member"."""
    claims = real_clerk.member_claims
    assert "org_role" not in claims
    assert isinstance(claims.get("o"), dict), claims.keys()
    assert claims["o"]["rol"] != "admin", claims["o"]
    assert claims["o"]["id"] == real_clerk.org_id


def test_real_tokens_are_rs256_and_not_self_signed(real_clerk):
    import jwt as pyjwt

    for token in (real_clerk.admin_token, real_clerk.member_token):
        assert pyjwt.get_unverified_header(token)["alg"] == "RS256"
        assert decode_claims(token)["iss"] != "https://127.0.0.1"


# ── the matrix, with real tokens ──────────────────────────────────────────────


def test_real_admin_token_authenticates(real_client, real_clerk):
    r = call(real_client, "GET", "/api/connections", real_clerk.admin_token)
    assert r.status_code == 200, r.text


def test_real_member_token_authenticates(real_client, real_clerk):
    r = call(real_client, "GET", "/api/connections", real_clerk.member_token)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("route", ADMIN_ROUTES, ids=[r.id for r in ADMIN_ROUTES])
def test_real_member_is_forbidden_on_every_admin_route(real_client, real_clerk, route):
    r = call(real_client, route.method, route.url, real_clerk.member_token,
             default_body(route.method))
    assert r.status_code == 403, (
        f"AUTHORIZATION BYPASS WITH A REAL CLERK TOKEN: {route.id} (guards={route.guards}) "
        f"returned {r.status_code} for a genuine non-admin member. Body: {r.text[:400]}"
    )


_PROBEABLE = [
    r for r in ADMIN_ROUTES
    if (r.method, r.path) not in ADMIN_PROBE_SKIP and not is_staff_only(r.method, r.path)
]
_STAFF_ROUTES = [r for r in ADMIN_ROUTES if is_staff_only(r.method, r.path)]


@pytest.mark.parametrize("route", _PROBEABLE, ids=[r.id for r in _PROBEABLE])
def test_real_admin_is_not_locked_out(real_client, real_clerk, route):
    r = call(real_client, route.method, route.url, real_clerk.admin_token,
             default_body(route.method))
    assert r.status_code not in (401, 403), (
        f"ADMIN LOCKED OUT WITH A REAL CLERK TOKEN: {route.id} returned {r.status_code}. "
        f"Body: {r.text[:400]}"
    )


@pytest.mark.parametrize("route", _STAFF_ROUTES, ids=[r.id for r in _STAFF_ROUTES])
def test_real_admin_is_forbidden_on_staff_routes(real_client, real_clerk, route):
    """A genuine Clerk org admin is still only a tenant identity."""
    r = call(real_client, route.method, route.url, real_clerk.admin_token,
             default_body(route.method))
    assert r.status_code == 403, (
        f"TENANT ESCALATION WITH A REAL CLERK TOKEN: {route.id} returned {r.status_code}; "
        f"expected 403 (staff-only route). Body: {r.text[:400]}"
    )


@pytest.mark.parametrize("method,path,body", EXPLOIT_SURFACES, ids=EXPLOIT_IDS)
def test_real_member_denied_on_exploit_surfaces(real_client, real_clerk, method, path, body):
    from .test_exploits import assert_no_credential_material

    r = call(real_client, method, path, real_clerk.member_token, body)
    assert r.status_code == 403, (
        f"EXPLOIT REPRODUCED WITH A REAL CLERK TOKEN: {method} {path} returned "
        f"{r.status_code}. Body: {r.text[:400]}"
    )
    assert_no_credential_material(r.text)
    assert "raw_key" not in r.text


def test_real_member_export_leaked_nothing_and_changed_nothing(real_client, real_clerk):
    from .test_exploits import assert_no_credential_material

    denied = call(real_client, "POST", "/api/connections/export", real_clerk.member_token,
                  {"include_credentials": True, "confirm": True})
    assert denied.status_code == 403, denied.text
    assert_no_credential_material(denied.text)

    listed = call(real_client, "GET", "/api/connections", real_clerk.admin_token)
    assert listed.status_code == 200, listed.text
    names = [c.get("name") for c in listed.json()]
    assert "e2e-real-clone" not in names, names

    keys = call(real_client, "GET", "/api/keys", real_clerk.admin_token)
    assert keys.status_code == 200, keys.text
    assert not any(k.get("name") == "e2e-real-escalation" for k in keys.json())


def test_real_token_with_no_token_is_401(real_client):
    r = call(real_client, "GET", "/api/connections", None)
    assert r.status_code == 401, r.text


def test_real_gateway_rejects_a_self_signed_token(real_client, fake_clerk, real_clerk):
    """A token signed by our own key must not pass the real Clerk JWKS check.

    Guards against the harness accidentally proving something weaker than it claims.
    """
    forged = fake_clerk.mint(sub=real_clerk.admin_user_id, org_id=real_clerk.org_id,
                             org_role="admin", claim_style="short",
                             issuer=decode_claims(real_clerk.admin_token)["iss"])
    r = call(real_client, "GET", "/api/keys", forged)
    assert r.status_code in (401, 503), (
        f"a self-signed token was accepted by the real-Clerk gateway: {r.status_code} {r.text[:300]}"
    )
