"""Decision 1 over real HTTP: members mint personal keys, scoped and owned per user.

member mints read/query/execute        -> 2xx, key works as a read credential
member mints write or admin            -> 403 "Organization admin role required"
member lists keys                      -> only their own
member revokes another member's key    -> 403 "You can only change resources you created"
admin lists keys                       -> sees the member's key; admin revokes it -> 204
"""

from __future__ import annotations

import secrets

import pytest

from .conftest import call

pytestmark = pytest.mark.e2e_cloud

OWNERSHIP_DENIAL = "You can only change resources you created"


def _mint(client, token: str, scopes: list[str]):
    name = f"e2e-member-{'-'.join(s.replace(':', '_') for s in scopes)}-{secrets.token_hex(4)}"
    return call(client, "POST", "/api/keys", token, {"name": name, "scopes": scopes})


@pytest.fixture(scope="module")
def member_key(client, clerk_shaped_member_token) -> dict:
    r = _mint(client, clerk_shaped_member_token, ["read", "query", "execute"])
    assert r.status_code in (200, 201), f"member could not mint a personal key: {r.text[:400]}"
    body = r.json()
    assert body["raw_key"].startswith("sp_")
    return body


def test_member_key_is_a_working_read_credential(client, member_key):
    r = call(client, "GET", "/api/connections", member_key["raw_key"])
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("scopes", [["read", "write"], ["read", "admin"], ["dbt_proxy"], ["agent:run"]])
def test_member_cannot_mint_elevated_scopes(client, clerk_shaped_member_token, scopes):
    r = _mint(client, clerk_shaped_member_token, scopes)
    assert r.status_code == 403, f"MEMBER ESCALATION: minted {scopes}: {r.status_code} {r.text[:400]}"
    assert r.json()["detail"] == "Organization admin role required"


def test_member_lists_only_their_own_keys(client, clerk_shaped_member_token, member_token, member_key):
    mine = call(client, "GET", "/api/keys", clerk_shaped_member_token)
    assert mine.status_code == 200, mine.text
    assert member_key["id"] in {k["id"] for k in mine.json()}

    someone_else = call(client, "GET", "/api/keys", member_token)
    assert someone_else.status_code == 200, someone_else.text
    assert member_key["id"] not in {k["id"] for k in someone_else.json()}


def test_other_member_cannot_revoke_the_key(client, member_token, member_key):
    r = call(client, "DELETE", f"/api/keys/{member_key['id']}", member_token)
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == OWNERSHIP_DENIAL


def test_admin_sees_and_revokes_the_members_key(client, clerk_shaped_admin_token, member_key):
    listed = call(client, "GET", "/api/keys", clerk_shaped_admin_token)
    assert listed.status_code == 200, listed.text
    assert member_key["id"] in {k["id"] for k in listed.json()}

    r = call(client, "DELETE", f"/api/keys/{member_key['id']}", clerk_shaped_admin_token)
    assert r.status_code == 204, r.text


def test_me_reports_the_member_role(client, clerk_shaped_member_token, clerk_shaped_admin_token):
    member = call(client, "GET", "/api/me", clerk_shaped_member_token)
    assert member.status_code == 200, member.text
    assert member.json()["role"] == "member"
    assert "keys.personal" in member.json()["permissions"]
    assert "keys.admin" not in member.json()["permissions"]

    admin = call(client, "GET", "/api/me", clerk_shaped_admin_token)
    assert admin.status_code == 200, admin.text
    assert admin.json()["role"] == "admin"
    assert "keys.admin" in admin.json()["permissions"]
