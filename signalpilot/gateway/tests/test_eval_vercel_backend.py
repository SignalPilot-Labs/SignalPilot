"""Tests for the Vercel eval execution backend (gateway/evals/backends.py).

Covers selection via SP_EVAL_EXECUTION_BACKEND, credential gating, the
bootstrap/exec/destroy lifecycle against a fake runtime, secret handling
(exec env only, never the creation spec), timeout mapping, and the
bind-mount refusal shared with the Kubernetes backend.
"""

from __future__ import annotations

import pytest

from gateway.config.evals import EvalRunSettings
from gateway.config.sandbox_runtime import reset_sandbox_runtime_settings
from gateway.evals.backends import (
    TIMED_OUT,
    ContainerRun,
    DockerBackend,
    VercelBackend,
    get_execution_backend,
)
from gateway.sandbox_runtime.base import ExecResult

_DIGEST_IMAGE = "reg.example.com/eval-runner@sha256:" + "b" * 64


def _settings(**overrides) -> EvalRunSettings:
    base = {
        "SP_EVAL_RUNNER_IMAGE": _DIGEST_IMAGE,
        "SP_EVAL_MCP_URL": "https://gateway.example.com/mcp",
        "SP_EVAL_TIMEOUT_SECONDS": "600",
        "SP_EVAL_EXECUTION_BACKEND": "vercel",
    }
    base.update(overrides)
    return EvalRunSettings(**base)


def _spec(**overrides) -> ContainerRun:
    kwargs = {
        "image": "sp-eval-runner:latest",
        "command": ["sh", "-lc", "echo hi"],
        "env": {"SP_PROMPT": "how many orders?", "SP_MODEL": "sonnet"},
        "secret_env": {
            "SP_MCP_JSON_B64": "eyJ4IjoxfQ==",
            "CLAUDE_CODE_OAUTH_TOKEN": "sk-oauth-supersecret",
        },
        "labels": {"run": "run-20260101-010101-aaaaaa"},
        "memory_bytes": 2 * 1024 * 1024 * 1024,
        "nano_cpus": 2_000_000_000,
        "timeout_seconds": 600,
    }
    kwargs.update(overrides)
    return ContainerRun(**kwargs)


@pytest.fixture
def vercel_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VERCEL_TOKEN", "vc-token")
    monkeypatch.setenv("VERCEL_TEAM_ID", "team_x")
    monkeypatch.setenv("VERCEL_PROJECT_ID", "prj_x")
    reset_sandbox_runtime_settings()
    yield
    reset_sandbox_runtime_settings()


class FakeRuntime:
    """Scripted stand-in for VercelSandboxRuntime."""

    def __init__(self, exec_results: list[ExecResult]):
        self._exec_results = list(exec_results)
        self.created: list[object] = []
        self.execs: list[dict] = []
        self.destroyed: list[str] = []

    async def create(self, spec) -> str:
        self.created.append(spec)
        return "sbx-fake-1"

    async def exec(self, sandbox_id, command, *, cwd=None, env=None, timeout_seconds=None):
        self.execs.append(
            {"sandbox_id": sandbox_id, "command": command, "env": env, "timeout": timeout_seconds}
        )
        return self._exec_results.pop(0)

    async def read_file(self, sandbox_id, path):
        return None

    async def destroy(self, sandbox_id) -> None:
        self.destroyed.append(sandbox_id)


def _backend(fake: FakeRuntime, settings: EvalRunSettings | None = None) -> VercelBackend:
    backend = VercelBackend(settings or _settings(), org_id="org_1")
    backend._make_runtime = lambda: fake  # type: ignore[method-assign]
    return backend


class TestSelection:
    def test_vercel_backend_selected_when_configured(self, monkeypatch, vercel_env):
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        backend = get_execution_backend(_settings(), org_id="org_1")
        assert isinstance(backend, VercelBackend)

    def test_vercel_overrides_local_docker(self, monkeypatch, vercel_env):
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        backend = get_execution_backend(_settings(), org_id="org_1")
        assert isinstance(backend, VercelBackend)

    def test_default_backend_unchanged(self, monkeypatch):
        # Cloud without an explicit vercel opt-in refuses (the Kubernetes
        # backend was retired with the EKS estate); local still gets Docker.
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        with pytest.raises(RuntimeError, match="SP_EVAL_EXECUTION_BACKEND=vercel"):
            get_execution_backend(_settings(SP_EVAL_EXECUTION_BACKEND=""), org_id="org_1")
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        backend = get_execution_backend(
            _settings(SP_EVAL_EXECUTION_BACKEND=""), org_id="org_1"
        )
        assert isinstance(backend, DockerBackend)

    def test_unknown_backend_value_is_rejected(self):
        with pytest.raises(ValueError, match="SP_EVAL_EXECUTION_BACKEND"):
            _settings(SP_EVAL_EXECUTION_BACKEND="fargate")

    def test_missing_vercel_credentials_fail_loudly(self, monkeypatch):
        for name in ("VERCEL_TOKEN", "VERCEL_TEAM_ID", "VERCEL_PROJECT_ID"):
            monkeypatch.delenv(name, raising=False)
        reset_sandbox_runtime_settings()
        try:
            with pytest.raises(RuntimeError, match="VERCEL_TOKEN"):
                VercelBackend(_settings(), org_id="org_1")
        finally:
            reset_sandbox_runtime_settings()


