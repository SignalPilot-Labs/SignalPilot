"""End-to-end HTTP proof that the dbt and agent routers require auth.

Regression tests for the audit findings R2-1 (dbt router entirely
unauthenticated -> RCE) and R2-2 (agent router unauthenticated ->
agent-driven RCE). Both routers had no ``@requires`` decorator at all, so
``AuthBackend.authenticate()`` returning ``None`` produced an
``UnauthenticatedUser`` that Starlette does *not* reject -- every handler
was reachable by an anonymous caller.

These tests talk to a **real booted server over HTTP**, not to the app
object, because the bug being guarded against is a decorator that is
present in the source but does not actually enforce (Starlette's
``requires()`` locates the request by a parameter literally named
``request``; this codebase's custom ``APIRouter`` invokes handlers as
``func(request=request)``). Only a real status code proves enforcement.

Boot a throwaway instance -- do NOT point these at a shared/live server,
the authenticated cases write to the workspace:

    docker run -d --name sp-authtest -p 127.0.0.1:2799:2718 \
        signalpilot-notebook \
        sp edit --host 0.0.0.0 --port 2718 --headless \
        --token-password e2e-authtest-token --no-skew-protection /workspace

then:

    SP_E2E_BASE_URL=http://127.0.0.1:2799 \
    SP_E2E_TOKEN=e2e-authtest-token \
        pytest tests/_server/api/endpoints/test_dbt_agent_auth_e2e.py

``--no-skew-protection`` matters: ``SkewProtectionMiddleware`` 401s every
POST that lacks a valid ``Sp-Server-Token`` *before* routing, which would
mask the absence of authentication on the handlers. Disabling it isolates
the auth check (and mirrors the shipped container CMD, which also disables
skew protection).

Optionally, to cover the read->exec privilege escalation, boot a second
instance in RUN (read-only) mode and set ``SP_E2E_RUN_BASE_URL`` /
``SP_E2E_RUN_TOKEN``; a RUN-mode identity holds only the ``read`` scope and
must be rejected by these ``edit``-gated routes.
"""

from __future__ import annotations

import os
import uuid

import pytest

httpx = pytest.importorskip("httpx")

BASE_URL = (os.environ.get("SP_E2E_BASE_URL") or "").rstrip("/")
TOKEN = os.environ.get("SP_E2E_TOKEN") or ""
RUN_BASE_URL = (os.environ.get("SP_E2E_RUN_BASE_URL") or "").rstrip("/")
RUN_TOKEN = os.environ.get("SP_E2E_RUN_TOKEN") or ""

pytestmark = pytest.mark.skipif(
    not (BASE_URL and TOKEN),
    reason=(
        "set SP_E2E_BASE_URL and SP_E2E_TOKEN to a throwaway sp instance "
        "booted with --token-password and --no-skew-protection "
        "(see module docstring)"
    ),
)

# 401 (unauthenticated) or 403 (authenticated but wrong scope). Anything
# else means the request was let through to the handler. Note that
# ``_server/errors.py:handle_error`` rewrites 403 -> 401 ("turn 403s into
# 401s to collect auth"), so a scope rejection from ``requires()`` normally
# arrives as 401; both are accepted here so the tests survive that policy
# changing.
REJECT_STATUSES = (401, 403)

# Read-gated (``@requires("read")``) route used as a positive control in RUN
# mode: it proves the RUN-mode identity really is authenticated and holds
# ``read``, so a rejection on the dbt/agent routes is a *scope* rejection and
# not just a bad token.
READ_GATED_CONTROL = "/api/status/connections"

TIMEOUT = 60.0

# The scheme guard must answer before git is ever spawned, so these calls are
# expected to return in milliseconds. A short read timeout turns "the guard is
# missing and git is out on the network" into a fast, legible failure instead
# of a multi-minute stall.
CLONE_TIMEOUT = 20.0


