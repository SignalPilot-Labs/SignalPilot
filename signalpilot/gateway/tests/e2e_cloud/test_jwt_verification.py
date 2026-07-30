"""Prove the real Clerk JWT verification path rejects malformed/forged tokens.

Every assertion here traverses the genuine code path: PyJWKClient fetches the JWKS
over HTTPS, jwt.decode enforces RS256 + issuer + require(exp, iat, sub), and
gateway/auth/user.py checks azp. Nothing is monkeypatched.
"""

from __future__ import annotations

import pytest

from .conftest import ORG_ID, call

pytestmark = pytest.mark.e2e_cloud

# A cheap authenticated GET that any member may call — isolates *authentication*
# failures from authorization failures.
PROBE = ("GET", "/api/connections")
# An admin route, for the role-claim cases.
ADMIN_PROBE = ("GET", "/api/keys")


def test_health_is_public(client):
    assert client.get("/health").status_code == 200


def test_no_token_is_401(client):
    r = call(client, *PROBE)
    assert r.status_code == 401, r.text


def test_valid_member_token_authenticates(client, member_token):
    r = call(client, *PROBE, token=member_token)
    assert r.status_code not in (401, 403), r.text


def test_expired_token_is_401(client, gateway, azp):
    token = gateway.clerk.mint(org_id=ORG_ID, org_role="admin", azp=azp, exp_delta=-3600, iat_delta=-7200)
    r = call(client, *PROBE, token=token)
    assert r.status_code == 401, r.text


def test_bad_signature_is_401(client, gateway, azp):
    """Correct kid, wrong private key -> InvalidSignatureError -> 401."""
    token = gateway.clerk.mint(org_id=ORG_ID, org_role="admin", azp=azp, sign_with_impostor=True)
    r = call(client, *PROBE, token=token)
    assert r.status_code == 401, r.text


def test_wrong_issuer_is_401(client, gateway, azp):
    token = gateway.clerk.mint(org_id=ORG_ID, org_role="admin", azp=azp,
                               issuer="https://attacker.example.com")
    r = call(client, *PROBE, token=token)
    assert r.status_code == 401, r.text


def test_missing_sub_is_401(client, gateway, azp):
    token = gateway.clerk.mint(org_id=ORG_ID, org_role="admin", azp=azp, omit_sub=True)
    r = call(client, *PROBE, token=token)
    assert r.status_code == 401, r.text


def test_missing_exp_is_401(client, gateway, azp):
    token = gateway.clerk.mint(org_id=ORG_ID, org_role="admin", azp=azp, omit_exp=True)
    r = call(client, *PROBE, token=token)
    assert r.status_code == 401, r.text


def test_missing_iat_is_401(client, gateway, azp):
    token = gateway.clerk.mint(org_id=ORG_ID, org_role="admin", azp=azp, omit_iat=True)
    r = call(client, *PROBE, token=token)
    assert r.status_code == 401, r.text


def test_wrong_azp_is_401(client, gateway):
    """SP_EXPECTED_AZP is configured on this gateway, so a foreign azp must fail."""
    token = gateway.clerk.mint(org_id=ORG_ID, org_role="admin", azp="https://attacker.example.com")
    r = call(client, *PROBE, token=token)
    assert r.status_code == 401, r.text


def test_alg_none_is_401(client, gateway):
    import jwt as pyjwt

    token = pyjwt.encode({"sub": "x", "iss": gateway.clerk.issuer, "iat": 0, "exp": 9999999999},
                         key="", algorithm="none")
    r = call(client, *PROBE, token=token)
    assert r.status_code == 401, r.text


def test_garbage_token_is_401(client):
    r = call(client, *PROBE, token="not.a.jwt")
    assert r.status_code == 401, r.text


def test_missing_org_claim_is_403(client, gateway, azp):
    """No org context at all -> resolve_org_id raises 403 'Organization context required'."""
    token = gateway.clerk.mint(org_id=None, org_role="admin", azp=azp)
    r = call(client, *PROBE, token=token)
    assert r.status_code == 403, r.text


def test_no_role_claim_fails_closed_on_admin_route(client, no_role_token):
    """Valid signature + org, but zero role claims: must NOT be treated as admin."""
    r = call(client, *ADMIN_PROBE, token=no_role_token)
    assert r.status_code == 403, r.text