class TestLifecycle:
    async def test_bootstrap_then_command_then_destroy(self, vercel_env):
        fake = FakeRuntime(
            [ExecResult(0, "bootstrapped", ""), ExecResult(0, "task output", "warn")]
        )
        exit_code, logs = await _backend(fake).run(_spec())
        assert exit_code == 0
        assert "task output" in logs and "warn" in logs
        assert len(fake.execs) == 2
        assert "claude" in fake.execs[0]["command"]  # bootstrap installs the CLI
        # The task command is tee'd to the live-tail log file with its exit
        # code preserved through the pipe.
        task_cmd = fake.execs[1]["command"]
        assert "echo hi" in task_cmd
        assert "tee /tmp/sp-eval-output.log" in task_cmd
        assert "pipefail" in task_cmd
        assert fake.destroyed == ["sbx-fake-1"]

    async def test_secrets_ride_exec_env_not_creation_spec(self, vercel_env):
        fake = FakeRuntime([ExecResult(0, "", ""), ExecResult(0, "", "")])
        await _backend(fake).run(_spec())
        created = fake.created[0]
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in (created.env or {})
        assert fake.execs[1]["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-oauth-supersecret"
        assert fake.execs[1]["env"]["SP_MODEL"] == "sonnet"

    async def test_bootstrap_failure_reports_without_running_task(self, vercel_env):
        fake = FakeRuntime([ExecResult(1, "", "npm exploded")])
        exit_code, logs = await _backend(fake).run(_spec())
        assert exit_code == 1
        assert "bootstrap failed" in logs and "npm exploded" in logs
        assert len(fake.execs) == 1
        assert fake.destroyed == ["sbx-fake-1"]

    async def test_sandbox_destroyed_when_exec_raises(self, vercel_env):
        class ExplodingRuntime(FakeRuntime):
            async def exec(self, *a, **kw):
                raise RuntimeError("provider hiccup")

        fake = ExplodingRuntime([])
        with pytest.raises(RuntimeError, match="provider hiccup"):
            await _backend(fake).run(_spec())
        assert fake.destroyed == ["sbx-fake-1"]

    async def test_timeout_maps_to_timed_out(self, vercel_env, monkeypatch):
        fake = FakeRuntime([ExecResult(0, "", ""), ExecResult(137, "killed", "")])
        backend = _backend(fake, _settings())
        # Simulate the elapsed clock crossing the task timeout.
        import gateway.evals.backends as backends_mod

        times = iter([0.0, 700.0])

        class FakeLoop:
            def time(self):
                return next(times)

        monkeypatch.setattr(
            backends_mod.asyncio, "get_event_loop", lambda: FakeLoop()
        )
        exit_code, _ = await backend.run(_spec())
        assert exit_code == TIMED_OUT

    async def test_binds_are_refused(self, vercel_env):
        fake = FakeRuntime([])
        with pytest.raises(RuntimeError, match="bind mounts"):
            await _backend(fake).run(_spec(binds=["/host:/repo:ro"]))
        assert fake.created == []


class TestLiveTail:
    """The panel's Vercel log tail polls the tee'd file inside the sandbox."""

    def _view(self, monkeypatch, reads):
        """A VercelSandboxView whose runtime serves `reads` in sequence.

        Each entry is bytes (file contents), None (file not written yet), or
        an exception instance to raise.
        """
        from gateway.evals import sandboxes as sandboxes_mod
        from gateway.evals.sandboxes import VercelSandboxView

        monkeypatch.setattr(sandboxes_mod, "_VERCEL_LOG_POLL_SECONDS", 0.0)
        view = VercelSandboxView(_settings(), org_id="org_1")

        class TailRuntime:
            def __init__(self):
                self._reads = list(reads)

            async def read_file(self, sandbox_id, path):
                item = self._reads.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

        async def owns(name):
            return True

        monkeypatch.setattr(view, "_make_runtime", lambda: TailRuntime())
        monkeypatch.setattr(view, "_owns", owns)
        return view

    async def _collect(self, view, tail_lines=200):
        return [event async for event in view.stream_logs("gold-planned-chicken-DbtqQZ", tail_lines=tail_lines)]

    async def test_incremental_tail_ends_on_sandbox_exit(self, monkeypatch, vercel_env):
        from gateway.sandbox_runtime.base import SandboxNotFound

        events = await self._collect(
            self._view(
                monkeypatch,
                [None, b"line one\n", b"line one\nline two\n", SandboxNotFound("gone")],
            )
        )
        kinds = [k for k, _ in events]
        assert kinds[0] == "info"  # bootstrap notice while the file is absent
        logs = "".join(text for kind, text in events if kind == "log")
        assert logs == "line one\nline two\n"  # each chunk emitted exactly once
        assert events[-1] == ("end", "sandbox-exited")

    async def test_first_read_honors_tail_lines(self, monkeypatch, vercel_env):
        from gateway.sandbox_runtime.base import SandboxNotFound

        backlog = b"".join(b"line %d\n" % i for i in range(50))
        events = await self._collect(
            self._view(monkeypatch, [backlog, SandboxNotFound("gone")]), tail_lines=2
        )
        logs = "".join(text for kind, text in events if kind == "log")
        assert logs == "line 48\nline 49\n"

    async def test_foreign_sandbox_is_refused(self, monkeypatch, vercel_env):
        view = self._view(monkeypatch, [b"secret log\n"])

        async def not_ours(name):
            return False

        monkeypatch.setattr(view, "_owns", not_ours)
        events = await self._collect(view)
        assert events[-1] == ("end", "attach-failed")
        assert not any(kind == "log" for kind, _ in events)
