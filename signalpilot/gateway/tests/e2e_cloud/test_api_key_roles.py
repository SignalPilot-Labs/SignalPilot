"""The second half of the fix: an API key cannot outrank the scopes it was issued with.

Before the fix, resolve_org_role() returned "admin" for ANY api_key regardless of its
scopes, so a read-only key satisfied every OrgAdmin dependency. Keys here are minted
through the real POST /api/keys endpoint using an admin JWT, then replayed as Bearer
credentials against admin routes.
"""

from __future__ import annotations

import secrets

import pytest

from .conftest import call

pytestmark = pytest.mark.e2e_cloud

# Routes guarded by OrgAdmin (role) and/or RequireScope("admin") (key scope).
# Both halves must deny a write-only key.
ADMIN_ROUTES_FOR_KEYS = [
    ("GET", "/api/keys", None),                 # RequireScope("admin") only
    ("GET", "/api/security/status", None),      # OrgAdmin only
    ("GET", "/api/settings", None),             # RequireScope("admin")
    ("PUT", "/api/settings", {}),               # OrgAdmin + RequireScope("admin")
    ("GET", "/api/byok/keys", None),            # OrgAdmin + RequireScope("admin")
    ("POST", "/api/connections/export", {"include_credentials": True, "confirm": True}),  # OrgAdmin
    ("GET", "/api/audit/export", None),         # RequireScope("admin")
]
ROUTE_IDS = [f"{m} {p}" for m, p, _ in ADMIN_ROUTES_FOR_KEYS]

# /api/security/status layers a second, stricter check on top of OrgAdmin: the caller's
# user_id must appear in SP_ADMIN_USER_IDS (platform-operator allowlist). No org admin
# and no API key satisfies that in this harness, so it is asserted only on the deny side.
ALLOW_ROUTES = [r for r in ADMIN_ROUTES_FOR_KEYS if r[1] != "/api/security/status"]
ALLOW_IDS = [f"{m} {p}" for m, p, _ in ALLOW_ROUTES]


def _mint_key(client, admin_token: str, scopes: list[str]) -> str:
    name = f"e2e-{'-'.join(scopes)}-{secrets.token_hex(4)}"
    r = call(client, "POST", "/api/keys", admin_token, {"name": name, "scopes": scopes})
    assert r.status_code in (200, 201), f"could not mint key with scopes={scopes}: {r.text[:400]}"
    raw = r.json()["raw_key"]
    assert raw.startswith("sp_")
    return raw


@pytest.fixture(scope="module")
def write_only_key(client, clerk_shaped_admin_token) -> str:
    return _mint_key(client, clerk_shaped_admin_token, ["read", "query", "write"])


@pytest.fixture(scope="module")
def admin_scoped_key(client, clerk_shaped_admin_token) -> str:
    return _mint_key(client, clerk_shaped_admin_token, ["read", "query", "write", "admin"])


def test_write_only_key_can_read(client, write_only_key):
    """Baseline: the key authenticates and its non-admin scopes work."""
    r = call(client, "GET", "/api/connections", write_only_key)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES_FOR_KEYS, ids=ROUTE_IDS)
def test_write_only_key_denied_on_admin_routes(client, write_only_key, method, path, body):
    r = call(client, method, path, write_only_key, body)
    assert r.status_code == 403, (
        f"API-KEY PRIVILEGE ESCALATION: a key WITHOUT the admin scope got {r.status_code} "
        f"on {method} {path}; expected 403. Body: {r.text[:400]}"
    )


@pytest.mark.parametrize("method,path,body", ALLOW_ROUTES, ids=ALLOW_IDS)
def test_admin_scoped_key_allowed_on_admin_routes(client, admin_scoped_key, method, path, body):
    r = call(client, method, path, admin_scoped_key, body)
    assert r.status_code not in (401, 403), (
        f"ADMIN KEY LOCKED OUT: an admin-scoped key got {r.status_code} on {method} {path}. "
        f"Body: {r.text[:400]}"
    )


def test_read_only_key_cannot_write(client, clerk_shaped_admin_token):
    """Non-admin scope enforcement is also still live for ordinary write routes."""
    read_key = _mint_key(client, clerk_shaped_admin_token, ["read"])
    r = call(client, "POST", "/api/cache/invalidate", read_key, {})
    assert r.status_code == 403, r.text


def test_unknown_sp_key_is_rejected(client):
    """An sp_-prefixed token that matches no stored key must not authenticate."""
    r = call(client, "GET", "/api/connections", "sp_" + secrets.token_hex(16))
    assert r.status_code in (401, 403), r.text
    # Documented behaviour: APIKeyAuthMiddleware answers 403 "Invalid API key." before
    # gateway/auth/user.py's cloud-mode sp_ rejection (401) can be reached over HTTP.
    assert r.status_code == 403, (
        f"expected the middleware's 403 for an unknown sp_ key, got {r.status_code}"
    )


def test_deleted_key_stops_working(client, clerk_shaped_admin_token):
    name_key = _mint_key(client, clerk_shaped_admin_token, ["read", "admin"])
    ok = call(client, "GET", "/api/keys", name_key)
    assert ok.status_code == 200, ok.text
    key_id = next(k["id"] for k in ok.json()
                  if k["prefix"] == name_key[:11])
    deleted = call(client, "DELETE", f"/api/keys/{key_id}", clerk_shaped_admin_token)
    assert deleted.status_code in (200, 204), deleted.text
    after = call(client, "GET", "/api/keys", name_key)
    assert after.status_code in (401, 403), after.text
