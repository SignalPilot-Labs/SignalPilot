"""Verify SP_EVAL_ALLOWED_ORGS enforcement for evaluation routes.

The organization allowlist and staff check operate independently. The tests
enumerate router entries to verify that every route uses EVAL_GUARDS.

The tests use state-store and object-store test doubles. An allowed organization
can receive status 404, 422, or 500. These tests check authorization status.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from gateway.api import eval_runs as eval_runs_module
from gateway.api.deps import get_store
from gateway.api.eval_runs import _require_allowed_org
from gateway.api.eval_runs import router as eval_runs_router
from gateway.config import get_governance_settings
from gateway.config.evals import get_eval_run_settings
from gateway.evals import sandboxes
from gateway.evals.object_store import EvidenceStoreDisabled

STAFF_USER = "platform-staff"
ALLOWED_ORG = "org_2allowedclerkid"
OTHER_ORG = "org_2someoneelse"
RUN_A = "run-20260101-010101-aaaaaa"
POD_A = "sp-eval-aaaaaaaaaaaa"

AVAILABILITY = "/api/evals/availability"

# Concrete values for the path params the eval routes declare.
_PATH_VALUES = {
    "run_id": RUN_A,
    "task_id": "q1",
    "phase": "setup",
    "filename": "fct_orders.json",
    "name": POD_A,
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
    monkeypatch.setenv("SP_ADMIN_USER_IDS", STAFF_USER)
    monkeypatch.setenv("SP_EVAL_ALLOWED_ORGS", ALLOWED_ORG)
    get_governance_settings.cache_clear()
    get_eval_run_settings.cache_clear()

    def _disabled():
        raise EvidenceStoreDisabled("SP_EVAL_S3_BUCKET is not set")

    monkeypatch.setattr(eval_runs_module, "get_object_store", _disabled)
    monkeypatch.setattr(sandboxes, "get_sandbox_view", lambda org_id: _StubView())
    yield
    get_governance_settings.cache_clear()
    get_eval_run_settings.cache_clear()


def _client(org_id: str, user_id: str = STAFF_USER) -> TestClient:
    app = FastAPI()
    app.include_router(eval_runs_router)
    app.dependency_overrides[get_store] = lambda: FakeStore(org_id, user_id)
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


class TestEveryRouteCarriesItsTier:
    """Verify the organization guard and one expected scope for every route.

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
        observed: dict[tuple[str, str], str] = {}
        for route in eval_runs_router.routes:
            if not isinstance(route, APIRoute) or route.path == AVAILABILITY:
                continue
            deps = list(route.dependencies)
            assert any(
                d is eval_runs_module.RequireAllowedOrg for d in deps
            ), f"{route.path} is missing RequireAllowedOrg"
            tiers = [
                name for name, dep in tier_deps.items() if any(d is dep for d in deps)
            ]
            assert len(tiers) == 1, (
                f"{route.path} must carry exactly one scope tier, found {tiers} — "
                "gate it with EVAL_GUARDS, EVAL_EVIDENCE_GUARDS or EVAL_EXECUTE_GUARDS"
            )
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                observed[(method, route.path)] = tiers[0]
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
    def test_non_allowlisted_org_is_refused(self, method: str, path: str) -> None:
        with _client(OTHER_ORG) as client:
            resp = _call(client, method, path)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Evals are not enabled for this workspace."

    @pytest.mark.parametrize("method,path", GATED_ROUTES)
    def test_allowlisted_org_passes_the_gate(self, method: str, path: str) -> None:
        """Verify that the allowlist does not return status 403.

        State-store test doubles can produce status 404, 422, or 500.
        """
        with _client(ALLOWED_ORG) as client:
            resp = _call(client, method, path)
        assert resp.status_code != 403

    def test_refusal_body_names_no_org(self) -> None:
        with _client(OTHER_ORG) as client:
            body = client.get("/api/evals/config").text
        assert ALLOWED_ORG not in body
        assert OTHER_ORG not in body


class TestGateIsByOrgNotUser:
    def test_same_staff_user_loses_access_when_switching_org(self) -> None:
        with _client(ALLOWED_ORG, user_id=STAFF_USER) as client:
            assert client.get("/api/evals/runs").status_code == 200
        with _client(OTHER_ORG, user_id=STAFF_USER) as client:
            assert client.get("/api/evals/runs").status_code == 403

    def test_blank_org_id_is_refused(self) -> None:
        with _client("", user_id=STAFF_USER) as client:
            assert client.get("/api/evals/runs").status_code == 403

    def test_allowlist_is_whitespace_tolerant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SP_EVAL_ALLOWED_ORGS", f" {OTHER_ORG} , {ALLOWED_ORG} ")
        get_eval_run_settings.cache_clear()
        with _client(ALLOWED_ORG) as client:
            assert client.get("/api/evals/runs").status_code == 200


