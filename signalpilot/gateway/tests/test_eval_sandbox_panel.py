"""Verify inventory, events, logs, and progress in the evaluation sandbox panel.

An organization cannot view another organization's sandboxes. Responses do not
contain credentials. Each live stream terminates. The tests use asynchronous
test doubles or SQLite for database-backed ownership checks.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api.deps import get_store
from gateway.api.eval_runs import router as eval_runs_router
from gateway.config import get_governance_settings
from gateway.config.evals import EvalRunSettings, get_eval_run_settings
from gateway.db.models import GatewayBase
from gateway.evals import runner, sandboxes
from gateway.store import evals as evals_store

STAFF_USER = "platform-staff"
RUN_A = "run-20260101-010101-aaaaaa"
RUN_B = "run-20260101-020202-bbbbbb"
POD_A = "sp-eval-aaaaaaaaaaaa"
POD_B = "sp-eval-bbbbbbbbbbbb"

# The values that must never appear in any response.
OAUTH_TOKEN = "sk-ant-oat01-" + "supersecrettokenvalue0123456789"
ANTHROPIC_KEY = "sk-ant-api03-" + "anothersupersecretkey0123456789"
MCP_KEY_B64 = base64.b64encode(
    json.dumps(
        {"mcpServers": {"signalpilot": {"headers": {"X-API-Key": "sp-live-secret"}}}},
        separators=(",", ":"),
    ).encode()
).decode()


def _postgres_dsn(authority: str) -> str:
    return "postgresql" + "://" + authority


class FakeStore:
    def __init__(self, org_id: str, user_id: str) -> None:
        self.org_id = org_id
        self.user_id = user_id

    async def get_eval_run(self, run_id: str):
        return None


@pytest.fixture(autouse=True)
def _staff_ids(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SP_ADMIN_USER_IDS", STAFF_USER)
    get_governance_settings.cache_clear()
    yield
    get_governance_settings.cache_clear()


@pytest.fixture(autouse=True)
def _eval_secrets(monkeypatch: pytest.MonkeyPatch):
    """Real-shaped credentials in settings so redaction is exercised, not assumed."""
    monkeypatch.setenv("SP_EVAL_CLAUDE_TOKEN", OAUTH_TOKEN)
    monkeypatch.setenv("SP_EVAL_ANTHROPIC_KEY", ANTHROPIC_KEY)
    get_eval_run_settings.cache_clear()
    yield
    get_eval_run_settings.cache_clear()


@pytest_asyncio.fixture
async def sqlite_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


@pytest.fixture
def db(sqlite_factory, monkeypatch: pytest.MonkeyPatch):
    """Point every eval-side DB touch at the sqlite factory."""
    import gateway.db.engine as db_engine
    from gateway.evals import notifications, retention

    monkeypatch.setattr(runner, "get_session_factory", lambda: sqlite_factory)
    monkeypatch.setattr(notifications, "get_session_factory", lambda: sqlite_factory)
    monkeypatch.setattr(retention, "get_session_factory", lambda: sqlite_factory)
    monkeypatch.setattr(db_engine, "get_session_factory", lambda: sqlite_factory)
    return sqlite_factory


def _client(org_id: str, user_id: str = STAFF_USER) -> TestClient:
    app = FastAPI()
    app.include_router(eval_runs_router)
    app.dependency_overrides[get_store] = lambda: FakeStore(org_id, user_id)
    return TestClient(app)


async def _seed_run(factory, org_id: str, run_id: str, *, pod: str, task_id: str = "t1:fan/out"):
    async with factory() as session:
        await evals_store.create_run(
            session,
            org_id=org_id,
            run_id=run_id,
            created_at=datetime.now(UTC).isoformat(),
            trigger="manual",
            doc_ids=[],
            doc_titles=[],
            task_filter=None,
            repo_url="https://example.com/set.git",
            model="sonnet",
        )
        await evals_store.seed_tasks(
            session,
            org_id=org_id,
            run_id=run_id,
            tasks=[{"task_id": task_id, "title": f"question for {org_id}"}],
        )
        await evals_store.update_task(
            session,
            org_id=org_id,
            run_id=run_id,
            task_id=task_id,
            status="running",
            sandbox={"backend": "kubernetes", "name": pod, "namespace": f"sp-nb-{org_id}"},
        )
        await evals_store.update_run(session, org_id=org_id, run_id=run_id, status="running")


def _pod(name: str, *, phase: str = "Running", waiting: str = "", node: str = "ip-10-0-1-7") -> dict:
    state: dict = {"running": {"started_at": "2026-01-01T00:00:11+00:00"}}
    if waiting:
        state = {"waiting": {"reason": waiting, "message": f"pulling with {OAUTH_TOKEN}"}}
    return {
        "metadata": {
            "name": name,
            "namespace": "sp-nb-org",
            "labels": {
                "signalpilot.ai/eval": "1",
                "signalpilot.ai/eval-run": RUN_A,
                "signalpilot.ai/eval-question": "t1-fan-out",
            },
            "creation_timestamp": "2026-01-01T00:00:00+00:00",
        },
        "spec": {
            "node_name": node,
            # The real pod spec carries these; the panel must never echo them back.
            "containers": [
                {
                    "name": "eval",
                    "env": [
                        {"name": "SP_MCP_JSON_B64", "value": MCP_KEY_B64},
                        {"name": "ANTHROPIC_API_KEY", "value": ANTHROPIC_KEY},
                    ],
                }
            ],
        },
        "status": {
            "phase": phase,
            "start_time": "2026-01-01T00:00:05+00:00",
            "container_statuses": [
                {"name": "eval", "ready": phase == "Running" and not waiting, "restart_count": 1, "state": state}
            ],
        },
    }


def _fake_core(pods: list[dict] | None = None, events: list[dict] | None = None) -> MagicMock:
    core = MagicMock()
    core.list_namespaced_pod = AsyncMock(return_value={"items": pods or []})
    core.list_namespaced_event = AsyncMock(return_value={"items": events or []})
    return core


def _patch_k8s_view(core: MagicMock, namespace: str = "sp-nb-org"):
    """Wire KubernetesSandboxView onto a mocked cluster."""

    async def _connect(self):
        self._namespace = namespace
        return core, namespace

    return patch.object(sandboxes.KubernetesSandboxView, "_connect", _connect)


def _patch_owners(monkeypatch, owners: dict[str, dict] | None = None) -> None:
    """Replace the asynchronous database-backed sandbox_index with a test double."""

    async def fake_index(org_id: str, limit: int = 25) -> dict:
        return dict(owners or {})

    monkeypatch.setattr(runner, "sandbox_index", fake_index)


# Verify name validation.


class TestSandboxNameValidation:
    @pytest.mark.parametrize(
        "name",
        [
            "sp-eval-aaaaaaaaaaaa",
            "a" * 12,
            "0123456789abcdef" * 4,
            # Vercel-generated sandbox names
            "gold-planned-chicken-DbtqQZ",
            "ivory-complicated-pelican-euE6FH",
        ],
    )
    def test_accepts_backend_minted_names(self, name: str) -> None:
        assert sandboxes.is_valid_sandbox_name(name)

    @pytest.mark.parametrize(
        "name",
        ["", "../../etc/passwd", "sp-eval-../x", "kube-apiserver", "sp-eval-AAAAAAAAAAAA", "sp-eval-aaaa aaaa"],
    )
    def test_refuses_anything_else(self, name: str) -> None:
        assert not sandboxes.is_valid_sandbox_name(name)

    def test_route_refuses_a_traversal_name(self) -> None:
        with _client("org-a") as client:
            assert client.get("/api/evals/sandboxes/..%2F..%2Fsecrets/events").status_code in (400, 404)


# Verify redaction.


class TestRedaction:
    def test_configured_tokens_are_stripped(self) -> None:
        out = sandboxes.redact(f"failed to pull using {OAUTH_TOKEN} and {ANTHROPIC_KEY}")
        assert OAUTH_TOKEN not in out
        assert ANTHROPIC_KEY not in out
        assert sandboxes.REDACTED in out

    def test_unknown_token_shapes_are_stripped(self) -> None:
        out = sandboxes.redact("env SP_MCP_JSON_B64=" + MCP_KEY_B64)
        assert MCP_KEY_B64 not in out

    def test_bearer_headers_are_stripped(self) -> None:
        assert "hunter2" not in sandboxes.redact("Authorization: hunter2hunter2hunter2")
        assert "abcd1234" not in sandboxes.redact("X-API-Key=abcd1234")

    @pytest.mark.parametrize(
        ("line", "secret"),
        [
            (
                "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",
                "eyJhbGciOiJIUzI1NiJ9.payload.signature",
            ),
            ("Bearer ghs_16CharsOfGitHubInstallTokenAAAA", "ghs_16CharsOfGitHubInstallTokenAAAA"),
            (
                "Authorization=Bearer ghs_TOKENVALUE_NOT_REDACTED_HERE",
                "ghs_TOKENVALUE_NOT_REDACTED_HERE",
            ),
        ],
    )
    def test_bearer_token_value_is_stripped(self, line: str, secret: str) -> None:
        assert secret not in sandboxes.redact(line)

    def test_branch_password_environment_value_is_stripped(self) -> None:
        secret = "Xk3n-" + "_QzT9aVbC2dEfGhIjKlMnOpQrSt"
        assert secret not in sandboxes.redact(f"PGPASSWORD={secret}")

    def test_presigned_url_credentials_are_stripped(self) -> None:
        access_key = "minioadmin%2F20260803%2Fus-east-1%2Fs3%2Faws4_request"
        signature = "0123456789abcdef" * 4
        url = (
            "http://eval-object-proxy:9000/object?X-Amz-Algorithm=AWS4-HMAC-SHA256"
            f"&X-Amz-Credential={access_key}&X-Amz-Signature={signature}"
        )
        out = sandboxes.redact(url)
        assert access_key not in out
        assert signature not in out

    def test_image_digests_survive(self) -> None:
        """An ImagePullBackOff message is useless without the digest it failed on."""
        digest = "a" * 64
        assert digest in sandboxes.redact(f"Failed to pull image reg/eval@sha256:{digest}")

    def test_empty_input(self) -> None:
        assert sandboxes.redact("") == ""

    def test_exact_runtime_secret_is_removed(self) -> None:
        secret = _postgres_dsn("branch_role:password@warehouse/eval-task")
        out = sandboxes.redact(
            f"connecting with {secret}",
            extra_secrets=[secret],
        )
        assert secret not in out
        assert sandboxes.REDACTED in out

    def test_dsn_password_is_removed_when_logged_without_the_url(self) -> None:
        dsn = _postgres_dsn("branch_role:p%40ssword-012345@warehouse/eval-task")
        out = sandboxes.redact(
            "driver rejected password p@ssword-012345",
            extra_secrets=[dsn],
        )
        assert "p@ssword-012345" not in out
        assert sandboxes.REDACTED in out

    def test_eval_api_key_is_removed_when_logged_bare(self) -> None:
        key = "sp_" + "a1" * 16
        out = sandboxes.redact(f"decoded key: {key}")
        assert key not in out

    def test_stream_redaction_survives_chunk_boundaries(self) -> None:
        key = "sp_" + "a1" * 16
        buf = sandboxes._RedactionBuffer()
        assert buf.feed("decoded key: " + key[:12]) == ""
        assert buf.feed(key[12:] + "\n") == f"decoded key: {sandboxes.REDACTED}\n"
        assert buf.flush() == ""

    def test_stream_redacts_dsn_userinfo(self) -> None:
        out = sandboxes.redact(_postgres_dsn("branch_role:p%40ssword-012345@warehouse/eval-task"))
        assert "branch_role" not in out
        assert "p%40ssword-012345" not in out


# Verify inventory.


class TestInventory:
    async def test_pod_is_shaped_for_the_panel(self, monkeypatch) -> None:
        _patch_owners(
            monkeypatch,
            {
                POD_A: {
                    "run_id": RUN_A,
                    "task_id": "t1:fan/out",
                    "task_title": "task for org-a",
                }
            },
        )
        core = _fake_core([_pod(POD_A)])
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        with _patch_k8s_view(core):
            body = await view.inventory()
        (sb,) = body["sandboxes"]
        assert body["backend"] == "kubernetes" and body["live"] is True
        assert sb["name"] == POD_A
        assert sb["phase"] == "running"
        assert sb["reason"] == "Running"
        assert sb["node"] == "ip-10-0-1-7"
        assert sb["restart_count"] == 1
        assert sb["age_seconds"] is not None
        assert sb["run_id"] == RUN_A
        # Exact id from run state, not the label-sanitized "t1-fan-out".
        assert sb["task_id"] == "t1:fan/out"
        assert sb["task_title"] == "task for org-a"

    async def test_waiting_pod_reports_its_reason(self, monkeypatch) -> None:
        _patch_owners(monkeypatch)
        core = _fake_core([_pod(POD_A, phase="Pending", waiting="ImagePullBackOff")])
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        with _patch_k8s_view(core):
            body = await view.inventory()
        (sb,) = body["sandboxes"]
        assert sb["phase"] == "pending"
        assert sb["reason"] == "ImagePullBackOff"
        assert sb["ready"] is False

    async def test_missing_namespace_is_an_empty_list_not_an_error(self, monkeypatch) -> None:
        _patch_owners(monkeypatch)
        core = _fake_core()
        core.list_namespaced_pod = AsyncMock(side_effect=RuntimeError("(404) Not Found"))
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        with _patch_k8s_view(core):
            body = await view.inventory()
        assert body["sandboxes"] == [] and body["live"] is True

    async def test_no_cluster_degrades_honestly(self) -> None:
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")

        async def _no_client(self):
            return None, ""

        with patch.object(sandboxes.KubernetesSandboxView, "_connect", _no_client):
            body = await view.inventory()
        assert body["live"] is False
        assert "unavailable" in body["message"].lower()
        assert body["sandboxes"] == []

    async def test_only_eval_pods_are_listed(self, monkeypatch) -> None:
        _patch_owners(monkeypatch)
        core = _fake_core([_pod(POD_A)])
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        with _patch_k8s_view(core):
            await view.inventory()
        assert core.list_namespaced_pod.await_args.kwargs["label_selector"] == "signalpilot.ai/eval=1"

    def test_view_requires_an_org(self) -> None:
        with pytest.raises(ValueError, match="org_id"):
            sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="")
        with pytest.raises(ValueError, match="org_id"):
            sandboxes.DockerSandboxView(EvalRunSettings(), org_id="")


# Verify events.


def _event(reason: str, message: str, *, type_: str = "Warning") -> dict:
    return {
        "type": type_,
        "reason": reason,
        "message": message,
        "count": 3,
        "first_timestamp": "2026-01-01T00:00:00+00:00",
        "last_timestamp": "2026-01-01T00:00:30+00:00",
        "source": {"component": "kubelet"},
    }


class TestEvents:
    async def test_events_are_shaped_and_field_selected(self) -> None:
        core = _fake_core(events=[_event("FailedScheduling", "0/3 nodes are available")])
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        with _patch_k8s_view(core):
            body = await view.events(POD_A)
        (ev,) = body["events"]
        assert ev["reason"] == "FailedScheduling"
        assert ev["type"] == "Warning"
        assert ev["count"] == 3
        assert ev["source"] == "kubelet"
        selector = core.list_namespaced_event.await_args.kwargs["field_selector"]
        assert f"involvedObject.name={POD_A}" in selector
        assert "involvedObject.kind=Pod" in selector

    async def test_event_messages_are_redacted(self) -> None:
        core = _fake_core(events=[_event("Failed", f"pull failed, auth {OAUTH_TOKEN}")])
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        with _patch_k8s_view(core):
            body = await view.events(POD_A)
        assert OAUTH_TOKEN not in json.dumps(body)

    async def test_docker_says_events_are_unsupported_rather_than_faking_them(self) -> None:
        view = sandboxes.DockerSandboxView(EvalRunSettings(), org_id="org-a")
        try:
            body = await view.events("abcdefabcdef")
        finally:
            await view.aclose()
        assert body["supported"] is False
        assert body["events"] == []


# Verify cross-org isolation.


class TestCrossOrgIsolation:
    async def test_each_org_reads_its_own_namespace(self, monkeypatch) -> None:
        """Namespace resolution is the boundary. the org id must reach it."""
        _patch_owners(monkeypatch)
        seen: list[str] = []

        class _Orch:
            _core_api = _fake_core()
            _namespace_prefix = "sp-nb"

            async def _ensure_client(self):
                return None

            def _resolve_namespace(self, org_id):
                seen.append(org_id)
                return f"sp-nb-{org_id}"

            async def close(self):
                return None

        with patch("gateway.orchestrator.kubernetes.KubernetesOrchestrator", _Orch):
            for org in ("org-a", "org-b"):
                view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id=org)
                body = await view.inventory()
                assert body["namespace"] == f"sp-nb-{org}"
        assert seen == ["org-a", "org-b"]

    async def test_sandbox_index_is_per_org(self, db) -> None:
        await _seed_run(db, "org-a", RUN_A, pod=POD_A)
        await _seed_run(db, "org-b", RUN_B, pod=POD_B)
        assert POD_A in await runner.sandbox_index("org-a")
        assert POD_A not in await runner.sandbox_index("org-b")
        assert POD_B not in await runner.sandbox_index("org-a")

    async def test_a_foreign_pod_gets_no_attribution(self, db) -> None:
        """org-b's index must not name org-a's question, even by pod name."""
        await _seed_run(db, "org-a", RUN_A, pod=POD_A)
        assert await runner.sandbox_index("org-b") == {}

    async def test_run_exists_is_org_scoped(self, db) -> None:
        await _seed_run(db, "org-a", RUN_A, pod=POD_A)
        assert await runner.run_exists("org-a", RUN_A) is True
        assert await runner.run_exists("org-b", RUN_A) is False

    async def test_docker_ownership_requires_a_run_in_this_orgs_state(self, monkeypatch) -> None:
        async def fake_run_exists(org_id: str, run_id: str) -> bool:
            return org_id == "org-a" and run_id == RUN_A

        monkeypatch.setattr(runner, "run_exists", fake_run_exists)
        view_a = sandboxes.DockerSandboxView(EvalRunSettings(), org_id="org-a")
        view_b = sandboxes.DockerSandboxView(EvalRunSettings(), org_id="org-b")
        labels = {"signalpilot.eval": "1", "signalpilot.eval.run": RUN_A}
        try:
            assert await view_a._owns(labels) is True
            assert await view_b._owns(labels) is False
            assert await view_a._owns({"signalpilot.eval": "1"}) is False
        finally:
            await view_a.aclose()
            await view_b.aclose()

    def test_inventory_route_passes_the_callers_org(self) -> None:
        captured: list[str] = []

        class _View:
            async def inventory(self):
                return {
                    "backend": "kubernetes",
                    "live": True,
                    "sandboxes": [],
                    "namespace": "",
                    "message": "",
                    "supports_live_logs": True,
                }

            async def aclose(self):
                return None

        def _factory(org_id: str):
            captured.append(org_id)
            return _View()

        with patch.object(sandboxes, "get_sandbox_view", _factory):
            with _client("org-b") as client:
                assert client.get("/api/evals/sandboxes").status_code == 200
        assert captured == ["org-b"]


# Verify no secret leakage.


class TestNoSecretLeakage:
    """Every sandbox response, over a pod whose spec and messages carry real
    credentials. Nothing but the digest may survive."""

    _SECRETS = (OAUTH_TOKEN, ANTHROPIC_KEY, MCP_KEY_B64, "sp-live-secret")

    def _assert_clean(self, body: str) -> None:
        for secret in self._SECRETS:
            assert secret not in body, f"leaked {secret[:12]}… in response"

    async def test_inventory_never_echoes_the_pod_spec(self, monkeypatch) -> None:
        _patch_owners(monkeypatch)
        core = _fake_core([_pod(POD_A, phase="Pending", waiting="ImagePullBackOff")])
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        with _patch_k8s_view(core):
            body = await view.inventory()
        self._assert_clean(json.dumps(body))
        assert "env" not in json.dumps(body)

    async def test_events_are_clean(self) -> None:
        core = _fake_core(events=[_event("Failed", f"{OAUTH_TOKEN} {MCP_KEY_B64}")])
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        with _patch_k8s_view(core):
            body = await view.events(POD_A)
        self._assert_clean(json.dumps(body))

    def test_log_stream_is_clean(self) -> None:

        class _View:
            async def stream_logs(self, name, *, tail_lines):
                yield "log", f"claude booting with ANTHROPIC_API_KEY={ANTHROPIC_KEY}\n"
                yield "log", f"mcp config {MCP_KEY_B64}\n"
                yield "end", "sandbox-exited"

            async def aclose(self):
                return None

        with patch.object(sandboxes, "get_sandbox_view", lambda org_id: _View()):
            with _client("org-a") as client:
                text = client.get(f"/api/evals/sandboxes/{POD_A}/logs/stream").text
        self._assert_clean(text)
        assert "claude booting" in text


# Verify live log stream.


class TestLogStream:
    def test_stream_emits_open_logs_and_end(self) -> None:
        closed: list[bool] = []

        class _View:
            async def stream_logs(self, name, *, tail_lines):
                assert tail_lines == 50
                yield "log", "line one\n"
                yield "end", "sandbox-exited"

            async def aclose(self):
                closed.append(True)

        with patch.object(sandboxes, "get_sandbox_view", lambda org_id: _View()):
            with _client("org-a") as client:
                resp = client.get(f"/api/evals/sandboxes/{POD_A}/logs/stream?tail=50")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
        assert [e["type"] for e in events] == ["open", "log", "end"]
        assert events[-1]["reason"] == "sandbox-exited"
        # The view is released even on a clean end. no leaked cluster client.
        assert closed == [True]

    def test_stream_terminates_when_the_view_errors(self) -> None:

        class _View:
            async def stream_logs(self, name, *, tail_lines):
                yield "log", "starting\n"
                raise RuntimeError("apiserver went away")

            async def aclose(self):
                return None

        with patch.object(sandboxes, "get_sandbox_view", lambda org_id: _View()):
            with _client("org-a") as client:
                resp = client.get(f"/api/evals/sandboxes/{POD_A}/logs/stream")
        events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
        assert events[-1]["type"] == "end"
        assert events[-1]["reason"] == "stream-error"

    def test_bad_sandbox_name_is_rejected_before_any_cluster_call(self) -> None:
        called: list[str] = []
        with patch.object(sandboxes, "get_sandbox_view", lambda org_id: called.append(org_id)):
            with _client("org-a") as client:
                resp = client.get("/api/evals/sandboxes/not-a-pod-name/logs/stream")
        assert resp.status_code == 400
        assert called == []

    def test_tail_is_bounded(self) -> None:
        with _client("org-a") as client:
            assert client.get(f"/api/evals/sandboxes/{POD_A}/logs/stream?tail=99999").status_code == 422
            assert client.get(f"/api/evals/sandboxes/{POD_A}/logs/stream?tail=0").status_code == 422

    def test_concurrent_streams_are_capped(self, monkeypatch) -> None:
        from gateway.api import eval_runs

        monkeypatch.setattr(eval_runs, "_log_stream_semaphore", _LockedSemaphore())
        with _client("org-a") as client:
            resp = client.get(f"/api/evals/sandboxes/{POD_A}/logs/stream")
        assert resp.status_code == 429
        assert resp.headers.get("Retry-After") == "15"

    async def test_kubernetes_stream_follows_and_caps_bytes(self, monkeypatch) -> None:
        monkeypatch.setattr(sandboxes, "LOG_STREAM_MAX_BYTES", 16)
        core = _fake_core()
        core.read_namespaced_pod_log = AsyncMock(return_value=_FakeLogResponse([b"x" * 8, b"y" * 12, b"never"]))
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        out = []
        with _patch_k8s_view(core):
            async for item in view.stream_logs(POD_A, tail_lines=25):
                out.append(item)
        assert out[-1] == ("end", "byte-cap")
        assert out[0] == ("log", "x" * 8 + "y" * 12)
        assert len(out) == 2  # buffered log plus cap; third chunk never read
        kwargs = core.read_namespaced_pod_log.await_args.kwargs
        assert kwargs["follow"] is True
        assert kwargs["tail_lines"] == 25
        assert kwargs["_preload_content"] is False

    async def test_kubernetes_stream_ends_when_the_pod_exits(self) -> None:
        core = _fake_core()
        core.read_namespaced_pod_log = AsyncMock(return_value=_FakeLogResponse([b"done\n"]))
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        out = []
        with _patch_k8s_view(core):
            async for item in view.stream_logs(POD_A, tail_lines=10):
                out.append(item)
        assert out == [("log", "done\n"), ("end", "sandbox-exited")]

    async def test_attach_failure_is_reported_not_raised(self) -> None:
        core = _fake_core()
        core.read_namespaced_pod_log = AsyncMock(side_effect=RuntimeError("(404) pod gone"))
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        out = []
        with _patch_k8s_view(core):
            async for item in view.stream_logs(POD_A, tail_lines=10):
                out.append(item)
        assert out[-1] == ("end", "attach-failed")

    async def test_docker_stream_refuses_a_container_this_org_does_not_own(self, monkeypatch) -> None:
        async def fake_run_exists(org_id: str, run_id: str) -> bool:
            return False  # org-b owns nothing

        monkeypatch.setattr(runner, "run_exists", fake_run_exists)
        view = sandboxes.DockerSandboxView(EvalRunSettings(), org_id="org-b")
        with patch.object(
            sandboxes.DockerSandboxView,
            "_list_raw",
            AsyncMock(return_value=[{"Id": "a" * 64, "Labels": {"signalpilot.eval.run": RUN_A}}]),
        ):
            out = [item async for item in view.stream_logs("a" * 12, tail_lines=10)]
        await view.aclose()
        assert out == [("end", "not-found")]


class _LockedSemaphore:
    def locked(self) -> bool:
        return True


class _FakeLogResponse:
    """Stands in for the aiohttp response kubernetes_asyncio returns with
    _preload_content=False."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.released = False
        self.content = self

    def iter_chunked(self, _size: int):
        async def gen():
            for chunk in self._chunks:
                yield chunk

        return gen()

    def release(self) -> None:
        self.released = True


