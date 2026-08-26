"""Prove the export endpoint is a REAL exfiltration primitive, then prove it is shut.

The other exploit tests assert a 403 on an empty database, which cannot distinguish
"the guard held" from "there was nothing to leak". This module seeds a connection
carrying an actual password, confirms an org admin's export DOES return that secret
material, and only then confirms every lesser caller is denied and receives nothing.

If the admin export ever stops returning the password, this module fails loudly —
because at that point the negative assertions below would be proving nothing.
"""

from __future__ import annotations

import secrets

import pytest

from .conftest import call
from .test_exploits import assert_no_credential_material

pytestmark = pytest.mark.e2e_cloud

CONN_NAME = "e2e-exfil-target"
EXPORT_WITH_CREDS = {"include_credentials": True, "confirm": True}


@pytest.fixture(scope="module")
def seeded_secret(client, clerk_shaped_admin_token) -> str:
    """Create a connection whose password is a value we can search response bodies for.

    The value is random and lives only in the throwaway sp_e2e_cloud database.
    """
    marker = "E2eExfilCanary" + secrets.token_hex(8)
    created = call(client, "POST", "/api/connections", clerk_shaped_admin_token, {
        "name": CONN_NAME,
        "db_type": "postgres",
        # Loopback is blocked unconditionally by the SSRF guard; the harness sets
        # SP_ALLOW_PRIVATE_CONNECTIONS so an unrouted RFC1918 address validates instead.
        "host": "10.255.255.1",
        "port": 5432,
        "database": "e2e",
        "username": "e2e_user",
        "password": marker,
        "description": "e2e exfiltration canary",
    })
    if created.status_code not in (200, 201):
        pytest.skip(f"could not seed a connection: {created.status_code} {created.text[:300]}")
    yield marker
    call(client, "DELETE", f"/api/connections/{CONN_NAME}", clerk_shaped_admin_token)


def test_admin_export_really_does_return_the_credential(client, clerk_shaped_admin_token,
                                                        seeded_secret):
    """Establishes that this endpoint is worth attacking. If this ever fails, the
    negative assertions in this module are vacuous and must be re-designed."""
    r = call(client, "POST", "/api/connections/export", clerk_shaped_admin_token,
             EXPORT_WITH_CREDS)
    assert r.status_code == 200, r.text
    assert CONN_NAME in r.text, "the seeded connection is missing from the admin export"
    assert seeded_secret in r.text, (
        "admin export no longer returns credential material - the exfiltration "
        "assertions below would no longer prove anything"
    )


@pytest.mark.parametrize("token_fixture", [
    "member_token",
    "clerk_shaped_member_token",
    "member_token_short_claim",
    "no_role_token",
])
def test_lesser_callers_get_nothing(client, request, seeded_secret, token_fixture):
    token = request.getfixturevalue(token_fixture)
    r = call(client, "POST", "/api/connections/export", token, EXPORT_WITH_CREDS)
    assert r.status_code == 403, (
        f"CREDENTIAL EXFILTRATION BYPASS ({token_fixture}): {r.status_code}. "
        f"Body: {r.text[:400]}"
    )
    assert seeded_secret not in r.text, f"CREDENTIAL LEAK to {token_fixture}"
    assert CONN_NAME not in r.text
    assert_no_credential_material(r.text)


def test_unauthenticated_gets_nothing(client, seeded_secret):
    r = call(client, "POST", "/api/connections/export", None, EXPORT_WITH_CREDS)
    assert r.status_code == 401, r.text
    assert seeded_secret not in r.text


def test_write_only_api_key_gets_nothing(client, clerk_shaped_admin_token, seeded_secret):
    """The inner require_scopes(request, "admin") guard on include_credentials."""
    minted = call(client, "POST", "/api/keys", clerk_shaped_admin_token,
                  {"name": f"e2e-exfil-{secrets.token_hex(4)}", "scopes": ["read", "write"]})
    assert minted.status_code in (200, 201), minted.text
    key = minted.json()["raw_key"]

    r = call(client, "POST", "/api/connections/export", key, EXPORT_WITH_CREDS)
    assert r.status_code == 403, (
        f"CREDENTIAL EXFILTRATION BYPASS (write-only API key): {r.status_code}. "
        f"Body: {r.text[:400]}"
    )
    assert seeded_secret not in r.text


def test_greedy_notebook_pod_gets_nothing(client, gateway, seeded_secret):
    from .test_notebook_session_scope import mint_notebook_jwt

    token = mint_notebook_jwt(gateway.session_jwt_secret,
                              ["read", "write", "query", "execute", "admin"])
    r = call(client, "POST", "/api/connections/export", token, EXPORT_WITH_CREDS)
    assert r.status_code == 403, (
        f"CREDENTIAL EXFILTRATION BYPASS (notebook pod claiming admin): {r.status_code}. "
        f"Body: {r.text[:400]}"
    )
    assert seeded_secret not in r.text


def test_member_cannot_read_the_credential_through_the_crud_route(client, member_token,
                                                                 seeded_secret):
    """A member may list connections, but the password must never come back."""
    listed = call(client, "GET", "/api/connections", member_token)
    assert listed.status_code == 200, listed.text
    assert seeded_secret not in listed.text, (
        "CREDENTIAL LEAK: GET /api/connections returned the password to a member"
    )

    detail = call(client, "GET", f"/api/connections/{CONN_NAME}", member_token)
    assert seeded_secret not in detail.text, (
        "CREDENTIAL LEAK: connection detail returned the password to a member"
    )
