"""Tests for the eval sandbox panel: inventory, pod events, live log SSE and
run progress (gateway/evals/sandboxes.py + the /api/evals/sandboxes routes).

Three properties matter and each has its own class: one org never sees another's
sandboxes, no credential ever reaches a response, and a live stream always
terminates.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.api.deps import get_store
from gateway.api.eval_runs import router as eval_runs_router
from gateway.config import get_governance_settings
from gateway.config.evals import EvalRunSettings, get_eval_run_settings
from gateway.evals import runner, sandboxes

STAFF_USER = "platform-staff"
RUN_A = "run-20260101-010101-aaaaaa"
RUN_B = "run-20260101-020202-bbbbbb"
POD_A = "sp-eval-aaaaaaaaaaaa"
POD_B = "sp-eval-bbbbbbbbbbbb"

# The values that must never appear in any response.
OAUTH_TOKEN = "sk-ant-oat01-supersecrettokenvalue0123456789"
ANTHROPIC_KEY = "sk-ant-api03-anothersupersecretkey0123456789"
MCP_KEY_B64 = "eyJtY3BTZXJ2ZXJzIjp7InNpZ25hbHBpbG90Ijp7ImhlYWRlcnMiOnsiWC1BUEktS2V5Ijoic3AtbGl2ZS1zZWNyZXQifX19fQ=="


class FakeStore:
    def __init__(self, org_id: str, user_id: str) -> None:
        self.org_id = org_id
        self.user_id = user_id


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
    yield


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


def _client(org_id: str, user_id: str = STAFF_USER) -> TestClient:
    app = FastAPI()
    app.include_router(eval_runs_router)
    app.dependency_overrides[get_store] = lambda: FakeStore(org_id, user_id)
    return TestClient(app)


def _seed_run(org_id: str, run_id: str, *, pod: str, question_id: str = "t1:fan/out") -> None:
    run_dir = runner.eval_root(org_id) / run_id
    (run_dir / "questions").mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "id": run_id,
                "status": "running",
                "created_at": "2026-01-01T00:00:00+00:00",
                "questions": [
                    {
                        "id": question_id,
                        "title": f"question for {org_id}",
                        "status": "running",
                        "started_at": "2026-01-01T00:00:10+00:00",
                        "sandbox": {"backend": "kubernetes", "name": pod, "namespace": f"sp-nb-{org_id}"},
                    },
                    {"id": "t2", "title": "second", "status": "pending"},
                ],
                "setup": [],
                "progress": {
                    "phase": "question",
                    "index": 0,
                    "total": 2,
                    "question_id": question_id,
                    "question_title": f"question for {org_id}",
                    "started_at": "2026-01-01T00:00:10+00:00",
                    "sandbox": {"backend": "kubernetes", "name": pod, "namespace": f"sp-nb-{org_id}"},
                },
            }
        ),
        encoding="utf-8",
    )


def _pod(name: str, *, phase: str = "Running", waiting: str = "", node: str = "ip-10-0-1-7") -> dict:
    state: dict = {"running": {"started_at": "2026-01-01T00:00:11+00:00"}}
    if waiting:
        state = {"waiting": {"reason": waiting, "message": f"pulling with {OAUTH_TOKEN}"}}
    return {
        "metadata": {
            "name": name,
            "namespace": "sp-nb-org",
            "labels": {"signalpilot.ai/eval": "1", "signalpilot.ai/eval-run": RUN_A, "signalpilot.ai/eval-question": "t1-fan-out"},
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
            "container_statuses": [{"name": "eval", "ready": phase == "Running" and not waiting, "restart_count": 1, "state": state}],
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


# ─── Name validation ─────────────────────────────────────────────────────────


class TestSandboxNameValidation:
    @pytest.mark.parametrize("name", ["sp-eval-aaaaaaaaaaaa", "a" * 12, "0123456789abcdef" * 4])
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


# ─── Redaction ───────────────────────────────────────────────────────────────


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

    def test_image_digests_survive(self) -> None:
        """An ImagePullBackOff message is useless without the digest it failed on."""
        digest = "a" * 64
        assert digest in sandboxes.redact(f"Failed to pull image reg/eval@sha256:{digest}")

    def test_empty_input(self) -> None:
        assert sandboxes.redact("") == ""


# ─── Inventory ───────────────────────────────────────────────────────────────


class TestInventory:
    @pytest.mark.asyncio
    async def test_pod_is_shaped_for_the_panel(self, monkeypatch) -> None:
        _seed_run("org-a", RUN_A, pod=POD_A)
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
        assert sb["question_id"] == "t1:fan/out"
        assert sb["question_title"] == "question for org-a"

    @pytest.mark.asyncio
    async def test_waiting_pod_reports_its_reason(self) -> None:
        core = _fake_core([_pod(POD_A, phase="Pending", waiting="ImagePullBackOff")])
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        with _patch_k8s_view(core):
            body = await view.inventory()
        (sb,) = body["sandboxes"]
        assert sb["phase"] == "pending"
        assert sb["reason"] == "ImagePullBackOff"
        assert sb["ready"] is False

    @pytest.mark.asyncio
    async def test_missing_namespace_is_an_empty_list_not_an_error(self) -> None:
        core = _fake_core()
        core.list_namespaced_pod = AsyncMock(side_effect=RuntimeError("(404) Not Found"))
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        with _patch_k8s_view(core):
            body = await view.inventory()
        assert body["sandboxes"] == [] and body["live"] is True

    @pytest.mark.asyncio
    async def test_no_cluster_degrades_honestly(self) -> None:
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")

        async def _no_client(self):
            return None, ""

        with patch.object(sandboxes.KubernetesSandboxView, "_connect", _no_client):
            body = await view.inventory()
        assert body["live"] is False
        assert "unavailable" in body["message"].lower()
        assert body["sandboxes"] == []

    @pytest.mark.asyncio
    async def test_only_eval_pods_are_listed(self) -> None:
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


# ─── Events ──────────────────────────────────────────────────────────────────


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
    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_event_messages_are_redacted(self) -> None:
        core = _fake_core(events=[_event("Failed", f"pull failed, auth {OAUTH_TOKEN}")])
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        with _patch_k8s_view(core):
            body = await view.events(POD_A)
        assert OAUTH_TOKEN not in json.dumps(body)

    @pytest.mark.asyncio
    async def test_docker_says_events_are_unsupported_rather_than_faking_them(self) -> None:
        view = sandboxes.DockerSandboxView(EvalRunSettings(), org_id="org-a")
        try:
            body = await view.events("abcdefabcdef")
        finally:
            await view.aclose()
        assert body["supported"] is False
        assert body["events"] == []


# ─── Cross-org isolation ─────────────────────────────────────────────────────


class TestCrossOrgIsolation:
    @pytest.mark.asyncio
    async def test_each_org_reads_its_own_namespace(self) -> None:
        """Namespace resolution is the boundary — the org id must reach it."""
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

    def test_sandbox_index_is_per_org(self) -> None:
        _seed_run("org-a", RUN_A, pod=POD_A)
        _seed_run("org-b", RUN_B, pod=POD_B)
        assert POD_A in runner.sandbox_index("org-a")
        assert POD_A not in runner.sandbox_index("org-b")
        assert POD_B not in runner.sandbox_index("org-a")

    def test_a_foreign_pod_gets_no_attribution(self) -> None:
        """org-b's index must not name org-a's question, even by pod name."""
        _seed_run("org-a", RUN_A, pod=POD_A)
        assert runner.sandbox_index("org-b") == {}

    def test_docker_ownership_requires_a_run_in_this_orgs_root(self) -> None:
        _seed_run("org-a", RUN_A, pod="aaaaaaaaaaaa")
        view_a = sandboxes.DockerSandboxView(EvalRunSettings(), org_id="org-a")
        view_b = sandboxes.DockerSandboxView(EvalRunSettings(), org_id="org-b")
        labels = {"signalpilot.eval": "1", "signalpilot.eval.run": RUN_A}
        assert view_a._owns(labels) is True
        assert view_b._owns(labels) is False
        assert view_a._owns({"signalpilot.eval": "1"}) is False

    def test_foreign_run_progress_is_404(self) -> None:
        _seed_run("org-a", RUN_A, pod=POD_A)
        with _client("org-b") as client:
            assert client.get(f"/api/evals/runs/{RUN_A}/progress").status_code == 404
        with _client("org-a") as client:
            assert client.get(f"/api/evals/runs/{RUN_A}/progress").status_code == 200

    def test_inventory_route_passes_the_callers_org(self) -> None:
        captured: list[str] = []

        class _View:
            async def inventory(self):
                return {"backend": "kubernetes", "live": True, "sandboxes": [], "namespace": "", "message": "", "supports_live_logs": True}

            async def aclose(self):
                return None

        def _factory(org_id: str):
            captured.append(org_id)
            return _View()

        with patch.object(sandboxes, "get_sandbox_view", _factory):
            with _client("org-b") as client:
                assert client.get("/api/evals/sandboxes").status_code == 200
        assert captured == ["org-b"]


# ─── No secret leakage ───────────────────────────────────────────────────────


class TestNoSecretLeakage:
    """Every sandbox response, over a pod whose spec and messages carry real
    credentials. Nothing but the digest may survive."""

    _SECRETS = (OAUTH_TOKEN, ANTHROPIC_KEY, MCP_KEY_B64, "sp-live-secret")

    def _assert_clean(self, body: str) -> None:
        for secret in self._SECRETS:
            assert secret not in body, f"leaked {secret[:12]}… in response"

    @pytest.mark.asyncio
    async def test_inventory_never_echoes_the_pod_spec(self) -> None:
        core = _fake_core([_pod(POD_A, phase="Pending", waiting="ImagePullBackOff")])
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        with _patch_k8s_view(core):
            body = await view.inventory()
        self._assert_clean(json.dumps(body))
        assert "env" not in json.dumps(body)

    @pytest.mark.asyncio
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

    def test_run_progress_carries_no_credentials(self) -> None:
        _seed_run("org-a", RUN_A, pod=POD_A)
        with _client("org-a") as client:
            body = client.get(f"/api/evals/runs/{RUN_A}/progress").text
        self._assert_clean(body)


# ─── Live log stream ─────────────────────────────────────────────────────────


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
        # The view is released even on a clean end — no leaked cluster client.
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

    @pytest.mark.asyncio
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
        assert len(out) == 3  # two chunks then the cap, third never read
        kwargs = core.read_namespaced_pod_log.await_args.kwargs
        assert kwargs["follow"] is True
        assert kwargs["tail_lines"] == 25
        assert kwargs["_preload_content"] is False

    @pytest.mark.asyncio
    async def test_kubernetes_stream_ends_when_the_pod_exits(self) -> None:
        core = _fake_core()
        core.read_namespaced_pod_log = AsyncMock(return_value=_FakeLogResponse([b"done\n"]))
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        out = []
        with _patch_k8s_view(core):
            async for item in view.stream_logs(POD_A, tail_lines=10):
                out.append(item)
        assert out == [("log", "done\n"), ("end", "sandbox-exited")]

    @pytest.mark.asyncio
    async def test_attach_failure_is_reported_not_raised(self) -> None:
        core = _fake_core()
        core.read_namespaced_pod_log = AsyncMock(side_effect=RuntimeError("(404) pod gone"))
        view = sandboxes.KubernetesSandboxView(EvalRunSettings(), org_id="org-a")
        out = []
        with _patch_k8s_view(core):
            async for item in view.stream_logs(POD_A, tail_lines=10):
                out.append(item)
        assert out[-1] == ("end", "attach-failed")

    @pytest.mark.asyncio
    async def test_docker_stream_refuses_a_container_this_org_does_not_own(self) -> None:
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


# ─── Run progress ────────────────────────────────────────────────────────────


class TestRunProgress:
    def test_progress_reports_position_and_elapsed(self) -> None:
        _seed_run("org-a", RUN_A, pod=POD_A)
        with _client("org-a") as client:
            body = client.get(f"/api/evals/runs/{RUN_A}/progress").json()
        assert body["phase"] == "question"
        assert body["index"] == 0
        assert body["total"] == 2
        assert body["done"] == 0
        assert body["question_id"] == "t1:fan/out"
        assert body["elapsed_s"] is not None and body["elapsed_s"] >= 0
        assert body["sandbox"]["name"] == POD_A

    def test_progress_of_a_run_without_markers_still_answers(self) -> None:
        run_dir = runner.eval_root("org-a") / RUN_A
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run.json").write_text(
            json.dumps({"id": RUN_A, "status": "completed", "questions": [{"id": "q", "status": "done"}]}),
            encoding="utf-8",
        )
        with _client("org-a") as client:
            body = client.get(f"/api/evals/runs/{RUN_A}/progress").json()
        assert body["phase"] == "finished"
        assert body["done"] == 1
        assert body["elapsed_s"] is None

    def test_bad_run_id_is_rejected(self) -> None:
        with _client("org-a") as client:
            assert client.get("/api/evals/runs/not-a-run/progress").status_code == 400


# ─── Staff gate ──────────────────────────────────────────────────────────────

_SANDBOX_ROUTES = [
    "/api/evals/sandboxes",
    f"/api/evals/sandboxes/{POD_A}/events",
    f"/api/evals/sandboxes/{POD_A}/logs/stream",
    f"/api/evals/runs/{RUN_A}/progress",
]


class TestStaffGate:
    @pytest.mark.parametrize("path", _SANDBOX_ROUTES)
    def test_org_admin_is_refused(self, path: str) -> None:
        with _client("org-a", user_id="tenant-org-admin") as client:
            assert client.get(path).status_code == 403

    @pytest.mark.parametrize("path", _SANDBOX_ROUTES)
    def test_unset_admin_ids_refuses_every_caller(self, path: str, monkeypatch) -> None:
        monkeypatch.delenv("SP_ADMIN_USER_IDS", raising=False)
        get_governance_settings.cache_clear()
        with _client("org-a", user_id="user_2clerkid") as client:
            assert client.get(path).status_code == 403


# ─── Runner progress markers ─────────────────────────────────────────────────


class TestRunnerMarkers:
    def test_sandbox_index_covers_setup_containers(self) -> None:
        run_dir = runner.eval_root("org-a") / RUN_A
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run.json").write_text(
            json.dumps(
                {
                    "id": RUN_A,
                    "questions": [],
                    "setup": [{"state": "broken-1", "sandbox": {"name": POD_B, "backend": "kubernetes"}}],
                }
            ),
            encoding="utf-8",
        )
        entry = runner.sandbox_index("org-a")[POD_B]
        assert entry["kind"] == "setup"
        assert entry["setup_state"] == "broken-1"

    def test_marker_writes_do_not_disturb_existing_run_fields(self) -> None:
        run = {"id": RUN_A, "status": "running", "questions": []}
        (runner.eval_root("org-a") / RUN_A).mkdir(parents=True, exist_ok=True)
        runner._mark_progress("org-a", run, phase="question", index=2)
        stored = runner.read_run("org-a", RUN_A)
        assert stored["status"] == "running"
        assert stored["progress"]["phase"] == "question"
        assert stored["progress"]["index"] == 2
        assert stored["progress"]["updated_at"]

    @pytest.mark.asyncio
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
            image="img", command=["true"], env={}, secret_env={}, labels={},
            memory_bytes=1, nano_cpus=1, timeout_seconds=1, on_start=boom,
        )
        _notify_start(spec, {"backend": "docker", "name": "abc"})  # must not raise


# ─── Markers written by a real run ───────────────────────────────────────────


class TestProgressDuringARun:
    """Drives _execute_run_inner against a fake backend: the panel can only show
    in-flight work if the markers land while the question is still running."""

    @pytest.fixture
    def eval_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        repo = tmp_path / "projects" / "set-1"
        (repo / "prompts").mkdir(parents=True)
        (repo / "eval.json").write_text(
            json.dumps(
                {
                    "name": "set-1",
                    "questions": [
                        {"id": "q1", "title": "first", "checks": [{"name": "answer", "value": 42}]},
                        {"id": "q2", "title": "second", "checks": [{"name": "answer", "value": 7}]},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (repo / "prompts" / "q1.txt").write_text("how many?", encoding="utf-8")
        (repo / "prompts" / "q2.txt").write_text("how many now?", encoding="utf-8")
        monkeypatch.setenv("SP_EVAL_PROJECTS_DIR", str(tmp_path / "projects"))
        monkeypatch.setenv("SP_EVAL_RUNNER_IMAGE", "sp-eval-runner:latest")
        get_eval_run_settings.cache_clear()
        runner.save_eval_config("org-a", {"repo_url": str(repo), "model": "sonnet"})
        return repo

    @pytest.mark.asyncio
    async def test_markers_land_while_the_question_is_running(self, eval_repo) -> None:
        observed: list[dict] = []

        class _Backend:
            def __init__(self) -> None:
                self.n = 0

            async def run(self, spec):
                self.n += 1
                spec.on_start({"backend": "kubernetes", "name": f"sp-eval-{self.n:012x}", "namespace": "sp-nb-org-a"})
                # State as a live viewer would read it mid-question.
                observed.append(runner.run_progress(runner.read_run("org-a", run["id"])))
                return 0, '{"type":"result","result":"42"}'

            async def aclose(self) -> None:
                return None

        run = runner.create_run("org-a", doc_ids=["d1"], doc_titles=["Doc"], question_ids=None)
        with patch("gateway.evals.runner.get_execution_backend", lambda *a, **k: _Backend()):
            await runner._execute_run_inner("org-a", run["id"])

        assert [o["phase"] for o in observed] == ["question", "question"]
        assert [o["index"] for o in observed] == [0, 1]
        assert [o["question_id"] for o in observed] == ["q1", "q2"]
        assert observed[0]["total"] == 2
        assert observed[0]["sandbox"]["name"] == "sp-eval-000000000001"
        assert observed[1]["done"] == 1  # the first question finished before the second started

        final = runner.read_run("org-a", run["id"])
        assert final["status"] == "completed"
        assert runner.run_progress(final)["phase"] == "finished"
        # Both sandboxes stay attributable after the fact.
        index = runner.sandbox_index("org-a")
        assert index["sp-eval-000000000001"]["question_id"] == "q1"
        assert index["sp-eval-000000000002"]["question_id"] == "q2"

    @pytest.mark.asyncio
    async def test_markers_from_one_org_are_invisible_to_another(self, eval_repo) -> None:
        class _Backend:
            async def run(self, spec):
                spec.on_start({"backend": "kubernetes", "name": POD_A, "namespace": "sp-nb-org-a"})
                return 0, "42"

            async def aclose(self) -> None:
                return None

        run = runner.create_run("org-a", doc_ids=["d1"], doc_titles=["Doc"], question_ids=None)
        with patch("gateway.evals.runner.get_execution_backend", lambda *a, **k: _Backend()):
            await runner._execute_run_inner("org-a", run["id"])

        assert POD_A in runner.sandbox_index("org-a")
        assert runner.sandbox_index("org-b") == {}
        with _client("org-b") as client:
            assert client.get(f"/api/evals/runs/{run['id']}/progress").status_code == 404