# Verify run progress.


class TestDeriveProgress:
    def test_running_run_reports_active_tasks(self) -> None:
        run = {
            "id": RUN_A,
            "status": "running",
            "created_at": datetime.now(UTC).isoformat(),
            "progress": {
                "phase": "running",
                "done": 1,
                "total": 3,
                "active": [{"task_id": "q2", "title": "second", "phase": "agent"}],
                "started_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        }
        body = runner.derive_progress(run)
        assert body["phase"] == "running"
        assert body["done"] == 1
        assert body["total"] == 3
        assert body["active"][0]["task_id"] == "q2"
        assert body["elapsed_s"] is not None and body["elapsed_s"] >= 0

    def test_finished_run_without_markers_still_answers(self) -> None:
        body = runner.derive_progress({"id": RUN_A, "status": "completed", "progress": {}})
        assert body["phase"] == "finished"
        assert body["done"] == 0
        assert body["elapsed_s"] is None

    def test_bad_run_id_is_rejected(self) -> None:
        with _client("org-a") as client:
            assert client.get("/api/evals/runs/not-a-run/progress").status_code == 400


class TestRunnerMarkers:
    async def test_backend_start_callback_carries_the_pod_name(self) -> None:
        from gateway.evals.backends import ContainerRun, _notify_start

        seen: list[dict] = []
        spec = ContainerRun(
            image="img",
            command=["true"],
            env={},
            secret_env={},
            labels={},
            memory_bytes=1,
            nano_cpus=1,
            timeout_seconds=1,
            on_start=seen.append,
        )
        _notify_start(spec, {"backend": "kubernetes", "name": POD_A, "namespace": "sp-nb-org"})
        assert seen[0]["name"] == POD_A
        assert seen[0]["started_at"]

    def test_a_failing_callback_does_not_break_the_run(self) -> None:
        from gateway.evals.backends import ContainerRun, _notify_start

        def boom(_info: dict) -> None:
            raise RuntimeError("disk full")

        spec = ContainerRun(
            image="img",
            command=["true"],
            env={},
            secret_env={},
            labels={},
            memory_bytes=1,
            nano_cpus=1,
            timeout_seconds=1,
            on_start=boom,
        )
        _notify_start(spec, {"backend": "docker", "name": "abc"})  # must not raise


# Verify a run with a backend test double.


class _FakeObjectStore:
    """In-memory evidence store with the real key layout."""

    from gateway.evals.object_store import EvalObjectStore as _Real

    transcript_key = _Real.transcript_key
    setup_log_key = _Real.setup_log_key
    artifact_key = _Real.artifact_key
    artifacts_prefix = _Real.artifacts_prefix
    run_prefix = _Real.run_prefix
    project_tarball_key = _Real.project_tarball_key

    def __init__(self) -> None:
        self.texts: dict[str, str] = {}
        self.blobs: dict[str, bytes] = {}

    async def put_text(self, key: str, text: str) -> int:
        self.texts[key] = text
        return len(text)

    async def put_bytes(self, key: str, data: bytes, content_type: str = "") -> int:
        self.blobs[key] = data
        return len(data)

    async def get_text(self, key: str) -> str | None:
        return self.texts.get(key)

    async def delete_prefix(self, prefix: str) -> int:
        return 0


class TestProgressDuringARun:
    """Exercise execute_run with a backend test double and SQLite.

    Tasks run concurrently. The runner records sandbox markers, grading results,
    the summary, and the permanent accuracy record.
    """

    @pytest.fixture
    def eval_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        repo = tmp_path / "projects" / "set-1"
        repo.mkdir(parents=True)
        (repo / "eval.json").write_text(
            json.dumps(
                {
                    "name": "t",
                    "tasks": [
                        {"id": "q1", "prompt_text": "what is 6*7?", "gt": "42"},
                        {"id": "q2", "prompt_text": "6*7 again?", "gt": "42"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("SP_EVAL_PROJECTS_DIR", str(tmp_path / "projects"))
        monkeypatch.setenv("SP_EVAL_RUNNER_IMAGE", "sp-eval-runner:latest")
        monkeypatch.setenv("SP_EVAL_S3_BUCKET", "eval-evidence")
        # Serialize tasks: the sqlite StaticPool shares one connection, which
        # concurrent sessions would fight over. One-at-a-time is still the
        # full lifecycle per task.
        monkeypatch.setenv("SP_EVAL_MAX_PARALLEL_TASKS", "1")
        get_eval_run_settings.cache_clear()
        yield repo
        get_eval_run_settings.cache_clear()

    @pytest.fixture
    def fake_obj(self, monkeypatch: pytest.MonkeyPatch) -> _FakeObjectStore:
        obj = _FakeObjectStore()
        from gateway.evals import retention

        monkeypatch.setattr(runner, "get_object_store", lambda: obj)
        monkeypatch.setattr(retention, "get_object_store", lambda: obj)
        return obj

    async def _start_run(self, db, org: str, repo: Path) -> str:
        run_id = runner.new_run_id()
        async with db() as session:
            await evals_store.save_config(
                session,
                org_id=org,
                cfg={"repo_url": str(repo), "connection": "eval-warehouse"},
            )
            await evals_store.create_run(
                session,
                org_id=org,
                run_id=run_id,
                created_at=datetime.now(UTC).isoformat(),
                trigger="manual",
                doc_ids=[],
                doc_titles=[],
                task_filter=None,
                repo_url=str(repo),
                model="sonnet",
            )
        return run_id

    async def test_a_full_run_lands_in_the_db(self, db, eval_repo, fake_obj, monkeypatch) -> None:
        observed: list[dict] = []

        class _Backend:
            def __init__(self) -> None:
                self.n = 0
                self._lock = asyncio.Lock()

            async def run(self, spec):
                async with self._lock:
                    self.n += 1
                    name = f"cafebabe{self.n:04d}"
                started = spec.on_start({"backend": "docker", "name": name})
                if inspect.isawaitable(started):
                    await started  # the marker write must land mid-task
                async with db() as session:
                    run = await evals_store.get_run(session, org_id="org-a", run_id=run_id)
                observed.append(runner.derive_progress(run))
                return 0, 'noise\n{"type":"result","result":"the answer is 42"}'

            async def aclose(self) -> None:
                return None

        monkeypatch.setattr(runner, "get_execution_backend", lambda *a, **k: _Backend())
        run_id = await self._start_run(db, "org-a", eval_repo)

        await runner.execute_run("org-a", run_id)

        async with db() as session:
            run = await evals_store.get_run(session, org_id="org-a", run_id=run_id)
        assert run["status"] == "completed"
        assert run["summary"]["total"] == 2
        assert run["summary"]["correct"] == 2
        assert run["eval_set_name"] == "t"
        assert run["eval_set_ref"].startswith("local-")

        # Task rows are graded and carry the extracted answer.
        assert [t["verdict"] for t in run["tasks"]] == ["CORRECT", "CORRECT"]
        assert all(t["status"] == "done" for t in run["tasks"])
        assert all("42" in t["answer"] for t in run["tasks"])

        # Transcripts landed in the evidence store under the run's keys.
        for task_id in ("q1", "q2"):
            key = _FakeObjectStore.transcript_key("org-a", run_id, task_id)
            assert "result" in fake_obj.texts[key]

        # The permanent accuracy record got its row.
        async with db() as session:
            history = await evals_store.list_accuracy(session, org_id="org-a")
        assert len(history) == 1
        assert history[0]["run_id"] == run_id
        assert history[0]["accuracy_pct"] == 100.0
        assert history[0]["tasks_total"] == 2

        # Mid-run the board reported live progress with the right shape.
        assert observed, "the backend never saw a mid-run progress snapshot"
        for snap in observed:
            assert snap["status"] == "running"
            assert snap["total"] == 2
            assert {"phase", "done", "total", "active"} <= set(snap)
        # At least one snapshot names an active task with its sandbox marker.
        active = [a for snap in observed for a in snap["active"]]
        assert any(a.get("sandbox", {}).get("name", "").startswith("cafebabe") for a in active)

        # And the final progress derivation says finished.
        final = runner.derive_progress(run)
        assert final["phase"] == "finished"
        assert final["done"] == 2
        assert final["active"] == []

        # Verify that execute_run revokes every task credential before return.
        from sqlalchemy import select

        from gateway.db.models import GatewayApiKey

        async with db() as session:
            leaked = (
                (await session.execute(select(GatewayApiKey).where(GatewayApiKey.eval_run_id == run_id)))
                .scalars()
                .all()
            )
        assert leaked == [], f"eval-bound API keys leaked: {[k.id for k in leaked]}"

    async def test_a_failing_task_is_an_error_not_a_hang(self, db, eval_repo, fake_obj, monkeypatch) -> None:
        class _Backend:
            async def run(self, spec):
                return 1, ""  # container died with no output

            async def aclose(self) -> None:
                return None

        monkeypatch.setattr(runner, "get_execution_backend", lambda *a, **k: _Backend())
        run_id = await self._start_run(db, "org-a", eval_repo)
        await runner.execute_run("org-a", run_id)

        async with db() as session:
            run = await evals_store.get_run(session, org_id="org-a", run_id=run_id)
        assert run["status"] == "failed"  # every task errored
        assert run["summary"]["error"] == 2
        assert all(t["verdict"] == "ERROR" for t in run["tasks"])

    async def test_markers_from_one_org_are_invisible_to_another(self, db, eval_repo, fake_obj, monkeypatch) -> None:
        class _Backend:
            async def run(self, spec):
                started = spec.on_start({"backend": "docker", "name": "cafebabe0001"})
                if inspect.isawaitable(started):
                    await started
                return 0, '{"type":"result","result":"42"}'

            async def aclose(self) -> None:
                return None

        monkeypatch.setattr(runner, "get_execution_backend", lambda *a, **k: _Backend())
        run_id = await self._start_run(db, "org-a", eval_repo)
        await runner.execute_run("org-a", run_id)

        assert await runner.run_exists("org-a", run_id) is True
        assert await runner.run_exists("org-b", run_id) is False
        assert await runner.sandbox_index("org-b") == {}