class TestEmptyAllowlist:
    """Cloud-mode cases are asserted on the setting itself: in cloud mode
    RequireScope rejects the unauthenticated TestClient with 401 before the eval
    gate is reached, so a route call there proves nothing about the allowlist.
    """

    @pytest.mark.parametrize("org", [ALLOWED_ORG, OTHER_ORG, "local", "", None])
    def test_cloud_mode_denies_everyone(self, org, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_EVAL_ALLOWED_ORGS", "")
        get_eval_run_settings.cache_clear()
        assert get_eval_run_settings().org_allowed(org) is False

    def test_cloud_mode_unset_var_denies_everyone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.delenv("SP_EVAL_ALLOWED_ORGS", raising=False)
        get_eval_run_settings.cache_clear()
        settings = get_eval_run_settings()
        assert settings.allowed_orgs == frozenset()
        assert settings.org_allowed(ALLOWED_ORG) is False

    def test_cloud_mode_honours_a_populated_allowlist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        get_eval_run_settings.cache_clear()
        settings = get_eval_run_settings()
        assert settings.org_allowed(ALLOWED_ORG) is True
        assert settings.org_allowed(OTHER_ORG) is False

    def test_local_mode_stays_usable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        monkeypatch.setenv("SP_EVAL_ALLOWED_ORGS", "")
        get_eval_run_settings.cache_clear()
        with _client("local") as client:
            assert client.get("/api/evals/runs").status_code == 200

    def test_populated_allowlist_still_binds_in_local_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        get_eval_run_settings.cache_clear()
        with _client(OTHER_ORG) as client:
            assert client.get("/api/evals/runs").status_code == 403


class TestAvailabilityEndpoint:
    def test_non_staff_cannot_probe_it(self) -> None:
        with _client(OTHER_ORG, user_id="some-tenant-user") as client:
            resp = client.get(AVAILABILITY)
        assert resp.status_code == 403
        assert resp.json() == {"detail": "Platform staff access required"}

    def test_refusal_leaks_no_org_id_or_allowlist(self) -> None:
        with _client(OTHER_ORG, user_id="some-tenant-user") as client:
            body = client.get(AVAILABILITY).text
            assert ALLOWED_ORG not in body
            assert OTHER_ORG not in body
            assert set(client.get(AVAILABILITY).json()) == {"detail"}

    def test_org_admin_without_staff_membership_is_refused(self) -> None:
        """An organization role never substitutes for platform staff membership."""
        with _client(ALLOWED_ORG, user_id="tenant-org-admin") as client:
            assert client.get(AVAILABILITY).status_code == 403

    def test_staff_in_an_allowlisted_org_is_enabled(self) -> None:
        """The probe must agree with EVAL_GUARDS."""
        with _client(ALLOWED_ORG, user_id=STAFF_USER) as client:
            assert client.get(AVAILABILITY).json()["enabled"] is True
            assert client.get("/api/evals/config").status_code != 403

    def test_availability_is_not_behind_the_eval_gates(self) -> None:
        """The probe must not carry EVAL_GUARDS, or the page could never read it."""
        route = next(
            r for r in eval_runs_router.routes
            if isinstance(r, APIRoute) and r.path == AVAILABILITY
        )
        calls = {d.dependency for d in route.dependencies}
        assert _require_allowed_org not in calls


class TestConnectionPinRequired:
    def test_config_save_rejects_a_blank_pin(self) -> None:
        with _client(ALLOWED_ORG, user_id=STAFF_USER) as client:
            response = client.put(
                "/api/evals/config",
                json={"repo_url": "https://example.com/evals.git", "connection": ""},
            )
        assert response.status_code == 422
        assert response.json()["detail"] == "An eval connection pin is required"

    def test_config_save_rejects_an_unknown_pin(self) -> None:
        with _client(ALLOWED_ORG, user_id=STAFF_USER) as client:
            response = client.put(
                "/api/evals/config",
                json={"repo_url": "https://example.com/evals.git", "connection": "missing"},
            )
        assert response.status_code == 422
        assert "does not exist" in response.json()["detail"]


class TestStaffAndOrgAreBothBoundaries:
    """A caller must be both platform staff and in an allowlisted workspace."""

    def test_plain_member_of_an_allowlisted_org_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No staff membership configured anywhere.
        monkeypatch.delenv("SP_ADMIN_USER_IDS", raising=False)
        get_governance_settings.cache_clear()
        with _client(ALLOWED_ORG, user_id="user_plain_member") as client:
            response = client.get("/api/evals/config")
        assert response.status_code == 403
        assert response.json()["detail"] == "Platform staff access required"

    def test_staff_member_of_another_org_is_still_refused(self) -> None:
        with _client("org_someone_else", user_id=STAFF_USER) as client:
            r = client.get("/api/evals/config")
        assert r.status_code == 403
        assert "not enabled for this workspace" in r.text
