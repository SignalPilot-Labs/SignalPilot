"""The authorization matrix over every admin-gated route, driven over real HTTP.

Route list is discovered from the app's own dependency tree (see routes.py), so it
cannot drift out of sync with the code. For each route:

  basic_member JWT (dev claim form)      -> 403
  basic_member JWT (Clerk prod o.rol)    -> 403
  no role claim at all                   -> 403
  no token                               -> 401
  admin JWT (dev claim form)             -> NOT 401/403
  admin JWT (Clerk prod o.rol="admin")   -> NOT 401/403

Staff-only routes (see routes.is_staff_only) invert the last two: an org admin is a
tenant identity and must be REFUSED there; only a platform-staff identity gets in.
"""

from __future__ import annotations

import pytest

from .conftest import call, default_body
from .routes import (
    ADMIN_PROBE_SKIP,
    AUTHZ_DENIAL_DETAILS,
    MEMBER_ROUTES,
    NON_AUTHZ_403_MARKERS,
    discover,
    is_staff_only,
)

pytestmark = pytest.mark.e2e_cloud

ADMIN_ROUTES, SCOPED_ROUTES = discover()
IDS = [r.id for r in ADMIN_ROUTES]


def test_discovery_found_the_expected_surface():
    """Sanity gate: if discovery silently returns nothing the whole matrix is vacuous."""
    assert len(ADMIN_ROUTES) >= 40, f"only discovered {len(ADMIN_ROUTES)} admin routes"
    paths = {r.path for r in ADMIN_ROUTES}
    # Spot-check the concrete exploit routes are in the discovered set.
    for expected in ("/api/connections/export", "/api/connections/import",
                     "/api/connections/{name}/clone", "/api/audit/export",
                     "/api/evals/config", "/api/settings", "/api/keys",
                     "/api/byok/keys"):
        assert expected in paths, f"{expected} missing from discovered admin routes"
    # The staff classification must not go vacuous. that would silently drop the
    # tenant-escalation assertions below. The floor was 7 while the eval routes
    # carried RequirePlatformStaff; they are gated on the org allowlist now, so
    # the genuine staff-only surface is smaller. This still fails if the
    # classification collapses to nothing.
    assert len(STAFF_ROUTES) >= 3, f"only {len(STAFF_ROUTES)} staff-only routes discovered"


@pytest.mark.parametrize("route", ADMIN_ROUTES, ids=IDS)
def test_basic_member_is_forbidden(client, member_token, route):
    r = call(client, route.method, route.url, member_token, default_body(route.method))
    assert r.status_code == 403, (
        f"AUTHORIZATION BYPASS: {route.id} (guards={route.guards}) returned "
        f"{r.status_code} for a basic_member JWT; expected 403. Body: {r.text[:400]}"
    )


@pytest.mark.parametrize("route", ADMIN_ROUTES, ids=IDS)
def test_basic_member_short_claim_is_forbidden(client, clerk_shaped_member_token, route):
    """Same as above but with the real Clerk production claim shape (o.rol)."""
    r = call(client, route.method, route.url, clerk_shaped_member_token, default_body(route.method))
    assert r.status_code == 403, (
        f"AUTHORIZATION BYPASS (prod claim form): {route.id} returned {r.status_code} "
        f"for a basic_member token; expected 403. Body: {r.text[:400]}"
    )


@pytest.mark.parametrize("route", ADMIN_ROUTES, ids=IDS)
def test_no_role_claim_is_forbidden(client, no_role_token, route):
    r = call(client, route.method, route.url, no_role_token, default_body(route.method))
    assert r.status_code == 403, (
        f"FAIL-OPEN ON MISSING ROLE: {route.id} returned {r.status_code} for a JWT with "
        f"no role claim; expected 403. Body: {r.text[:400]}"
    )


@pytest.mark.parametrize("route", ADMIN_ROUTES, ids=IDS)
def test_unauthenticated_is_401(client, route):
    r = call(client, route.method, route.url, None, default_body(route.method))
    assert r.status_code == 401, (
        f"UNAUTHENTICATED ACCESS: {route.id} returned {r.status_code} with no token; "
        f"expected 401. Body: {r.text[:400]}"
    )


STAFF_ROUTES = [r for r in ADMIN_ROUTES if is_staff_only(r.method, r.path)]
_STAFF_IDS = [r.id for r in STAFF_ROUTES]

_PROBEABLE = [
    r for r in ADMIN_ROUTES
    if (r.method, r.path) not in ADMIN_PROBE_SKIP and not is_staff_only(r.method, r.path)
]
_PROBE_IDS = [r.id for r in _PROBEABLE]


@pytest.mark.parametrize("route", _PROBEABLE, ids=_PROBE_IDS)
def test_admin_is_not_locked_out(client, admin_token, route):
    """Verify that an organization administrator passes the authorization check.

    Other errors are valid because the test uses placeholder identifiers and
    empty request bodies.
    """
    r = call(client, route.method, route.url, admin_token, default_body(route.method))
    assert r.status_code not in (401, 403), (
        f"ADMIN LOCKED OUT: {route.id} returned {r.status_code} for an org-admin JWT "
        f"(dev claim form). Body: {r.text[:400]}"
    )


@pytest.mark.parametrize("route", _PROBEABLE, ids=_PROBE_IDS)
def test_admin_short_claim_is_not_locked_out(client, clerk_shaped_admin_token, route):
    """The Clerk PRODUCTION path: o.rol == "admin", no flat org_role claim."""
    r = call(client, route.method, route.url, clerk_shaped_admin_token, default_body(route.method))
    assert r.status_code not in (401, 403), (
        f"ADMIN LOCKED OUT (prod claim form o.rol): {route.id} returned {r.status_code}. "
        f"Body: {r.text[:400]}"
    )


