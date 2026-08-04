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
        ("POST", "/api/evals/runs/{run_id}/cancel"),
    }
)

# Routes that require a PLATFORM-STAFF identity (user_id in SP_ADMIN_USER_IDS, a
# deployment-operator allowlist defaulting to {"local"}) on top of the org-admin
# role. A tenant org admin is *correctly* refused on these, so the matrix asserts
# the refusal rather than the "admin is not locked out" probe, and asserts a staff
# identity gets through.
STAFF_ONLY_PATH_PREFIXES: tuple[str, ...] = (
    "/api/evals/",
)
STAFF_ONLY_ROUTES: frozenset[tuple[str, str]] = frozenset({("GET", "/api/security/status")})

# Sub claim of the staff token; matches SP_ADMIN_USER_IDS on the booted gateway.
STAFF_USER_ID = "user_staff"


def is_staff_only(method: str, path: str) -> bool:
    return (method, path) in STAFF_ONLY_ROUTES or path.startswith(STAFF_ONLY_PATH_PREFIXES)

# These markers identify policy-based status 403 responses.
# They distinguish policy denials from authorization denials.
NON_AUTHZ_403_MARKERS: tuple[str, ...] = (
    "not available on the free plan",
    "Upgrade to",
    "plan limit",
# The test gateway has an empty SP_EVAL_ALLOWED_ORGS allowlist.
# This policy denial does not indicate an authorization failure.
    "Evals are not enabled for this workspace.",
)

# Exact detail strings the authorization layer emits. Seeing any of these on a member
# route is a lockout regression; seeing none of them on an admin route is a bypass.
AUTHZ_DENIAL_DETAILS: tuple[str, ...] = (
    "Organization admin role required",
    "Insufficient scope",
    "Unknown authentication method",
    "Admin access required",
    "Platform staff access required",
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

    from gateway.api.deps import require_platform_staff
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
            if dep.call is require_platform_staff:
                guards.add("PlatformStaff")
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
    """Return admin and non-admin routes registered in cloud mode.

    Cloud mode does not register the files, projects, or sandboxes routers.
    Discovery uses SP_DEPLOYMENT_MODE=cloud to match the deployed route set.

    A subprocess isolates the process state that app import creates. The dummy
    publishable key constructs the JWKS client without a network request.
    """
    import base64
    import json
    import subprocess
    import sys

    dummy_domain = base64.b64encode(b"127.0.0.1:1$").decode().rstrip("=")
    env = dict(os.environ)
    env |= {
        "SP_DEPLOYMENT_MODE": "cloud",
        # Cloud K8s settings are validated when the module is imported, even
        # though discovery never launches a pod. Digest-pinned by requirement.
        "SP_NOTEBOOK_IMAGE": "registry.invalid/notebook@sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "SP_PUBLIC_GATEWAY_URL": "https://gateway.invalid",
        "SP_NOTEBOOK_RUNTIME_CLASS": "gvisor",
        "CLERK_PUBLISHABLE_KEY": f"pk_test_{dummy_domain}",
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        "PYTHONIOENCODING": "utf-8",
        # Disable bytecode writes to prevent concurrent collection from sharing __pycache__.
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
