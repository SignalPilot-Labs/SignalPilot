"""Org allowlist for /api/evals/* (SP_EVAL_ALLOWED_ORGS).

The gate is per-organization and independent of the staff gate, so both are
proven separately. Routes are enumerated off the router rather than listed, so a
route added without EVAL_GUARDS fails here instead of shipping ungated.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from gateway.api.deps import get_store
from gateway.api.eval_runs import _require_allowed_org, _require_platform_staff
from gateway.api.eval_runs import router as eval_runs_router
from gateway.config import get_governance_settings
from gateway.config.evals import get_eval_run_settings

STAFF_USER = "platform-staff"
ALLOWED_ORG = "org_2allowedclerkid"
OTHER_ORG = "org_2someoneelse"
RUN_A = "run-20260101-010101-aaaaaa"
POD_A = "sp-eval-aaaaaaaaaaaa"

AVAILABILITY = "/api/evals/availability"

# Concrete values for the path params the eval routes declare.
_PATH_VALUES = {
    "run_id": RUN_A,
    "question_id": "q1",
    "state": "clean",
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
    def __init__(self, org_id: str, user_id: str) -> None:
        self.org_id = org_id
        self.user_id = user_id


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
    yield


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SP_ADMIN_USER_IDS", STAFF_USER)
    monkeypatch.setenv("SP_EVAL_ALLOWED_ORGS", ALLOWED_ORG)
    get_governance_settings.cache_clear()
    get_eval_run_settings.cache_clear()
    yield
    get_governance_settings.cache_clear()
    get_eval_run_settings.cache_clear()


def _client(org_id: str, user_id: str = STAFF_USER) -> TestClient:
    app = FastAPI()
    app.include_router(eval_runs_router)
    app.dependency_overrides[get_store] = lambda: FakeStore(org_id, user_id)
    return TestClient(app)


def _call(client: TestClient, method: str, path: str):
    if method == "post":
        return client.post(path, json={"doc_ids": ["doc-1"]})
    if method == "put":
        return client.put(path, json={"repo_url": "https://example.com/x.git"})
    return getattr(client, method)(path)


class TestEveryRouteIsGated:
    def test_route_enumeration_is_not_empty(self) -> None:
        assert len(GATED_ROUTES) >= 12
        paths = {p for _, p in GATED_ROUTES}
        assert f"/api/evals/sandboxes/{POD_A}/logs/stream" in paths
        assert "/api/evals/sandboxes" in paths

    @pytest.mark.parametrize("method,path", GATED_ROUTES)
    def test_non_allowlisted_org_is_refused(self, method: str, path: str) -> None:
        with _client(OTHER_ORG) as client:
            resp = _call(client, method, path)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Evals are not enabled for this workspace."

    @pytest.mark.parametrize("method,path", GATED_ROUTES)
    def test_allowlisted_org_passes_the_gate(self, method: str, path: str) -> None:
        """The gate lets the allowed org through — 403 must not appear anywhere."""
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

    def test_allowlisted_org_still_needs_staff(self) -> None:
        with _client(ALLOWED_ORG, user_id="tenant-org-admin") as client:
            resp = client.get("/api/evals/config")
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Platform staff access required."

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
    def test_non_allowlisted_org_can_read_it(self) -> None:
        with _client(OTHER_ORG, user_id="some-tenant-user") as client:
            resp = client.get(AVAILABILITY)
        assert resp.status_code == 200
        assert resp.json() == {"enabled": False, "reason": "not_enabled_for_org"}

    def test_it_leaks_no_org_id_or_allowlist(self) -> None:
        with _client(OTHER_ORG, user_id="some-tenant-user") as client:
            body = client.get(AVAILABILITY).text
        assert ALLOWED_ORG not in body
        assert OTHER_ORG not in body
        assert set(client.get(AVAILABILITY).json()) == {"enabled", "reason"}

    def test_allowlisted_non_staff_gets_not_staff(self) -> None:
        with _client(ALLOWED_ORG, user_id="tenant-org-admin") as client:
            assert client.get(AVAILABILITY).json() == {"enabled": False, "reason": "not_staff"}

    def test_allowlisted_staff_is_enabled(self) -> None:
        with _client(ALLOWED_ORG, user_id=STAFF_USER) as client:
            assert client.get(AVAILABILITY).json() == {"enabled": True, "reason": "ok"}

    def test_org_gate_is_reported_before_staff(self) -> None:
        """A non-allowlisted staff member sees the workspace reason, not the staff one."""
        with _client(OTHER_ORG, user_id=STAFF_USER) as client:
            assert client.get(AVAILABILITY).json()["reason"] == "not_enabled_for_org"

    def test_availability_is_not_behind_the_eval_gates(self) -> None:
        """The probe must not carry EVAL_GUARDS, or the page could never read it."""
        route = next(
            r for r in eval_runs_router.routes
            if isinstance(r, APIRoute) and r.path == AVAILABILITY
        )
        calls = {d.dependency for d in route.dependencies}
        assert _require_allowed_org not in calls
        assert _require_platform_staff not in calls