# Verify that organization administrators cannot access staff routes.

_STAFF_PROBEABLE = [r for r in STAFF_ROUTES if (r.method, r.path) not in ADMIN_PROBE_SKIP]
_STAFF_PROBE_IDS = [r.id for r in _STAFF_PROBEABLE]


@pytest.mark.parametrize("route", STAFF_ROUTES, ids=_STAFF_IDS)
def test_org_admin_is_forbidden_on_staff_routes(client, admin_token, route):
    """An org admin is a tenant identity. it must not reach platform-staff routes."""
    r = call(client, route.method, route.url, admin_token, default_body(route.method))
    assert r.status_code == 403, (
        f"TENANT ESCALATION: {route.id} returned {r.status_code} for an org-admin JWT; "
        f"expected 403 (staff-only route). Body: {r.text[:400]}"
    )


@pytest.mark.parametrize("route", STAFF_ROUTES, ids=_STAFF_IDS)
def test_org_admin_short_claim_is_forbidden_on_staff_routes(client, clerk_shaped_admin_token, route):
    r = call(client, route.method, route.url, clerk_shaped_admin_token, default_body(route.method))
    assert r.status_code == 403, (
        f"TENANT ESCALATION (prod claim form): {route.id} returned {r.status_code} for an "
        f"org-admin JWT; expected 403 (staff-only route). Body: {r.text[:400]}"
    )


@pytest.mark.parametrize("route", _STAFF_PROBEABLE, ids=_STAFF_PROBE_IDS)
def test_staff_identity_is_not_locked_out(client, staff_token, route):
    """Verify that a user in SP_ADMIN_USER_IDS passes authorization.

    Another policy can deny a staff-only route. The test accepts status 403
    only when the response identifies that policy and contains no authorization denial.
    """
    r = call(client, route.method, route.url, staff_token, default_body(route.method))
    assert r.status_code != 401, (
        f"STAFF LOCKED OUT: {route.id} returned 401 for a platform-staff JWT. "
        f"Body: {r.text[:400]}"
    )
    if r.status_code == 403:
        assert any(m in r.text for m in NON_AUTHZ_403_MARKERS), (
            f"STAFF LOCKED OUT: {route.id} returned an authorization 403 for a "
            f"platform-staff JWT. Body: {r.text[:400]}"
        )
    for denial in AUTHZ_DENIAL_DETAILS:
        assert denial not in r.text, (
            f"STAFF LOCKED OUT: {route.id} carries the authorization denial "
            f"{denial!r} for a platform-staff JWT. Body: {r.text[:400]}"
        )


def test_put_eval_config_requires_the_admin_scope():
    """Verify that evaluation repository selection requires the admin scope.

    PUT /api/evals/config appears in the admin matrix because it uses
    RequireScope("admin").
    """
    route = next(
        (r for r in ADMIN_ROUTES if r.id == "PUT /api/evals/config"), None
    )
    assert route is not None, "PUT /api/evals/config is no longer admin-gated"
    assert 'RequireScope("admin")' in route.guards, route.guards


def test_prefixed_admin_role_spelling_also_passes(client, admin_token_short_claim_prefixed):
    """Clerk's memberships API reports "org:admin"; both spellings must be accepted."""
    r = call(client, "GET", "/api/keys", admin_token_short_claim_prefixed)
    assert r.status_code not in (401, 403), r.text


# Verify member route access.


def _assert_not_authz_denial(r, label: str) -> None:
    """A member route may 403 for policy reasons (plan gating) but never for authz."""
    assert r.status_code != 401, f"MEMBER LOCKOUT REGRESSION ({label}): 401. Body: {r.text[:400]}"
    if r.status_code == 403:
        assert any(m in r.text for m in NON_AUTHZ_403_MARKERS), (
            f"MEMBER LOCKOUT REGRESSION ({label}): 403 from the authorization layer. "
            f"Body: {r.text[:400]}"
        )
    for denial in AUTHZ_DENIAL_DETAILS:
        assert denial not in r.text, (
            f"MEMBER LOCKOUT REGRESSION ({label}): body carries the authorization "
            f"denial {denial!r}. Body: {r.text[:400]}"
        )


@pytest.mark.parametrize("method,path", MEMBER_ROUTES, ids=[f"{m} {p}" for m, p in MEMBER_ROUTES])
def test_ordinary_member_routes_did_not_regress(client, member_token, method, path):
    r = call(client, method, path, member_token, default_body(method))
    _assert_not_authz_denial(r, f"dev claim form, {method} {path}")


@pytest.mark.parametrize("method,path", MEMBER_ROUTES, ids=[f"{m} {p}" for m, p in MEMBER_ROUTES])
def test_ordinary_member_routes_work_with_prod_claims(client, clerk_shaped_member_token, method, path):
    r = call(client, method, path, clerk_shaped_member_token, default_body(method))
    _assert_not_authz_denial(r, f"prod claim form, {method} {path}")


@pytest.mark.parametrize("method,path", MEMBER_ROUTES, ids=[f"{m} {p}" for m, p in MEMBER_ROUTES])
def test_ordinary_member_routes_still_require_auth(client, method, path):
    r = call(client, method, path, None, default_body(method))
    assert r.status_code == 401, (
        f"UNAUTHENTICATED ACCESS: {method} {path} returned {r.status_code} with no token. "
        f"Body: {r.text[:400]}"
    )