# Every handler in endpoints/dbt.py (9) and endpoints/agent.py (8).
# Table-driven on purpose: a newly added handler that is not listed here is
# caught by test_route_inventory_is_fully_covered, and one that is listed but
# ungated is caught by test_unauthenticated_request_is_rejected.
#
# Bodies are deliberately inert (empty / invalid / already-blocked) so that
# the *authenticated* half of the suite does not mutate the workspace: the
# only assertion there is "not an auth rejection", so a 400/422/500 from a
# missing field is a pass.
DBT_ROUTES: list[tuple[str, str, dict[str, object] | None]] = [
    ("POST", "/api/dbt/command", {"command": "definitely-not-a-dbt-command"}),
    ("POST", "/api/dbt/project_info", {}),
    ("POST", "/api/dbt/models", {}),
    ("POST", "/api/dbt/artifact", {"artifact": "manifest"}),
    ("POST", "/api/dbt/discover_projects", {"rootDir": "/workspace"}),
    ("POST", "/api/dbt/scaffold_project", {}),
    ("POST", "/api/dbt/compile_model", {"modelName": ""}),
    ("POST", "/api/dbt/preview_model", {"modelName": ""}),
]

AGENT_ROUTES: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "/api/agent/auth-status", None),
    ("POST", "/api/agent/save-api-key", {}),
    ("POST", "/api/agent/create", {}),
    ("POST", "/api/agent/message", {}),
    ("POST", "/api/agent/stop", {}),
    ("POST", "/api/agent/status", {}),
    ("POST", "/api/agent/list", {}),
    ("POST", "/api/agent/events", {}),
]

EDIT_GATED_ROUTES = DBT_ROUTES + AGENT_ROUTES

ROUTE_IDS = [f"{method} {path}" for method, path, _ in EDIT_GATED_ROUTES]


def _request(
    method: str,
    path: str,
    body: dict[str, object] | None,
    *,
    token: str | None = None,
    base_url: str | None = None,
    timeout: float = TIMEOUT,
) -> httpx.Response:
    # A fresh client per call: a successful auth sets a session cookie, so a
    # shared cookie jar would silently authenticate the "anonymous" requests.
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = (base_url or BASE_URL) + path
    with httpx.Client(timeout=timeout) as client:
        if method == "GET":
            return client.get(url, headers=headers)
        return client.post(url, json=body if body is not None else {}, headers=headers)


def test_server_is_up() -> None:
    """Sanity: the target is a live sp server (and not, say, a 404 proxy)."""
    with httpx.Client(timeout=TIMEOUT) as client:
        assert client.get(f"{BASE_URL}/health").status_code == 200


def test_auth_is_actually_enabled_on_target() -> None:
    """Guard against a false-green suite.

    If the target was booted with --no-token, ``enable_auth`` is False and
    ``AuthBackend`` hands ``read``+``edit`` to *anonymous* callers -- the
    decorator then passes for everyone and the fix protects nothing. This
    test fails first, with that cause named, instead of leaving 17
    indistinguishable route failures behind.
    """
    response = _request("POST", "/api/dbt/project_info", {})
    assert response.status_code in REJECT_STATUSES, (
        "anonymous POST /api/dbt/project_info was not rejected "
        f"(got {response.status_code}). Either the @requires('edit') fix is "
        "missing, or this server was booted with --no-token / "
        "enable_auth=False, in which case the fix cannot protect anything."
    )


@pytest.mark.parametrize(
    ("method", "path", "body"), EDIT_GATED_ROUTES, ids=ROUTE_IDS
)
def test_unauthenticated_request_is_rejected(
    method: str, path: str, body: dict[str, object] | None
) -> None:
    """R2-1 / R2-2: no anonymous caller reaches these handlers."""
    response = _request(method, path, body)
    assert response.status_code in REJECT_STATUSES, (
        f"{method} {path} returned {response.status_code} to an "
        f"UNAUTHENTICATED caller -- handler is reachable. Body: "
        f"{response.text[:400]}"
    )


