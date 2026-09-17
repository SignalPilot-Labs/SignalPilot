"""Verify that every evaluation route is gated by the organization's plan.

Evals are a paid feature. There is no operator allowlist and no platform-staff
list: an org on a paid tier can use every eval route its scopes allow, and an
org on the free tier is refused with the plan message on every one of them.

The tests enumerate router entries to verify that every route carries one of
the three eval guard lists. State-store test doubles can produce status 404,
422, or 500 for an entitled org; these tests check authorization status only.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from gateway.api import eval_runs as eval_runs_module
from gateway.api.deps import get_store
from gateway.api.eval_runs import router as eval_runs_router
from gateway.auth.user import resolve_org_id
from gateway.config.evals import get_eval_run_settings
from gateway.evals import sandboxes
from gateway.evals.object_store import EvidenceStoreDisabled
from gateway.governance import plan_limits

PAID_ORG = "org_2paidclerkid"
FREE_ORG = "org_2freeclerkid"
USER = "user_member"
RUN_A = "run-20260101-010101-aaaaaa"
POD_A = "sp-eval-aaaaaaaaaaaa"
AVAILABILITY = "/api/evals/availability"

_PATH_VALUES = {
    "run_id": RUN_A,
    "task_id": "q1",
    "phase": "setup",
    "filename": "fct_orders.json",
    "name": POD_A,
}

TIERS = {PAID_ORG: "enterprise", FREE_ORG: "free"}


def _gated_routes() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for route in eval_runs_router.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        for key, value in _PATH_VALUES.items():
            path = path.replace("{" + key + "}", value)
        if path == AVAILABILITY:
            continue
        for method in sorted(route.methods or ()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            out.append((method, path))
    return out


GATED_ROUTES = _gated_routes()


class FakeStore:
    """Minimal store: enough for the guards and for handlers to fail softly."""

    def __init__(self, org_id: str, user_id: str) -> None:
        self.org_id = org_id
        self.user_id = user_id
        self.session = None

    def _require_org_id(self) -> str:
        return self.org_id

    async def get_eval_config(self):
        return {}

    def __getattr__(self, name: str):
        async def _missing(*args, **kwargs):
            return None

        return _missing


class _StubView:
    async def list(self):
        return []

    async def events(self, name):
        return []

    async def logs(self, name):
        async def _gen():
            if False:
                yield b""

        return _gen()

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch):
    get_eval_run_settings.cache_clear()

    async def _limits(org_id: str):
        return plan_limits.PLAN_TIERS[TIERS.get(org_id, "free")]

    monkeypatch.setattr(plan_limits, "get_org_limits", _limits)

    def _disabled():
        raise EvidenceStoreDisabled("SP_EVAL_S3_BUCKET is not set")

    monkeypatch.setattr(eval_runs_module, "get_object_store", _disabled)
    monkeypatch.setattr(sandboxes, "get_sandbox_view", lambda org_id: _StubView())
    yield
    get_eval_run_settings.cache_clear()


def _client(org_id: str, user_id: str = USER) -> TestClient:
    app = FastAPI()
    app.include_router(eval_runs_router)
    app.dependency_overrides[get_store] = lambda: FakeStore(org_id, user_id)
    app.dependency_overrides[resolve_org_id] = lambda: org_id
    return TestClient(app, raise_server_exceptions=False)


def _call(client: TestClient, method: str, path: str):
    if method == "GET":
        return client.get(path)
    if method == "POST":
        return client.post(path, json={})
    if method == "PUT":
        return client.put(path, json={})
    if method == "DELETE":
        return client.delete(path)
    raise AssertionError(method)


class TestEveryRouteCarriesAPlanGate:
    def test_route_enumeration_is_not_empty(self) -> None:
        assert len(GATED_ROUTES) >= 14
        paths = {p for _, p in GATED_ROUTES}
        assert "/api/evals/sandboxes" in paths
        assert f"/api/evals/runs/{RUN_A}/tasks/q1/transcript" in paths
        assert "/api/evals/accuracy" in paths

    def test_every_route_uses_one_of_the_guard_lists(self) -> None:
        guard_lists = (
            eval_runs_module.EVAL_GUARDS,
            eval_runs_module.EVAL_EVIDENCE_GUARDS,
            eval_runs_module.EVAL_EXECUTE_GUARDS,
        )
        gate_calls = {id(lst[1].dependency) for lst in guard_lists}
        assert len({id(lst[1].dependency) for lst in guard_lists}) == 1, "all lists share EvalsGate"
        for route in eval_runs_router.routes:
            if not isinstance(route, APIRoute) or route.path == AVAILABILITY:
                continue
            deps = {id(d.dependency) for d in route.dependencies}
            assert deps & gate_calls, f"{route.path} is missing the plan gate"


class TestPlanGate:
    @pytest.mark.parametrize("method,path", GATED_ROUTES)
    def test_free_plan_org_is_refused(self, method: str, path: str) -> None:
        with _client(FREE_ORG) as client:
            resp = _call(client, method, path)
        assert resp.status_code == 403
        assert "not available on the free plan" in resp.json()["detail"]

    @pytest.mark.parametrize("method,path", GATED_ROUTES)
    def test_paid_plan_org_passes_the_gate(self, method: str, path: str) -> None:
        with _client(PAID_ORG) as client:
            resp = _call(client, method, path)
        assert resp.status_code != 403

    def test_gate_follows_the_active_org_not_the_user(self) -> None:
        with _client(PAID_ORG, user_id=USER) as client:
            assert client.get("/api/evals/runs").status_code == 200
        with _client(FREE_ORG, user_id=USER) as client:
            assert client.get("/api/evals/runs").status_code == 403


class TestAvailability:
    def test_free_plan_reports_plan_reason(self) -> None:
        with _client(FREE_ORG) as client:
            resp = client.get(AVAILABILITY)
        assert resp.status_code == 200
        assert resp.json() == {"enabled": False, "reason": "plan"}

    def test_paid_plan_is_enabled(self) -> None:
        with _client(PAID_ORG) as client:
            resp = client.get(AVAILABILITY)
        assert resp.status_code == 200
        assert resp.json() == {"enabled": True, "reason": "ok"}


class TestPlanTable:
    def test_free_tier_has_no_chat_or_evals(self) -> None:
        free = plan_limits.PLAN_TIERS["free"]
        assert free.chat is False and free.evals is False

    @pytest.mark.parametrize("tier", ["pro", "team", "enterprise", "unlimited"])
    def test_paid_tiers_include_chat_and_evals(self, tier: str) -> None:
        limits = plan_limits.PLAN_TIERS[tier]
        assert limits.chat is True and limits.evals is True

    def test_check_feature_knows_the_new_features(self) -> None:
        from fastapi import HTTPException

        free = plan_limits.PLAN_TIERS["free"]
        for name in ("chat", "evals"):
            with pytest.raises(HTTPException) as exc:
                plan_limits.check_feature(name, free)
            assert exc.value.status_code == 403
        plan_limits.check_feature("chat", plan_limits.PLAN_TIERS["pro"])
