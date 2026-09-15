"""Verify plan and capability gating for evaluation routes.

There is no staff list and no org allowlist any more. Every eval route needs a
billable plan (402 otherwise); execution routes also need a deployment that
can run evals (503 otherwise). The availability probe reports both answers
separately and is not gated, so a free org can read why the page is a prompt.

The tests enumerate router entries to verify that every route carries exactly
one scope tier, and drive each route as a free org and as a billable org. The
state-store and object-store test doubles can answer 404, 422 or 500 for a
billable org; these tests check gating status codes only.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from gateway.api import eval_runs as eval_runs_module
from gateway.api.deps import GatingError, get_store, require_billable_plan, require_deployment_capability_call
from gateway.api.eval_runs import router as eval_runs_router
from gateway.auth import resolve_org_id, resolve_user_id
from gateway.billing import entitlements as ent
from gateway.billing.entitlements import OrgEntitlement
from gateway.config.evals import get_eval_run_settings
from gateway.evals import sandboxes
from gateway.evals.object_store import EvidenceStoreDisabled

BILLABLE_ORG = "org_2teamclerkid"
FREE_ORG = "org_2freeclerkid"
USER = "user_org_admin"
RUN_A = "run-20260101-010101-aaaaaa"
POD_A = "sp-eval-aaaaaaaaaaaa"
RUNNER_IMAGE = "example.com/eval-runner@sha256:" + "a" * 64

AVAILABILITY = "/api/evals/availability"

# Concrete values for the path params the eval routes declare.
_PATH_VALUES = {
    "run_id": RUN_A,
    "task_id": "q1",
    "phase": "setup",
    "filename": "fct_orders.json",
    "name": POD_A,
}

ENTITLEMENTS = {
    BILLABLE_ORG: OrgEntitlement(org_id=BILLABLE_ORG, tier="team", status="active"),
    FREE_ORG: OrgEntitlement(org_id=FREE_ORG, tier="free", status="none"),
}


def _gated_routes() -> list[tuple[str, str]]:
    """Every eval route except the availability probe, as (method, concrete path)."""
    out: list[tuple[str, str]] = []
    for route in eval_runs_router.routes:
        if not isinstance(route, APIRoute) or route.path == AVAILABILITY:
            continue
        path = route.path
        for name, value in _PATH_VALUES.items():
            path = path.replace("{" + name + "}", value)
        assert "{" not in path, f"unmapped path param in {route.path}"
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            out.append((method.lower(), path))
    return sorted(out)


GATED_ROUTES = _gated_routes()


class FakeStore:
    """Only what the routes reachable in these tests actually read."""

    def __init__(self, org_id: str, user_id: str) -> None:
        self.org_id = org_id
        self.user_id = user_id

    async def get_eval_config(self) -> dict:
        return {}

    async def save_eval_config(self, cfg: dict) -> dict:
        return cfg

    async def get_connection(self, name: str):
        return object() if name == "eval-warehouse" else None

    async def get_eval_run(self, run_id: str):
        return None

    async def list_eval_runs(self, limit: int = 50) -> list:
        return []

    async def list_eval_accuracy(self, limit: int = 500) -> list:
        return []

    async def list_eval_regressions(self, limit: int = 100) -> list:
        return []

    async def list_eval_task_performance(self) -> list:
        return []

    async def get_knowledge_doc(self, doc_id: str, include_body: bool = True):
        return None


class _StubView:
    """Keeps the sandbox routes off the Docker socket."""

    async def inventory(self):
        return {
            "backend": "docker",
            "live": True,
            "sandboxes": [],
            "namespace": "",
            "message": "",
            "supports_live_logs": True,
        }

    async def events(self, name: str):
        return {"backend": "docker", "supported": False, "message": "", "events": []}

    async def stream_logs(self, name: str, *, tail_lines: int):
        yield "end", "not-found"

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch):
    """Cloud entitlements from the table above; a deployment that can run evals."""
    monkeypatch.setenv("SP_BACKEND_URL", "https://backend.invalid")
    monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("SP_EVAL_RUNNER_IMAGE", RUNNER_IMAGE)
    monkeypatch.setenv("SP_EVAL_S3_BUCKET", "sp-eval-runs")
    monkeypatch.delenv("SP_EVAL_EXECUTION_BACKEND", raising=False)
    get_eval_run_settings.cache_clear()

    async def _load(org_id: str) -> OrgEntitlement:
        return ENTITLEMENTS.get(org_id) or ent.free_entitlement(org_id)

    monkeypatch.setattr(ent, "_load_entitlement", _load)
    monkeypatch.setattr("gateway.store.orgs.ensure_gateway_org", AsyncMock())
    ent.invalidate()

    def _disabled():
        raise EvidenceStoreDisabled("SP_EVAL_S3_BUCKET is not set")

    monkeypatch.setattr(eval_runs_module, "get_object_store", _disabled)
    monkeypatch.setattr(sandboxes, "get_sandbox_view", lambda org_id: _StubView())
    yield
    ent.invalidate()
    get_eval_run_settings.cache_clear()


def _client(org_id: str, user_id: str = USER) -> TestClient:
    app = FastAPI()
    app.include_router(eval_runs_router)
    app.dependency_overrides[get_store] = lambda: FakeStore(org_id, user_id)

    async def _user() -> str:
        return user_id

    async def _org() -> str:
        return org_id

    app.dependency_overrides[resolve_user_id] = _user
    app.dependency_overrides[resolve_org_id] = _org
    return TestClient(app, raise_server_exceptions=False)


def _call(client: TestClient, method: str, path: str):
    if method == "post":
        return client.post(path, json={"doc_ids": ["doc-1"]})
    if method == "put":
        return client.put(
            path,
            json={"repo_url": "https://example.com/x.git", "connection": "eval-warehouse"},
        )
    return getattr(client, method)(path)


# Map each method and route template to its required scope.
# The read scope permits metadata access. The query scope permits evidence access.
# The admin scope permits configuration changes and evaluation execution.
EXPECTED_TIERS: dict[tuple[str, str], str] = {
    ("GET", "/api/evals/config"): "read",
    ("PUT", "/api/evals/config"): "admin",
    ("GET", "/api/evals/tasks"): "read",
    ("POST", "/api/evals/runs"): "admin",
    ("POST", "/api/evals/runs/{run_id}/cancel"): "admin",
    ("GET", "/api/evals/runs"): "read",
    ("GET", "/api/evals/runs/{run_id}"): "read",
    ("GET", "/api/evals/runs/{run_id}/progress"): "read",
    ("GET", "/api/evals/runs/{run_id}/tasks/{task_id}/setup/{phase}/log"): "query",
    ("GET", "/api/evals/runs/{run_id}/tasks/{task_id}/transcript"): "query",
    ("GET", "/api/evals/runs/{run_id}/artifacts"): "query",
    ("GET", "/api/evals/runs/{run_id}/artifacts/{task_id}/{filename}"): "query",
    ("GET", "/api/evals/runs/{run_id}/export"): "query",
    ("GET", "/api/evals/accuracy"): "read",
    ("GET", "/api/evals/sandboxes"): "read",
    ("GET", "/api/evals/sandboxes/{name}/events"): "read",
    ("GET", "/api/evals/sandboxes/{name}/logs/stream"): "read",
}

EXECUTE_ROUTES = {key for key, tier in EXPECTED_TIERS.items() if tier == "admin"}


class TestEveryRouteCarriesItsTier:
    """Verify the plan gate and one expected scope for every route.

    The test compares guard objects with the Depends instances in the route module.
    """

    def _tier_deps(self) -> dict[str, object]:
        return {
            "read": eval_runs_module.EVAL_GUARDS[0],
            "query": eval_runs_module.EVAL_EVIDENCE_GUARDS[0],
            "admin": eval_runs_module.EVAL_EXECUTE_GUARDS[0],
        }

    def _observed_tiers(self) -> dict[tuple[str, str], str]:
        tier_deps = self._tier_deps()
        evals_capability = require_deployment_capability_call("evals")
        observed: dict[tuple[str, str], str] = {}
        for route in eval_runs_router.routes:
            if not isinstance(route, APIRoute) or route.path == AVAILABILITY:
                continue
            deps = list(route.dependencies)
            calls = {d.dependency for d in deps}
            assert require_billable_plan in calls, f"{route.path} is missing RequireBillablePlan"
            tiers = [name for name, dep in tier_deps.items() if any(d is dep for d in deps)]
            assert len(tiers) == 1, (
                f"{route.path} must carry exactly one scope tier, found {tiers} — "
                "gate it with EVAL_GUARDS, EVAL_EVIDENCE_GUARDS or EVAL_EXECUTE_GUARDS"
            )
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                observed[(method, route.path)] = tiers[0]
                if tiers[0] == "admin":
                    assert evals_capability in calls, f"{route.path} executes but lacks the evals capability gate"
                else:
                    assert evals_capability not in calls, f"{route.path} only reads and must not need a runner"
        return observed

    def test_every_route_matches_the_tier_table(self) -> None:
        observed = self._observed_tiers()
        assert observed == EXPECTED_TIERS, (
            "eval routes drifted from the tier table — if you added a route, "
            "add it to EXPECTED_TIERS with the tier it deserves"
        )

    def test_execute_and_evidence_routes_are_not_merely_read(self) -> None:
        observed = self._observed_tiers()
        assert observed[("PUT", "/api/evals/config")] == "admin"
        assert observed[("POST", "/api/evals/runs")] == "admin"
        for key, tier in observed.items():
            method, path = key
            if "/transcript" in path or "/artifacts" in path or path.endswith("/export") or "/setup/" in path:
                assert tier == "query", f"{key} is evidence and must not be read-tier"

    def test_the_tier_guards_require_distinct_scopes(self) -> None:
        """The three guard lists must not collapse into one scope."""
        deps = self._tier_deps()
        assert len({id(d) for d in deps.values()}) == 3

    def test_no_staff_or_allowlist_guard_exists(self) -> None:
        assert not hasattr(eval_runs_module, "RequireAllowedOrg")
        assert not hasattr(eval_runs_module, "_require_allowed_org")


class TestEveryRouteIsGated:
    def test_route_enumeration_is_not_empty(self) -> None:
        assert len(GATED_ROUTES) >= 14
        paths = {p for _, p in GATED_ROUTES}
        assert f"/api/evals/sandboxes/{POD_A}/logs/stream" in paths
        assert "/api/evals/sandboxes" in paths
        assert f"/api/evals/runs/{RUN_A}/tasks/q1/transcript" in paths
        assert f"/api/evals/runs/{RUN_A}/tasks/q1/setup/setup/log" in paths
        assert f"/api/evals/runs/{RUN_A}/artifacts/q1/fct_orders.json" in paths
        assert f"/api/evals/runs/{RUN_A}/export" in paths
        assert "/api/evals/accuracy" in paths
        assert "/api/evals/tasks" in paths

    @pytest.mark.parametrize("method,path", GATED_ROUTES)
    def test_free_org_gets_402_plan_required(self, method: str, path: str) -> None:
        with _client(FREE_ORG) as client:
            resp = _call(client, method, path)
        assert resp.status_code == 402
        assert resp.json()["detail"] == {"error": "plan_required", "tier": "free"}

    @pytest.mark.parametrize("method,path", GATED_ROUTES)
    def test_billable_org_passes_the_gate(self, method: str, path: str) -> None:
        """Verify that a billable org is never refused by the plan or capability gates.

        State-store test doubles can produce status 404, 422, or 500.
        """
        with _client(BILLABLE_ORG) as client:
            resp = _call(client, method, path)
        assert resp.status_code not in (402, 403, 503), resp.text

    def test_refusal_body_names_no_org(self) -> None:
        with _client(FREE_ORG) as client:
            body = client.get("/api/evals/config").text
        assert BILLABLE_ORG not in body
        assert FREE_ORG not in body

    def test_org_role_does_not_substitute_for_a_plan(self) -> None:
        """An org admin of a free org is still a free org."""
        with _client(FREE_ORG, user_id="tenant-org-admin") as client:
            assert client.get("/api/evals/runs").status_code == 402


class TestGateIsByOrgNotUser:
    def test_same_user_loses_access_when_switching_to_a_free_org(self) -> None:
        with _client(BILLABLE_ORG, user_id=USER) as client:
            assert client.get("/api/evals/runs").status_code == 200
        with _client(FREE_ORG, user_id=USER) as client:
            assert client.get("/api/evals/runs").status_code == 402

    def test_blank_org_id_is_refused(self) -> None:
        with _client("", user_id=USER) as client:
            assert client.get("/api/evals/runs").status_code == 402

    def test_local_mode_stays_usable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SP_BACKEND_URL", raising=False)
        ent.invalidate()
        with _client("local") as client:
            assert client.get("/api/evals/runs").status_code == 200


class TestDeploymentCapability:
    """Execution needs a runner; reading state and evidence does not."""

    @pytest.fixture
    def no_runner(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SP_EVAL_RUNNER_IMAGE", raising=False)
        get_eval_run_settings.cache_clear()
        yield
        get_eval_run_settings.cache_clear()

    @pytest.mark.parametrize("method,path", sorted((m.lower(), p) for m, p in EXECUTE_ROUTES if "{" not in p))
    def test_execute_routes_answer_503_without_a_runner(self, no_runner, method: str, path: str) -> None:
        with _client(BILLABLE_ORG) as client:
            resp = _call(client, method, path)
        assert resp.status_code == 503
        assert resp.json()["detail"] == {"error": "not_available_in_deployment", "capability": "evals"}

    def test_read_routes_still_answer_without_a_runner(self, no_runner) -> None:
        with _client(BILLABLE_ORG) as client:
            assert client.get("/api/evals/runs").status_code == 200
            assert client.get("/api/evals/accuracy").status_code == 200

    def test_plan_is_checked_before_capability(self, no_runner) -> None:
        """A free org on an unconfigured deployment hears about the plan first."""
        with _client(FREE_ORG) as client:
            assert client.post("/api/evals/runs", json={"doc_ids": []}).status_code == 402

    def test_cloud_mode_without_the_vercel_backend_is_not_capable(self, monkeypatch) -> None:
        """Asserted on the setting: in cloud mode RequireScope answers 401 to the
        unauthenticated TestClient before any gate runs, so a route call proves nothing."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        get_eval_run_settings.cache_clear()
        assert get_eval_run_settings().capable is False
        monkeypatch.setenv("SP_EVAL_EXECUTION_BACKEND", "vercel")
        get_eval_run_settings.cache_clear()
        assert get_eval_run_settings().capable is True


