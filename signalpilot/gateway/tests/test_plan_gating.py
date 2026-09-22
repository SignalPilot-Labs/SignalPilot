"""The one gating rule: RequireBillablePlan, RequireDeploymentCapability, and the bootstrap payload.

Every case is driven through a real FastAPI app with the identity seams
overridden, so the tests exercise the dependency wiring, the error bodies and
the handler that lifts them to the top level, not just the helper functions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.api import deps
from gateway.api.deps import (
    GatingError,
    RequireBillablePlan,
    RequireDeploymentCapability,
    deployment_capabilities,
    require_billable_plan,
)
from gateway.auth import resolve_org_id, resolve_user_id
from gateway.billing import entitlements as ent
from gateway.billing.entitlements import OrgEntitlement
from gateway.config.evals import get_eval_run_settings
from gateway.config.sandbox_runtime import reset_sandbox_runtime_settings
from gateway.governance import org_limits

FREE_ORG = "org_free"
TEAM_ORG = "org_team"
PAST_DUE_ORG = "org_past_due"
LAPSED_ORG = "org_lapsed"
RUNNER_IMAGE = "example.com/eval-runner@sha256:" + "a" * 64

ENTITLEMENTS: dict[str, OrgEntitlement] = {
    FREE_ORG: OrgEntitlement(org_id=FREE_ORG, tier="free", status="none"),
    TEAM_ORG: OrgEntitlement(
        org_id=TEAM_ORG,
        tier="team",
        status="active",
        included_seats=10,
        included_models=30,
        included_eval_runs=30,
        included_credits=5_000,
    ),
    PAST_DUE_ORG: OrgEntitlement(
        org_id=PAST_DUE_ORG,
        tier="scale",
        status="past_due",
        grace_until=datetime.now(UTC) + timedelta(days=3),
    ),
    LAPSED_ORG: OrgEntitlement(
        org_id=LAPSED_ORG,
        tier="enterprise",
        status="past_due",
        grace_until=datetime.now(UTC) - timedelta(days=1),
    ),
}


@pytest.fixture
def cloud(monkeypatch: pytest.MonkeyPatch):
    """Cloud mode with the subscriptions read replaced by the table above."""
    monkeypatch.setenv("SP_BACKEND_URL", "https://backend.invalid")

    async def _load(org_id: str) -> OrgEntitlement:
        return ENTITLEMENTS.get(org_id) or ent.free_entitlement(org_id)

    monkeypatch.setattr(ent, "_load_entitlement", _load)
    ensured = AsyncMock()
    monkeypatch.setattr("gateway.store.orgs.ensure_gateway_org", ensured)
    ent.invalidate()
    yield ensured
    ent.invalidate()


@pytest.fixture
def local(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SP_BACKEND_URL", raising=False)
    monkeypatch.setattr(ent, "_load_entitlement", AsyncMock(side_effect=AssertionError("no db in local mode")))
    ent.invalidate()
    yield
    ent.invalidate()


@pytest.fixture
def evals_capable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("SP_EVAL_RUNNER_IMAGE", RUNNER_IMAGE)
    monkeypatch.setenv("SP_EVAL_S3_BUCKET", "sp-eval-runs")
    monkeypatch.delenv("SP_EVAL_EXECUTION_BACKEND", raising=False)
    get_eval_run_settings.cache_clear()
    yield
    get_eval_run_settings.cache_clear()


@pytest.fixture
def evals_incapable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SP_EVAL_RUNNER_IMAGE", raising=False)
    get_eval_run_settings.cache_clear()
    yield
    get_eval_run_settings.cache_clear()


@pytest.fixture(autouse=True)
def _sandbox_settings(monkeypatch: pytest.MonkeyPatch):
    for name in ("VERCEL_TOKEN", "VERCEL_TEAM_ID", "VERCEL_PROJECT_ID"):
        monkeypatch.delenv(name, raising=False)
    reset_sandbox_runtime_settings()
    yield
    reset_sandbox_runtime_settings()


def _app(org_id: str) -> FastAPI:
    """A tiny app with one plan-gated and one capability-gated route."""
    from gateway.api import _gating_error_handler

    app = FastAPI()
    app.add_exception_handler(GatingError, _gating_error_handler)

    @app.get("/plan-gated", dependencies=[RequireBillablePlan])
    async def plan_gated():
        return {"ok": True}

    @app.get("/evals-gated", dependencies=[RequireDeploymentCapability("evals")])
    async def evals_gated():
        return {"ok": True}

    @app.get("/sandbox-gated", dependencies=[RequireDeploymentCapability("sandbox")])
    async def sandbox_gated():
        return {"ok": True}

    async def _user() -> str:
        return "user-1"

    async def _org() -> str:
        return org_id

    app.dependency_overrides[resolve_user_id] = _user
    app.dependency_overrides[resolve_org_id] = _org
    return app


class TestRequireBillablePlan:
    @pytest.mark.parametrize("org", [TEAM_ORG, PAST_DUE_ORG])
    def test_billable_org_passes(self, cloud, org: str) -> None:
        with TestClient(_app(org)) as client:
            assert client.get("/plan-gated").json() == {"ok": True}

    @pytest.mark.parametrize("org,tier", [(FREE_ORG, "free"), (LAPSED_ORG, "enterprise"), ("org_unknown", "free")])
    def test_non_billable_org_gets_402_plan_required(self, cloud, org: str, tier: str) -> None:
        with TestClient(_app(org)) as client:
            resp = client.get("/plan-gated")
        assert resp.status_code == 402
        body = resp.json()
        assert body["error"] == "plan_required"
        assert body["tier"] == tier
        # The same keys are repeated under ``detail`` for clients that only read that.
        assert body["detail"] == {"error": "plan_required", "tier": tier}

    def test_refusal_body_names_no_org(self, cloud) -> None:
        with TestClient(_app(FREE_ORG)) as client:
            assert FREE_ORG not in client.get("/plan-gated").text

    def test_local_mode_is_never_gated(self, local) -> None:
        with TestClient(_app("local")) as client:
            assert client.get("/plan-gated").status_code == 200

    def test_gate_keeps_the_gateway_orgs_side_effect(self, cloud) -> None:
        with TestClient(_app(TEAM_ORG)) as client:
            client.get("/plan-gated")
        cloud.assert_awaited_with(TEAM_ORG)

    async def test_dependency_returns_the_entitlement(self, cloud) -> None:
        entitlement = await require_billable_plan(TEAM_ORG)
        assert entitlement.tier == "team" and entitlement.included_credits == 5_000

    def test_without_the_handler_the_body_is_under_detail(self, cloud) -> None:
        """Routers mounted in a bare app (as the route tests do) still refuse with the same keys."""
        app = _app(FREE_ORG)
        app.exception_handlers.pop(GatingError)
        with TestClient(app) as client:
            resp = client.get("/plan-gated")
        assert resp.status_code == 402
        assert resp.json() == {"detail": {"error": "plan_required", "tier": "free"}}


class TestRequireDeploymentCapability:
    def test_unknown_capability_is_a_programming_error(self) -> None:
        with pytest.raises(ValueError):
            RequireDeploymentCapability("teleport")

    def test_same_dependency_object_per_name(self) -> None:
        assert RequireDeploymentCapability("evals") is RequireDeploymentCapability("evals")
        assert RequireDeploymentCapability("evals") is not RequireDeploymentCapability("sandbox")

    def test_capable_deployment_passes(self, local, evals_capable) -> None:
        with TestClient(_app("local")) as client:
            assert client.get("/evals-gated").status_code == 200

    def test_incapable_deployment_gets_503(self, local, evals_incapable) -> None:
        with TestClient(_app("local")) as client:
            resp = client.get("/evals-gated")
        assert resp.status_code == 503
        assert resp.json()["error"] == "not_available_in_deployment"
        assert resp.json()["capability"] == "evals"

    def test_capability_ignores_the_plan(self, cloud, evals_capable) -> None:
        """A free org is told the deployment can run evals; the plan gate is a separate answer."""
        with TestClient(_app(FREE_ORG)) as client:
            assert client.get("/evals-gated").status_code == 200

    def test_sandbox_capability_follows_the_runtime_credentials(self, local, monkeypatch) -> None:
        with TestClient(_app("local")) as client:
            assert client.get("/sandbox-gated").status_code == 503
        monkeypatch.setenv("VERCEL_TOKEN", "t")
        monkeypatch.setenv("VERCEL_TEAM_ID", "team")
        monkeypatch.setenv("VERCEL_PROJECT_ID", "p")
        reset_sandbox_runtime_settings()
        with TestClient(_app("local")) as client:
            assert client.get("/sandbox-gated").status_code == 200

    def test_deployment_capabilities_shape(self, evals_incapable) -> None:
        assert deployment_capabilities() == {"evals": False, "sandbox": False}


class TestEvalsCapability:
    """``evals`` means image + evidence store + a backend that can run in this mode."""

    def test_needs_the_runner_image(self, monkeypatch) -> None:
        monkeypatch.delenv("SP_EVAL_RUNNER_IMAGE", raising=False)
        monkeypatch.setenv("SP_EVAL_S3_BUCKET", "b")
        get_eval_run_settings.cache_clear()
        assert get_eval_run_settings().capable is False

    def test_needs_the_evidence_bucket(self, monkeypatch) -> None:
        monkeypatch.setenv("SP_EVAL_RUNNER_IMAGE", RUNNER_IMAGE)
        monkeypatch.delenv("SP_EVAL_S3_BUCKET", raising=False)
        get_eval_run_settings.cache_clear()
        assert get_eval_run_settings().capable is False

    def test_local_docker_is_capable(self, evals_capable) -> None:
        assert get_eval_run_settings().capable is True

    def test_cloud_without_vercel_backend_is_not_capable(self, evals_capable, monkeypatch) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        get_eval_run_settings.cache_clear()
        assert get_eval_run_settings().capable is False
        monkeypatch.setenv("SP_EVAL_EXECUTION_BACKEND", "vercel")
        get_eval_run_settings.cache_clear()
        assert get_eval_run_settings().capable is True

    def test_no_org_allowlist_exists(self) -> None:
        settings = get_eval_run_settings()
        assert not hasattr(settings, "allowed_orgs")
        assert not hasattr(settings, "org_allowed")


class TestOrgLimits:
    def test_billable_ceilings(self) -> None:
        limits = org_limits.limits_for(ENTITLEMENTS[TEAM_ORG])
        assert (limits.connections, limits.api_keys) == (100, 100)
        assert (limits.knowledge_storage_mb, limits.knowledge_history_versions) == (500, 50)
        assert limits.is_billable

    def test_free_ceilings(self) -> None:
        limits = org_limits.limits_for(ENTITLEMENTS[FREE_ORG])
        assert (limits.connections, limits.api_keys) == (3, 1)
        assert (limits.knowledge_storage_mb, limits.knowledge_history_versions) == (25, 5)
        assert not limits.is_billable

    def test_local_mode_has_no_ceilings(self) -> None:
        limits = org_limits.limits_for(ent.local_entitlement("local"))
        assert limits.connections == limits.api_keys == 0
        assert limits.knowledge_storage_mb == limits.knowledge_history_versions == 0
        org_limits.check_connection_limit(10_000, limits)
        org_limits.check_api_key_limit(10_000, limits)

    def test_ceiling_refusal_is_403_with_a_machine_readable_body(self) -> None:
        limits = org_limits.limits_for(ENTITLEMENTS[FREE_ORG])
        with pytest.raises(Exception) as exc:
            org_limits.check_api_key_limit(1, limits)
        detail = exc.value.detail
        assert exc.value.status_code == 403
        assert detail["error"] == "limit_reached" and detail["resource"] == "api_keys" and detail["limit"] == 1
        org_limits.check_api_key_limit(0, limits)

    async def test_get_org_limits_resolves_the_entitlement(self, cloud) -> None:
        limits = await org_limits.get_org_limits(TEAM_ORG)
        assert limits.tier == "team" and limits.connections == 100
        cloud.assert_awaited_with(TEAM_ORG)

    def test_no_daily_query_limit_exists(self) -> None:
        """Queries are metered as credits by the emitters; there is no per-day cap or counter."""
        from pathlib import Path

        import gateway.governance as governance

        assert not (Path(governance.__file__).parent / "query_limits.py").exists()
        assert not hasattr(org_limits, "check_query_limit")
        assert not hasattr(org_limits, "record_query")


# ── Chat bootstrap payload ───────────────────────────────────────────────────


class _BootstrapStore:
    def __init__(self, org_id: str) -> None:
        self.org_id = org_id
        self.user_id = "user-1"
        self.session = SimpleNamespace()

    def _require_org_id(self) -> str:
        return self.org_id


def _bootstrap_app(org_id: str) -> FastAPI:
    from gateway.api.chat_routes.projects import router
    from gateway.auth.user import resolve_org_role

    app = FastAPI()
    app.include_router(router, prefix="/api/chat")
    app.dependency_overrides[deps.get_store] = lambda: _BootstrapStore(org_id)

    async def _user() -> str:
        return "user-1"

    async def _org() -> str:
        return org_id

    async def _role() -> str:
        return "admin"

    app.dependency_overrides[resolve_user_id] = _user
    app.dependency_overrides[resolve_org_id] = _org
    app.dependency_overrides[resolve_org_role] = _role
    return app


@pytest.fixture
def chat_switches_on(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "SP_FEATURE_STANDALONE_CHAT",
        "SP_FEATURE_CHAT_QUERY_APPROVAL",
        "SP_FEATURE_CHAT_STRUCTURED_RESULTS",
        "SP_FEATURE_CHAT_ORG_SHARING",
        "SP_FEATURE_CHAT_FORKING",
        "SP_FEATURE_CHAT_SIZE_ROUTER",
        "SP_FEATURE_CHAT_RUNTIME_RESULTS",
        "SP_FEATURE_CHAT_RUNTIME_ARTIFACTS",
        "SP_FEATURE_CHAT_DATASET_REFS",
        "SP_FEATURE_CHAT_MCP_CONNECTORS",
    ):
        monkeypatch.delenv(name, raising=False)


class TestBootstrapPayload:
    def test_free_org_sees_its_entitlement_and_a_disabled_surface(self, cloud, chat_switches_on, evals_capable):
        with TestClient(_bootstrap_app(FREE_ORG)) as client:
            resp = client.get("/api/chat/bootstrap")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["enabled"] is False
        assert body["projects"] == []
        assert body["entitlement"]["tier"] == "free"
        assert body["entitlement"]["is_billable"] is False
        assert body["capabilities"] == {"evals": True, "sandbox": False}
        # Every flag is off for a free org even though no kill switch is set.
        assert body["enterprise_features"] and not any(body["enterprise_features"].values())

    @pytest.fixture
    def billable_app(self, cloud, chat_switches_on, monkeypatch) -> FastAPI:
        """A billable org's bootstrap with the project query stubbed to an empty workspace."""
        from gateway.api.chat_routes import projects as projects_module

        class _Result:
            def scalars(self):
                return []

        async def _execute(*_args, **_kwargs):
            return _Result()

        async def _budgets(*_args, **_kwargs):
            return (0.25, 1.0)

        async def _default(*_args, **_kwargs):
            return None

        monkeypatch.setattr(projects_module, "default_chat_budgets", _budgets)
        monkeypatch.setattr(projects_module, "resolve_default_project", _default)
        app = _bootstrap_app(TEAM_ORG)
        store = _BootstrapStore(TEAM_ORG)
        store.session = SimpleNamespace(execute=_execute)
        app.dependency_overrides[deps.get_store] = lambda: store
        return app

    def test_billable_org_flags_are_on_unless_a_kill_switch_is_off(self, billable_app, monkeypatch):
        monkeypatch.setenv("SP_FEATURE_CHAT_FORKING", "false")
        with TestClient(billable_app) as client:
            resp = client.get("/api/chat/bootstrap")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        flags = body["enterprise_features"]
        assert flags["forking"] is False
        assert flags["query_approval"] is True
        assert flags["organization_sharing"] is True
        assert flags["mcp_connectors"] is True
        assert flags["size_router"] is True and flags["size_router_shadow"] is False
        assert body["entitlement"]["is_billable"] is True
        assert body["entitlement"]["included_credits"] == 5_000
        assert set(body["capabilities"]) == {"evals", "sandbox"}

    def test_billable_org_reaches_the_project_list(self, billable_app):
        """``enabled`` is True for a billable org; the project query runs (stubbed to empty)."""
        with TestClient(billable_app) as client:
            resp = client.get("/api/chat/bootstrap")
        assert resp.status_code == 200, resp.text
        assert resp.json()["enabled"] is True
        assert resp.json()["entitlement"]["tier"] == "team"

    def test_kill_switch_off_disables_even_a_billable_org(self, cloud, chat_switches_on, monkeypatch):
        monkeypatch.setenv("SP_FEATURE_STANDALONE_CHAT", "false")
        with TestClient(_bootstrap_app(TEAM_ORG)) as client:
            body = client.get("/api/chat/bootstrap").json()
        assert body["enabled"] is False
        assert body["entitlement"]["is_billable"] is True

    def test_refresh_query_bypasses_the_entitlement_cache(self, billable_app, monkeypatch):
        """The web calls bootstrap with ``?refresh=1`` once after Stripe Checkout."""
        paid = ENTITLEMENTS[TEAM_ORG]
        monkeypatch.setitem(ENTITLEMENTS, TEAM_ORG, ENTITLEMENTS[FREE_ORG])
        with TestClient(billable_app) as client:
            assert client.get("/api/chat/bootstrap").json()["entitlement"]["tier"] == "free"
            monkeypatch.setitem(ENTITLEMENTS, TEAM_ORG, paid)
            body = client.get("/api/chat/bootstrap").json()
            assert body["entitlement"]["tier"] == "free" and body["enabled"] is False
            body = client.get("/api/chat/bootstrap?refresh=1").json()
            assert body["entitlement"]["tier"] == "team" and body["enabled"] is True

    def test_plan_route_accepts_refresh(self, cloud, monkeypatch):
        from gateway.api.keys import router

        app = FastAPI()
        app.include_router(router)
        store = SimpleNamespace(list_connections=AsyncMock(return_value=[]), list_api_keys=AsyncMock(return_value=[]))
        app.dependency_overrides[deps.get_store] = lambda: store

        async def _user() -> str:
            return "user-1"

        async def _org() -> str:
            return FREE_ORG

        app.dependency_overrides[resolve_user_id] = _user
        app.dependency_overrides[resolve_org_id] = _org
        with TestClient(app) as client:
            resp = client.get("/api/plan")
            assert resp.status_code == 200, resp.text
            assert resp.json()["tier"] == "free"
            monkeypatch.setitem(ENTITLEMENTS, FREE_ORG, ENTITLEMENTS[TEAM_ORG])
            assert client.get("/api/plan").json()["tier"] == "free"
            body = client.get("/api/plan?refresh=1").json()
            assert body["tier"] == "team" and body["is_billable"] is True

    def test_bootstrap_itself_is_not_plan_gated(self, cloud, chat_switches_on):
        """A free org must be able to read the payload that tells it to pick a plan."""
        from fastapi.routing import APIRoute

        from gateway.api.chat_routes.projects import router

        route = next(r for r in router.routes if isinstance(r, APIRoute) and r.path == "/bootstrap")
        assert require_billable_plan not in {d.dependency for d in route.dependencies}

    def test_the_other_chat_routes_are_plan_gated(self, cloud, chat_switches_on):
        from fastapi.routing import APIRoute

        from gateway.api.standalone_chat import router

        ungated = [
            r.path
            for r in router.routes
            if isinstance(r, APIRoute) and require_billable_plan not in {d.dependency for d in r.dependencies}
        ]
        assert ungated == ["/api/chat/bootstrap"]

    def test_chat_reports_are_plan_gated(self):
        from fastapi.routing import APIRoute

        from gateway.api.chat_reports import router

        for route in router.routes:
            if isinstance(route, APIRoute):
                assert require_billable_plan in {d.dependency for d in route.dependencies}, route.path

    def test_chat_kill_switch_answers_503(self, cloud, chat_switches_on, monkeypatch):
        from gateway.api.chat_routes.common import require_enabled

        monkeypatch.setenv("SP_FEATURE_STANDALONE_CHAT", "0")
        with pytest.raises(GatingError) as exc:
            require_enabled()
        assert exc.value.status_code == 503
        assert exc.value.detail == {"error": "not_available_in_deployment", "capability": "chat"}