@pytest.mark.parametrize(
    ("method", "path", "body"), EDIT_GATED_ROUTES, ids=ROUTE_IDS
)
def test_authenticated_edit_identity_reaches_handler(
    method: str, path: str, body: dict[str, object] | None
) -> None:
    """The fix must not break legitimate callers.

    An ``edit``-scoped identity must get *past* the decorator. Any non-auth
    status (200, or 4xx/5xx from the inert body) proves the handler ran.
    """
    response = _request(method, path, body, token=TOKEN)
    assert response.status_code not in REJECT_STATUSES, (
        f"{method} {path} rejected an edit-scoped identity with "
        f"{response.status_code}: {response.text[:400]}"
    )


requires_run_mode = pytest.mark.skipif(
    not (RUN_BASE_URL and RUN_TOKEN),
    reason="set SP_E2E_RUN_BASE_URL/SP_E2E_RUN_TOKEN to a RUN-mode instance",
)


@requires_run_mode
def test_run_mode_identity_really_holds_read_scope() -> None:
    """Positive control for the read-only test below.

    Without this, ``test_read_only_identity_is_rejected`` would pass even if
    the RUN token were simply invalid. A read-gated route must answer 200 for
    the RUN token and reject an anonymous caller.
    """
    # Separate clients on purpose: a successful auth sets a session cookie
    # (``CookieSession.set_access_token``), so a shared cookie jar would make
    # the "anonymous" request authenticated.
    with httpx.Client(timeout=TIMEOUT) as client:
        authed = client.get(
            RUN_BASE_URL + READ_GATED_CONTROL,
            headers={"Authorization": f"Bearer {RUN_TOKEN}"},
        )
    with httpx.Client(timeout=TIMEOUT) as client:
        anon = client.get(RUN_BASE_URL + READ_GATED_CONTROL)
    assert authed.status_code == 200, (
        f"RUN token was not accepted on the read-gated control route "
        f"{READ_GATED_CONTROL}: {authed.status_code} {authed.text[:200]}"
    )
    assert anon.status_code in REJECT_STATUSES, anon.text[:200]


@requires_run_mode
@pytest.mark.parametrize(
    ("method", "path", "body"), EDIT_GATED_ROUTES, ids=ROUTE_IDS
)
def test_read_only_identity_is_rejected(
    method: str, path: str, body: dict[str, object] | None
) -> None:
    """read -> exec privilege escalation.

    In RUN mode ``AuthBackend`` grants only ``AuthCredentials(["read"])``.
    Every one of these routes is an edit-class operation (runs dbt, clones
    repos, drives a tool-enabled agent), so a read-scope holder must get 403.
    """
    response = _request(
        method, path, body, token=RUN_TOKEN, base_url=RUN_BASE_URL
    )
    assert response.status_code in REJECT_STATUSES, (
        f"{method} {path} let a READ-ONLY identity through with "
        f"{response.status_code} -- read->exec escalation. Body: "
        f"{response.text[:400]}"
    )


def test_route_inventory_is_fully_covered() -> None:
    """A new dbt/agent handler that nobody listed above fails the suite.

    Enumerates the routers' registered paths and requires that the tables in
    this module cover them exactly. Needs the server package importable, so
    it is skipped when run from outside the server environment.
    """
    pytest.importorskip("signalpilot._server.api.endpoints.dbt")
    from signalpilot._server.api.endpoints.agent import router as agent_router
    from signalpilot._server.api.endpoints.dbt import router as dbt_router

    def registered(router: object, prefix: str) -> set[tuple[str, str]]:
        found: set[tuple[str, str]] = set()
        for route in router.routes:  # type: ignore[attr-defined]
            for method in sorted(route.methods or ()):  # type: ignore[attr-defined]
                if method in ("HEAD", "OPTIONS"):
                    continue
                found.add((method, prefix + route.path))  # type: ignore[attr-defined]
        return found

    actual = registered(dbt_router, "/api/dbt") | registered(
        agent_router, "/api/agent"
    )
    covered = {(method, path) for method, path, _ in EDIT_GATED_ROUTES}

    assert actual == covered, (
        "dbt/agent route inventory drifted -- add the new route(s) to the "
        "tables in this module (and make sure they carry @requires). "
        f"Not covered by tests: {sorted(actual - covered)}. "
        f"Listed but not registered: {sorted(covered - actual)}."
    )


