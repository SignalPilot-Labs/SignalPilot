"""The authorization matrix over every admin-gated route, driven over real HTTP.

Route list is discovered from the app's own dependency tree (see routes.py), so it
cannot drift out of sync with the code. For each route:

  basic_member JWT (dev claim form)      -> 403
  basic_member JWT (Clerk prod o.rol)    -> 403
  no role claim at all                   -> 403
  no token                               -> 401
  admin JWT (dev claim form)             -> NOT 401/403
  admin JWT (Clerk prod o.rol="admin")   -> NOT 401/403

Plan-gated routes (guard "BillablePlan") add one more axis: an admin of a FREE org
is refused with 402 ``plan_required``, and an admin of a billable org is never
refused with 401, 402 or 403. There is no platform-staff identity any more.
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
    plan_gated,
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
    # The plan-gate classification must not go vacuous: that would silently drop the
    # free-org assertions below.
    assert len(PLAN_GATED_ROUTES) >= 20, f"only {len(PLAN_GATED_ROUTES)} plan-gated routes discovered"
    gated_paths = {r.path for r in PLAN_GATED_ROUTES}
    for expected in ("/api/evals/config", "/api/security/status", "/api/workspace-projects",
                     "/api/chat/conversations", "/api/notebook-sessions"):
        assert expected in gated_paths, f"{expected} lost its plan gate"


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


PLAN_GATED_ROUTES = plan_gated()
_PLAN_GATED_IDS = [r.id for r in PLAN_GATED_ROUTES]

_PROBEABLE = [r for r in ADMIN_ROUTES if (r.method, r.path) not in ADMIN_PROBE_SKIP]
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


# Verify the plan gate: a free org is refused with 402, a billable org never is.


@pytest.mark.parametrize("route", PLAN_GATED_ROUTES, ids=_PLAN_GATED_IDS)
def test_free_org_admin_gets_402_on_plan_gated_routes(client, free_org_admin_token, route):
    """An org admin of a free org is refused by the plan gate, with a machine-readable body."""
    r = call(client, route.method, route.url, free_org_admin_token, default_body(route.method))
    assert r.status_code == 402, (
        f"PLAN GATE MISSING: {route.id} returned {r.status_code} for a free-org admin JWT; "
        f"expected 402. Body: {r.text[:400]}"
    )
    body = r.json()
    assert body.get("error") == "plan_required", body
    assert body.get("tier") == "free", body


@pytest.mark.parametrize("route", PLAN_GATED_ROUTES, ids=_PLAN_GATED_IDS)
def test_billable_org_admin_passes_the_plan_gate(client, admin_token, route):
    """A billable org's admin is never refused by the plan gate.

    Other errors are valid because the test uses placeholder identifiers and
    empty request bodies; ``ADMIN_PROBE_SKIP`` routes are still asserted here
    because a 402 is decided before any work is spawned.
    """
    r = call(client, route.method, route.url, admin_token, default_body(route.method))
    assert r.status_code not in (401, 402, 403), (
        f"BILLABLE ORG LOCKED OUT: {route.id} returned {r.status_code} for an org-admin JWT "
        f"of a billable org. Body: {r.text[:400]}"
    )


def test_evals_availability_is_readable_by_a_free_org(client, free_org_admin_token, admin_token):
    """The probe is not plan-gated and reports billable and capable separately."""
    free = call(client, "GET", "/api/evals/availability", free_org_admin_token)
    assert free.status_code == 200, free.text
    assert free.json()["billable"] is False
    assert free.json()["enabled"] is False
    assert set(free.json()) == {"billable", "capable", "enabled"}

    billable = call(client, "GET", "/api/evals/availability", admin_token)
    assert billable.status_code == 200, billable.text
    assert billable.json()["billable"] is True
    assert billable.json()["enabled"] is billable.json()["capable"]


def test_chat_bootstrap_carries_the_entitlement_for_every_org(client, free_org_admin_token, admin_token):
    for token, expected_billable in ((free_org_admin_token, False), (admin_token, True)):
        r = call(client, "GET", "/api/chat/bootstrap", token)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["entitlement"]["is_billable"] is expected_billable
        assert set(body["capabilities"]) == {"evals", "sandbox"}
        if not expected_billable:
            assert body["enabled"] is False
            assert not any(body["enterprise_features"].values())


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