class TestAvailabilityEndpoint:
    def test_free_org_can_read_that_it_needs_a_plan(self) -> None:
        with _client(FREE_ORG) as client:
            resp = client.get(AVAILABILITY)
        assert resp.status_code == 200
        assert resp.json() == {"billable": False, "capable": True, "enabled": False}

    def test_billable_org_on_a_capable_deployment_is_enabled(self) -> None:
        with _client(BILLABLE_ORG) as client:
            assert client.get(AVAILABILITY).json() == {"billable": True, "capable": True, "enabled": True}
            assert client.get("/api/evals/config").status_code == 200

    def test_billable_org_on_an_incapable_deployment(self, monkeypatch) -> None:
        monkeypatch.delenv("SP_EVAL_RUNNER_IMAGE", raising=False)
        get_eval_run_settings.cache_clear()
        with _client(BILLABLE_ORG) as client:
            assert client.get(AVAILABILITY).json() == {"billable": True, "capable": False, "enabled": False}

    def test_probe_leaks_no_org_id(self) -> None:
        with _client(FREE_ORG) as client:
            body = client.get(AVAILABILITY).text
        assert BILLABLE_ORG not in body
        assert FREE_ORG not in body

    def test_availability_is_not_behind_the_eval_gates(self) -> None:
        """The probe must not carry EVAL_GUARDS, or the page could never read it."""
        route = next(r for r in eval_runs_router.routes if isinstance(r, APIRoute) and r.path == AVAILABILITY)
        calls = {d.dependency for d in route.dependencies}
        assert require_billable_plan not in calls
        assert require_deployment_capability_call("evals") not in calls


class TestConnectionPinRequired:
    def test_config_save_rejects_a_blank_pin(self) -> None:
        with _client(BILLABLE_ORG) as client:
            response = client.put(
                "/api/evals/config",
                json={"repo_url": "https://example.com/evals.git", "connection": ""},
            )
        assert response.status_code == 422
        assert response.json()["detail"] == "An eval connection pin is required"

    def test_config_save_rejects_an_unknown_pin(self) -> None:
        with _client(BILLABLE_ORG) as client:
            response = client.put(
                "/api/evals/config",
                json={"repo_url": "https://example.com/evals.git", "connection": "missing"},
            )
        assert response.status_code == 422
        assert "does not exist" in response.json()["detail"]


class TestGatingErrorsAreDistinguishable:
    def test_plan_and_capability_errors_are_gating_errors(self) -> None:
        from gateway.api.deps import not_available_error, plan_required_error

        assert isinstance(plan_required_error("free"), GatingError)
        assert isinstance(not_available_error("evals"), GatingError)