# ── B. DBT_COMMANDS allowlist enforcement ────────────────────────


DBT_RESULT_KEYS = ("exitCode", "stdout", "stderr", "durationMs")


@pytest.mark.parametrize(
    "command",
    [
        "definitely-not-a-dbt-command",
        "run-operation-that-does-not-exist",
        "run; whoami",
        "--version",
        "",
    ],
)
def test_non_allowlisted_dbt_command_is_rejected(command: str) -> None:
    """The DBT_COMMANDS allowlist was defined but never enforced."""
    response = _request("POST", "/api/dbt/command", {"command": command}, token=TOKEN)
    assert response.status_code == 400, (
        f"non-allowlisted command {command!r} got {response.status_code}: "
        f"{response.text[:400]}"
    )
    payload = response.json()
    assert "Unsupported dbt command" in str(payload.get("error", "")), payload
    # Proof dbt was never invoked: the runner's result fields are absent.
    for key in DBT_RESULT_KEYS:
        assert key not in payload, (
            f"response for a blocked command carries {key!r} -- dbt appears "
            f"to have been invoked: {payload}"
        )


def test_allowlisted_dbt_command_passes_the_allowlist() -> None:
    """An allowlisted command must get past the check (it may then fail)."""
    response = _request("POST", "/api/dbt/command", {"command": "parse"}, token=TOKEN)
    assert response.status_code != 400, (
        f"allowlisted 'parse' was blocked: {response.text[:400]}"
    )
    payload = response.json()
    assert "exitCode" in payload, (
        f"'parse' did not reach the dbt runner: {payload}"
    )


# ── A (side-effect proof). Rejection means "did not execute" ─────


def test_unauthenticated_scaffold_creates_nothing() -> None:
    """Prove the 401 is a real block, not a post-hoc error response.

    Anonymous scaffold into a fresh directory, then ask an authenticated
    caller whether a dbt project appeared there. Positive control: the same
    scaffold *with* auth does create a discoverable project, so the probe is
    sensitive to the side effect it is looking for.
    """
    parent = "/workspace"
    name = f"e2e_authprobe_{uuid.uuid4().hex[:8]}"

    def project_exists() -> bool:
        found = _request(
            "POST",
            "/api/dbt/discover_projects",
            {"rootDir": parent},
            token=TOKEN,
        )
        assert found.status_code == 200, found.text[:400]
        return any(
            name in str(project.get("projectDir", ""))
            or project.get("projectName") == name
            for project in found.json()["projects"]
        )

    anon = _request(
        "POST",
        "/api/dbt/scaffold_project",
        {"projectName": name, "parentDir": parent},
    )
    assert anon.status_code in REJECT_STATUSES, anon.text[:400]
    assert not project_exists(), (
        f"unauthenticated scaffold_project actually wrote project {name}"
    )

    # Positive control: the probe must be able to see the side effect.
    authed = _request(
        "POST",
        "/api/dbt/scaffold_project",
        {"projectName": name, "parentDir": parent},
        token=TOKEN,
    )
    assert authed.status_code == 200, authed.text[:400]
    assert authed.json()["success"] is True, authed.json()
    assert project_exists(), (
        "probe is not sensitive: authenticated scaffold produced no "
        "discoverable project either"
    )


def test_unauthenticated_dbt_command_does_not_execute() -> None:
    """An anonymous /command must not return runner output."""
    response = _request("POST", "/api/dbt/command", {"command": "parse"})
    assert response.status_code in REJECT_STATUSES, response.text[:400]
    for key in DBT_RESULT_KEYS:
        assert key not in response.text, (
            f"anonymous /api/dbt/command response contains {key!r} -- dbt ran: "
            f"{response.text[:400]}"
        )