class TestKillSwitchDefaults:
    def test_every_chat_flag_defaults_on(self, chat_switches_on) -> None:
        from gateway.standalone_chat.config import enterprise_chat_feature_flags, standalone_chat_enabled

        assert standalone_chat_enabled()
        flags = enterprise_chat_feature_flags().as_dict()
        assert flags.pop("size_router_shadow") is False
        assert all(flags.values()), flags

    def test_a_switch_set_to_false_turns_only_that_capability_off(self, chat_switches_on, monkeypatch) -> None:
        from gateway.standalone_chat.config import enterprise_chat_feature_flags

        monkeypatch.setenv("SP_FEATURE_CHAT_QUERY_APPROVAL", "false")
        flags = enterprise_chat_feature_flags()
        assert flags.query_approval is False
        assert flags.structured_results and flags.forking and flags.sandbox_runtime

    def test_size_router_shadow_value(self, chat_switches_on, monkeypatch) -> None:
        from gateway.standalone_chat.config import enterprise_chat_feature_flags

        monkeypatch.setenv("SP_FEATURE_CHAT_SIZE_ROUTER", "shadow")
        flags = enterprise_chat_feature_flags()
        assert flags.size_router is False and flags.size_router_shadow is True

    def test_improvement_runs_default_on(self) -> None:
        from gateway.models.settings import GatewaySettings

        assert GatewaySettings().improvement_runs_enabled is True


class TestNoStaffConceptRemains:
    def test_deps_exposes_no_staff_or_projects_gate(self) -> None:
        assert not hasattr(deps, "RequirePlatformStaff")
        assert not hasattr(deps, "require_platform_staff")
        assert not hasattr(deps, "ProjectsGate")
        assert not hasattr(deps, "require_projects_feature")

    def test_governance_settings_have_no_admin_list(self) -> None:
        from gateway.config import get_governance_settings

        assert not hasattr(get_governance_settings(), "admin_user_ids")

    def test_plan_limits_module_is_gone(self) -> None:
        from pathlib import Path

        import gateway.governance as governance

        assert not (Path(governance.__file__).parent / "plan_limits.py").exists()

    def test_security_status_is_org_admin_plus_billable(self) -> None:
        from fastapi.routing import APIRoute

        from gateway.api.security import router
        from gateway.auth.user import require_org_admin

        route = next(r for r in router.routes if isinstance(r, APIRoute) and r.path == "/api/security/status")
        route_deps = {d.dependency for d in route.dependencies}
        assert require_billable_plan in route_deps
        param_deps = {d.call for d in route.dependant.dependencies}
        assert require_org_admin in param_deps
