"""Every registered route has a decided role class, and the guards agree with it.

``tests/route_roles.json`` maps ``"METHOD PATH"`` to one of:

* ``admin``  - the route carries ``OrgAdmin`` or ``RequireScope("admin")``;
* ``member`` - any authenticated org member may call it (org-level reads,
  governed queries, proposals, personal key minting);
* ``owner``  - the handler applies an ownership rule (the creator, with
  admins allowed) on top of authentication;
* ``public`` - no gateway authentication dependency at all (health, OAuth
  metadata, webhooks, callbacks, single-use download tokens).

The test walks the live app, derives what it can from the dependency tree
(admin guard present, authentication present) and checks that against the
manifest. A route missing from the manifest fails with the line to add; a
manifest entry for a route that no longer exists fails too, so the file is
always exactly the route table. Owner versus member cannot be derived and is
the author's decision, recorded in the manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

MANIFEST_PATH = Path(__file__).parent / "route_roles.json"
CLASSES = frozenset({"admin", "member", "owner", "public"})

# Routes that authenticate inside the handler (git smart HTTP, the notebook
# proxy) rather than through a FastAPI dependency. They are the only non-public
# classes allowed without an authentication dependency.
SELF_AUTH_PREFIXES: tuple[str, ...] = ("/git/", "/notebook/")


def _scopes_of(call) -> tuple[str, ...] | None:
    """The scope tuple captured by a RequireScope() closure, if ``call`` is one."""
    if "RequireScope" not in getattr(call, "__qualname__", ""):
        return None
    for cell in getattr(call, "__closure__", None) or ():
        try:
            value = cell.cell_contents
        except ValueError:  # pragma: no cover - empty cell
            continue
        if isinstance(value, tuple) and all(isinstance(x, str) for x in value):
            return value
    return ()


def _flatten(dependant, out: list, seen: set[int]) -> None:
    for sub in dependant.dependencies:
        if id(sub) in seen:
            continue
        seen.add(id(sub))
        out.append(sub)
        _flatten(sub, out, seen)


def derive_routes() -> dict[str, dict[str, bool]]:
    """``{"METHOD PATH": {"admin": bool, "authenticated": bool}}`` for the live app."""
    from gateway.auth.user import require_org_admin, resolve_user_id
    from gateway.main import app
    from gateway.security.scope_guard import _resolve_user_id as guard_user_id

    rows: dict[str, dict[str, bool]] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        deps: list = []
        _flatten(route.dependant, deps, set())
        calls = [dep.call for dep in deps]
        admin = any(call is require_org_admin for call in calls) or any(
            "admin" in (_scopes_of(call) or ()) for call in calls
        )
        authenticated = any(call in (resolve_user_id, guard_user_id) for call in calls) or any(
            _scopes_of(call) is not None for call in calls
        )
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            rows[f"{method} {route.path}"] = {"admin": admin, "authenticated": authenticated}
    return rows


def load_manifest() -> dict[str, str]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def derived() -> dict[str, dict[str, bool]]:
    return derive_routes()


@pytest.fixture(scope="module")
def manifest() -> dict[str, str]:
    return load_manifest()


def test_manifest_values_are_known_classes(manifest):
    bad = {key: value for key, value in manifest.items() if value not in CLASSES}
    assert not bad, f"unknown role classes in route_roles.json: {bad}"


def test_every_route_is_classified(derived, manifest):
    missing = sorted(set(derived) - set(manifest))
    assert not missing, (
        "Routes without a role decision. Add each to tests/route_roles.json as "
        '"METHOD PATH": "admin" | "member" | "owner" | "public" after deciding who may call it:\n'
        + "\n".join(f'  "{key}": "{"admin" if derived[key]["admin"] else "member"}",' for key in missing)
    )


def test_manifest_has_no_stale_routes(derived, manifest):
    stale = sorted(set(manifest) - set(derived))
    assert not stale, f"route_roles.json lists routes that no longer exist: {stale}"


def test_admin_class_matches_the_admin_guard(derived, manifest):
    """``admin`` exactly when the dependency tree carries an admin guard."""
    wrong = {
        key: ("admin" if facts["admin"] else "not admin")
        for key, facts in derived.items()
        if key in manifest and (manifest[key] == "admin") != facts["admin"]
    }
    assert not wrong, (
        "Manifest class disagrees with the route's guards (guard says -> ...): "
        f"{wrong}. Either add/remove OrgAdmin on the route or fix the manifest."
    )


def test_public_class_means_no_authentication_dependency(derived, manifest):
    wrong = [key for key, cls in manifest.items() if cls == "public" and derived.get(key, {}).get("authenticated")]
    assert not wrong, f"Classified public but carries an authentication dependency: {wrong}"


def test_authenticated_classes_carry_an_authentication_dependency(derived, manifest):
    wrong = [
        key
        for key, cls in manifest.items()
        if cls in {"member", "owner"}
        and key in derived
        and not derived[key]["authenticated"]
        and not key.split(" ", 1)[1].startswith(SELF_AUTH_PREFIXES)
    ]
    assert not wrong, (
        f"Classified member/owner but nothing authenticates the caller: {wrong}. "
        "Add RequireScope/UserID, or list the prefix in SELF_AUTH_PREFIXES with a reason."
    )


def test_manifest_covers_the_decided_surface(manifest):
    """Spot-check the routes the admin/member plan decided on."""
    expected = {
        "PUT /api/org/secrets": "admin",
        "POST /api/connections/test-credentials": "admin",
        "GET /api/audit": "admin",
        "GET /api/audit/stats": "admin",
        "GET /api/github/install-url": "admin",
        "POST /api/github/import": "admin",
        "POST /api/workspace-projects": "admin",
        "PUT /api/connections/{name}/schema/endorsements": "admin",
        "PUT /api/connections/{name}/pii": "admin",
        "PUT /api/chat/default-project": "admin",
        "POST /api/budget": "admin",
        "POST /api/evals/upload/initiate": "admin",
        "GET /api/keys": "member",
        "POST /api/keys": "member",
        "DELETE /api/keys/{key_id}": "owner",
        "POST /api/knowledge": "member",
        "PUT /api/knowledge/{doc_id}": "admin",
        "GET /api/me": "member",
        "POST /api/chat/reports/{report_id}/versions": "owner",
        "POST /api/chat/report-versions/{version_id}/share": "owner",
        "DELETE /api/connections/{name}/xata/projects/{project}/branches/{branch}": "owner",
        "PUT /api/workspace-projects/{project_id}/files/{path:path}": "member",
    }
    wrong = {key: (manifest.get(key), cls) for key, cls in expected.items() if manifest.get(key) != cls}
    assert not wrong, f"(actual, expected): {wrong}"
