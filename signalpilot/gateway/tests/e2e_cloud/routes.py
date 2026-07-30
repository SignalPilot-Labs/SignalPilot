"""Discover the admin-gated route surface by introspecting the real dependency tree.

The matrix is not hand-maintained: it is derived from the FastAPI app itself, so a
newly added ``RequireScope("admin")`` / ``OrgAdmin`` route is automatically covered
and a route that *loses* its guard shows up as a matrix failure instead of silently
disappearing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Placeholder values substituted into path parameters. Deliberately non-existent so
# an authorized (admin) call lands on a 404/422 rather than mutating anything.
PATH_PARAM_VALUE = "e2e-nonexistent"

# Routes we refuse to drive even as admin because a *successful* call reaches out to
# the network or spawns work. They are still asserted for the basic_member 403 case;
# only the "admin must not be 403" probe is skipped.
ADMIN_PROBE_SKIP: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/demo/connector"),  # provisions a real Xata branch
        ("POST", "/api/github/bot/scan"),  # calls the GitHub API
        ("POST", "/api/evals/runs"),  # can launch an eval runner
        # Deliberately stricter than OrgAdmin: security.py::_require_admin additionally
        # requires the caller's user_id to be listed in SP_ADMIN_USER_IDS (a
        # deployment-operator allowlist, default {"local"}). An org admin who is not a
        # platform operator is *correctly* 403 here, so the "admin is not locked out"
        # probe does not apply. The basic_member 403 case is still asserted.
        ("GET", "/api/security/status"),
    }
)

# Non-authorization reasons a route may legitimately answer 403. Used to distinguish
# a real authorization denial from an unrelated policy denial.
NON_AUTHZ_403_MARKERS: tuple[str, ...] = (
    "not available on the free plan",
    "Upgrade to",
    "plan limit",
)

# Exact detail strings the authorization layer emits. Seeing any of these on a member
# route is a lockout regression; seeing none of them on an admin route is a bypass.
AUTHZ_DENIAL_DETAILS: tuple[str, ...] = (
    "Organization admin role required",
    "Insufficient scope",
    "Unknown authentication method",
    "Admin access required",
)


@dataclass(frozen=True)
class RouteSpec:
    method: str
    path: str
    guards: tuple[str, ...]
    name: str

    @property
    def url(self) -> str:
        out = self.path
        while "{" in out:
            head, _, rest = out.partition("{")
            _param, _, tail = rest.partition("}")
            out = head + PATH_PARAM_VALUE + tail
        return out

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"


def _scopes_of(call) -> tuple[str, ...] | None:
    """Extract the scope tuple captured by a RequireScope() closure, if any."""
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


def _collect() -> list[dict]:
    """Walk the live FastAPI dependency tree. Runs inside the cloud-mode child."""
    from fastapi.routing import APIRoute

    from gateway.auth.user import require_org_admin
    from gateway.main import app

    rows: list[dict] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        deps: list = []
        _flatten(route.dependant, deps, set())

        guards: set[str] = set()
        all_scopes: set[str] = set()
        for dep in deps:
            if dep.call is require_org_admin:
                guards.add("OrgAdmin")
            found = _scopes_of(dep.call)
            if found is not None:
                all_scopes |= set(found)
                if "admin" in found:
                    guards.add('RequireScope("admin")')

        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            rows.append({
                "method": method, "path": route.path, "name": route.name or "",
                "guards": sorted(guards), "scopes": sorted(all_scopes),
            })
    return rows


@lru_cache(maxsize=1)
def discover() -> tuple[list[RouteSpec], list[RouteSpec]]:
    """Return (admin_routes, non_admin_scoped_routes) as registered in CLOUD mode.

    Route registration is mode-dependent — gateway/api/__init__.py skips the files,
    projects and sandboxes routers in cloud mode — so discovery must run with
    SP_DEPLOYMENT_MODE=cloud or the matrix asks for routes that legitimately 404.

    Importing the app in cloud mode mutates process-global state (auth/user.py raises
    at import without CLERK_PUBLISHABLE_KEY, and caches a JWKS client), so this runs
    in a throwaway subprocess. The dummy publishable key is never used to fetch
    anything: _get_jwks_client only constructs the client at import time.
    """
    import base64
    import json
    import subprocess
    import sys

    dummy_domain = base64.b64encode(b"127.0.0.1:1$").decode().rstrip("=")
    env = dict(os.environ)
    env |= {
        "SP_DEPLOYMENT_MODE": "cloud",
        "CLERK_PUBLISHABLE_KEY": f"pk_test_{dummy_domain}",
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        "PYTHONIOENCODING": "utf-8",
        # Two collection-time callers used to race each other writing __pycache__ for
        # the gateway package, which surfaced as a spurious circular-import error.
        # discover() is lru_cached now, but keep bytecode writing off regardless.
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    script = (
        "import json,sys;"
        "from tests.e2e_cloud.routes import _collect;"
        "sys.stdout.write('@@'+json.dumps(_collect())+'@@')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).resolve().parents[2]),
        env=env, capture_output=True, text=True, timeout=180,
    )
    if "@@" not in proc.stdout:
        raise RuntimeError(
            "cloud-mode route discovery failed:\n"
            f"stdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
        )
    rows = json.loads(proc.stdout.split("@@")[1])

    admin: list[RouteSpec] = []
    scoped: list[RouteSpec] = []
    for row in rows:
        spec = RouteSpec(row["method"], row["path"], tuple(row["guards"]), row["name"])
        if row["guards"]:
            admin.append(spec)
        elif row["scopes"]:
            scoped.append(spec)
    return admin, scoped


# A curated subset of ordinary member routes. A false-positive lockout (member
# regressed to 403) is as serious as a bypass, so these are asserted explicitly
# rather than sampled from discovery.
MEMBER_ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/api/connections"),
    ("GET", "/api/connections/health"),
    ("GET", "/api/connections/stats"),
    ("GET", "/api/plan"),
    ("GET", "/api/knowledge"),
    ("GET", "/api/reports"),
    ("GET", "/api/chat/conversations"),
    ("GET", "/api/workspace-projects"),
    ("GET", "/api/notebook-sessions"),
    ("GET", "/api/cache/stats"),
    ("GET", "/api/pool/stats"),
    ("GET", "/api/schema-cache/stats"),
    ("GET", "/api/connectors/capabilities"),
    ("GET", "/api/user/secrets"),
    ("GET", "/api/agent-runs"),
    ("GET", "/api/integrations/notion"),
    ("GET", "/api/schema-watches"),
    ("POST", "/api/connections/parse-url"),
    ("POST", "/api/cache/invalidate"),
    ("POST", "/api/schema-cache/invalidate"),
)
