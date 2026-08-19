"""Unit tests for the sandbox runtime abstraction and its Vercel provider.

The provider tests run against a fake SDK injected through
`gateway.sandbox_runtime.vercel._sdk`; the live suite at the bottom exercises
a real Vercel sandbox and only runs when VERCEL_TOKEN is present.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import pytest

from gateway.config.sandbox_runtime import (
    SandboxRuntimeSettings,
    get_sandbox_runtime_settings,
    reset_sandbox_runtime_settings,
)
from gateway.sandbox_runtime import (
    ExecResult,
    GitCheckout,
    SandboxNotFound,
    SandboxRuntimeError,
    SandboxSpec,
    get_sandbox_runtime,
)
from gateway.sandbox_runtime.vercel import VercelSandboxRuntime


# ---------------------------------------------------------------------------
# Fake SDK
# ---------------------------------------------------------------------------


@dataclass
class FakeCompleted:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class FakeFs:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.dirs: set[str] = {"/", "/tmp"}

    def exists(self, path: str) -> bool:
        return path in self.files or path in self.dirs

    def mkdir(self, path: str) -> None:
        self.dirs.add(path)

    def write_bytes(self, path: str, content: bytes) -> None:
        self.files[path] = content

    def read_bytes(self, path: str) -> bytes:
        return self.files[path]


@dataclass
class FakeRoute:
    port: int
    url: str


@dataclass
class FakeProcess:
    id: str = "proc_1"


@dataclass
class FakeSnapshot:
    id: str = "snap_1"


class FakeSandbox:
    def __init__(self, name: str = "sbx_123") -> None:
        self.name = name
        self.fs = FakeFs()
        self.destroyed = False
        self.stopped = False
        self.status = "running"
        self.tags: dict[str, str] = {}
        self.current_snapshot_id: str | None = None
        self.routes: tuple[FakeRoute, ...] = ()
        self.run_calls: list[dict] = []
        self.create_process_calls: list[dict] = []
        self.extend_calls: list = []
        self.snapshot_calls: list = []
        self.next_result = FakeCompleted(returncode=0, stdout="out", stderr="")

    def run_process(self, cmd, args=None, *, cwd=None, env=None, kill_after=None, capture_output=False):
        self.run_calls.append(
            {
                "cmd": cmd,
                "args": args,
                "cwd": cwd,
                "env": env,
                "kill_after": kill_after,
                "capture_output": capture_output,
            }
        )
        return self.next_result

    def create_process(self, cmd, args=None, *, cwd=None, env=None, stdout=None, stderr=None):
        self.create_process_calls.append(
            {"cmd": cmd, "args": args, "cwd": cwd, "env": env}
        )
        return FakeProcess(id=f"proc_{len(self.create_process_calls)}")

    def extend_execution_time_limit(self, duration):
        self.extend_calls.append(duration)
        return self

    def snapshot(self, *, expiration=None):
        self.snapshot_calls.append(expiration)
        snapshot = FakeSnapshot(id=f"snap_{len(self.snapshot_calls)}")
        self.current_snapshot_id = snapshot.id
        return snapshot

    def stop(self) -> None:
        self.stopped = True
        self.status = "stopped"

    def destroy(self) -> None:
        self.destroyed = True


@dataclass
class FakeOperation:
    sandbox: FakeSandbox
    entered: bool = False

    def __enter__(self) -> FakeSandbox:
        self.entered = True
        return self.sandbox


@dataclass
class FakeSdk:
    sandbox: FakeSandbox = field(default_factory=FakeSandbox)
    create_calls: list[dict] = field(default_factory=list)
    resume_calls: list[str] = field(default_factory=list)
    known_ids: set[str] | None = None
    fleet: list[FakeSandbox] = field(default_factory=list)

    def create_sandbox(self, **kwargs) -> FakeOperation:
        self.create_calls.append(kwargs)
        return FakeOperation(self.sandbox)

    def get_sandbox(self, *, name: str, project_id: str | None = None) -> FakeSandbox:
        if self.known_ids is not None and name not in self.known_ids:
            raise LookupError(name)
        return self.sandbox

    def resume_sandbox(self, *, name: str, project_id: str | None = None) -> FakeOperation:
        if self.known_ids is not None and name not in self.known_ids:
            raise LookupError(name)
        self.resume_calls.append(name)
        self.sandbox.status = "running"
        return FakeOperation(self.sandbox)

    def query_sandboxes(self, *, project_id: str | None = None, **kwargs):
        return iter(self.fleet or [self.sandbox])


@pytest.fixture()
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> FakeSdk:
    sdk = FakeSdk()
    monkeypatch.setattr("gateway.sandbox_runtime.vercel._sdk", lambda: sdk)
    return sdk


# ---------------------------------------------------------------------------
# Settings + factory
# ---------------------------------------------------------------------------


class TestSettings:
    def test_disabled_without_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("VERCEL_TOKEN", "VERCEL_TEAM_ID", "VERCEL_PROJECT_ID"):
            monkeypatch.delenv(name, raising=False)
        settings = SandboxRuntimeSettings()
        assert settings.provider == "vercel"
        assert settings.enabled is False

    def test_enabled_with_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VERCEL_TOKEN", "t")
        monkeypatch.setenv("VERCEL_TEAM_ID", "team")
        monkeypatch.setenv("VERCEL_PROJECT_ID", "prj")
        assert SandboxRuntimeSettings().enabled is True

    def test_partial_credentials_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VERCEL_TOKEN", "t")
        monkeypatch.delenv("VERCEL_TEAM_ID", raising=False)
        monkeypatch.setenv("VERCEL_PROJECT_ID", "prj")
        assert SandboxRuntimeSettings().enabled is False

    def test_unknown_provider_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SP_SANDBOX_RUNTIME_PROVIDER", "aws")
        monkeypatch.setenv("VERCEL_TOKEN", "t")
        monkeypatch.setenv("VERCEL_TEAM_ID", "team")
        monkeypatch.setenv("VERCEL_PROJECT_ID", "prj")
        assert SandboxRuntimeSettings().enabled is False

    def test_settings_cache_reset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_sandbox_runtime_settings()
        monkeypatch.setenv("SP_SANDBOX_RUNTIME_TIME_LIMIT", "300")
        try:
            assert get_sandbox_runtime_settings().time_limit_seconds == 300
        finally:
            reset_sandbox_runtime_settings()


class TestFactory:
    def test_raises_when_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("VERCEL_TOKEN", "VERCEL_TEAM_ID", "VERCEL_PROJECT_ID"):
            monkeypatch.delenv(name, raising=False)
        reset_sandbox_runtime_settings()
        try:
            with pytest.raises(SandboxRuntimeError, match="No sandbox runtime"):
                get_sandbox_runtime()
        finally:
            reset_sandbox_runtime_settings()

    def test_returns_vercel_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VERCEL_TOKEN", "t")
        monkeypatch.setenv("VERCEL_TEAM_ID", "team")
        monkeypatch.setenv("VERCEL_PROJECT_ID", "prj_test")
        reset_sandbox_runtime_settings()
        try:
            runtime = get_sandbox_runtime()
            assert isinstance(runtime, VercelSandboxRuntime)
            assert runtime.provider == "vercel"
        finally:
            reset_sandbox_runtime_settings()


# ---------------------------------------------------------------------------
# Vercel provider behavior (fake SDK)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVercelRuntime:
    async def test_create_passes_spec(self, fake_sdk: FakeSdk) -> None:
        runtime = VercelSandboxRuntime(project_id="prj_x")
        spec = SandboxSpec(
            time_limit_seconds=600,
            env={"A": "1"},
            tags={"sp_run": "run-1"},
        )
        sandbox_id = await runtime.create(spec)
        assert sandbox_id == "sbx_123"
        (call,) = fake_sdk.create_calls
        assert call["project_id"] == "prj_x"
        assert call["execution_time_limit"] == 600
        assert call["env"] == {"A": "1"}
        assert call["tags"] == {"sp_run": "run-1"}
        assert call["source"] is None
        assert call["destroy"] is False

    async def test_create_maps_git_source(self, fake_sdk: FakeSdk) -> None:
        pytest.importorskip("vercel")
        runtime = VercelSandboxRuntime(project_id="prj_x")
        spec = SandboxSpec(
            git=GitCheckout(
                url="https://github.com/org/repo.git",
                revision="abc123",
                username="x-access-token",
                password="tok",
            )
        )
        await runtime.create(spec)
        source = fake_sdk.create_calls[0]["source"]
        assert source.url == "https://github.com/org/repo.git"
        assert source.revision == "abc123"
        assert source.username == "x-access-token"
        assert source.password == "tok"
        assert source.depth == 1

    async def test_exec_shell_wrapping_and_result(self, fake_sdk: FakeSdk) -> None:
        runtime = VercelSandboxRuntime()
        fake_sdk.sandbox.next_result = FakeCompleted(returncode=2, stdout="o", stderr="e")
        result = await runtime.exec("sbx_123", "dbt parse", cwd="/proj", timeout_seconds=30)
        assert result == ExecResult(returncode=2, stdout="o", stderr="e")
        assert result.ok is False
        (call,) = fake_sdk.sandbox.run_calls
        assert call["cmd"] == "bash"
        assert call["args"] == ["-c", "dbt parse"]
        assert call["cwd"] == "/proj"
        assert call["kill_after"] == 30
        assert call["capture_output"] is True

    async def test_exec_ok_result(self, fake_sdk: FakeSdk) -> None:
        runtime = VercelSandboxRuntime()
        result = await runtime.exec("sbx_123", "true")
        assert result.ok is True

    async def test_write_file_creates_parent(self, fake_sdk: FakeSdk) -> None:
        runtime = VercelSandboxRuntime()
        await runtime.write_file("sbx_123", "/work/reports/out.html", b"<html/>")
        fs = fake_sdk.sandbox.fs
        assert "/work/reports" in fs.dirs
        assert fs.files["/work/reports/out.html"] == b"<html/>"

    async def test_read_file_missing_returns_none(self, fake_sdk: FakeSdk) -> None:
        runtime = VercelSandboxRuntime()
        assert await runtime.read_file("sbx_123", "/nope") is None

    async def test_read_file_roundtrip(self, fake_sdk: FakeSdk) -> None:
        runtime = VercelSandboxRuntime()
        fake_sdk.sandbox.fs.files["/data.csv"] = b"a,b"
        assert await runtime.read_file("sbx_123", "/data.csv") == b"a,b"

    async def test_attach_unknown_id_raises_not_found(self, fake_sdk: FakeSdk) -> None:
        fake_sdk.known_ids = {"other"}
        runtime = VercelSandboxRuntime()
        with pytest.raises(SandboxNotFound):
            await runtime.exec("sbx_123", "true")

    async def test_destroy_is_idempotent(self, fake_sdk: FakeSdk) -> None:
        fake_sdk.known_ids = set()  # nothing attachable
        runtime = VercelSandboxRuntime()
        await runtime.destroy("sbx_gone")  # must not raise

    async def test_destroy_destroys(self, fake_sdk: FakeSdk) -> None:
        runtime = VercelSandboxRuntime()
        await runtime.destroy("sbx_123")
        assert fake_sdk.sandbox.destroyed is True


# ---------------------------------------------------------------------------
# Runtime v2 surface (server shape: ports, processes, snapshot/resume, list)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVercelRuntimeV2:
    async def test_create_passes_server_shape_fields(self, fake_sdk: FakeSdk) -> None:
        pytest.importorskip("vercel")
        runtime = VercelSandboxRuntime(project_id="prj_x")
        spec = SandboxSpec(
            time_limit_seconds=1800,
            ports=(2718,),
            image="registry.vercel.com/org/sp-notebook@sha256:abc",
            vcpus=2,
            memory_mb=4096,
            persistent=True,
            egress_allow_hosts=("gateway.signalpilot.ai", "pypi.org"),
            tags={"sp-purpose": "notebook"},
        )
        await runtime.create(spec)
        (call,) = fake_sdk.create_calls
        assert call["ports"] == [2718]
        assert call["image"] == "registry.vercel.com/org/sp-notebook@sha256:abc"
        assert call["persistent"] is True
        assert call["resources"].vcpus == 2
        assert call["resources"].memory == 4096
        policy = call["network_policy"]
        assert policy.mode == "custom"
        assert set(policy.allow) == {"gateway.signalpilot.ai", "pypi.org"}

    async def test_empty_egress_allowlist_denies_all(self, fake_sdk: FakeSdk) -> None:
        pytest.importorskip("vercel")
        runtime = VercelSandboxRuntime()
        await runtime.create(SandboxSpec(egress_allow_hosts=()))
        assert fake_sdk.create_calls[0]["network_policy"].mode == "deny-all"

    async def test_none_egress_keeps_provider_default(self, fake_sdk: FakeSdk) -> None:
        runtime = VercelSandboxRuntime()
        await runtime.create(SandboxSpec())
        assert fake_sdk.create_calls[0]["network_policy"] is None

    async def test_start_process_is_detached_and_returns_id(self, fake_sdk: FakeSdk) -> None:
        runtime = VercelSandboxRuntime()
        process_id = await runtime.start_process(
            "sbx_123", "sp edit --port 2718", cwd="/workspace", env={"SP_X": "1"}
        )
        assert process_id == "proc_1"
        (call,) = fake_sdk.sandbox.create_process_calls
        assert call["args"] == ["-c", "sp edit --port 2718"]
        assert call["cwd"] == "/workspace"
        assert fake_sdk.sandbox.run_calls == []  # never the blocking path

    async def test_routes_maps_port_to_public_url(self, fake_sdk: FakeSdk) -> None:
        fake_sdk.sandbox.routes = (FakeRoute(port=2718, url="https://sbx-abc.vercel.run"),)
        runtime = VercelSandboxRuntime()
        assert await runtime.routes("sbx_123") == {2718: "https://sbx-abc.vercel.run"}

    async def test_extend_time_limit_floors_at_one_second(self, fake_sdk: FakeSdk) -> None:
        runtime = VercelSandboxRuntime()
        await runtime.extend_time_limit("sbx_123", 900)
        await runtime.extend_time_limit("sbx_123", 0)
        assert fake_sdk.sandbox.extend_calls == [900, 1]

    async def test_snapshot_then_resume_roundtrip(self, fake_sdk: FakeSdk) -> None:
        runtime = VercelSandboxRuntime()
        snapshot_id = await runtime.snapshot("sbx_123", expiration_seconds=86400)
        assert snapshot_id == "snap_1"
        assert fake_sdk.sandbox.snapshot_calls == [86400]
        await runtime.stop("sbx_123")
        assert fake_sdk.sandbox.stopped is True
        await runtime.resume("sbx_123")
        assert fake_sdk.resume_calls == ["sbx_123"]
        assert fake_sdk.sandbox.status == "running"

    async def test_resume_unknown_raises_not_found(self, fake_sdk: FakeSdk) -> None:
        fake_sdk.known_ids = set()
        runtime = VercelSandboxRuntime()
        with pytest.raises(SandboxNotFound):
            await runtime.resume("sbx_gone")

    async def test_list_filters_by_tags(self, fake_sdk: FakeSdk) -> None:
        notebook = FakeSandbox(name="sbx_nb")
        notebook.tags = {"sp-purpose": "notebook", "org": "o1"}
        evaluation = FakeSandbox(name="sbx_eval")
        evaluation.tags = {"sp-eval": "1"}
        fake_sdk.fleet = [notebook, evaluation]
        runtime = VercelSandboxRuntime()
        rows = await runtime.list(tags={"sp-purpose": "notebook"})
        assert [row.sandbox_id for row in rows] == ["sbx_nb"]
        assert rows[0].status == "running"
        everything = await runtime.list()
        assert {row.sandbox_id for row in everything} == {"sbx_nb", "sbx_eval"}


# ---------------------------------------------------------------------------
# Live tests (real Vercel sandbox) — gated on credentials
# ---------------------------------------------------------------------------

_LIVE = bool(os.getenv("VERCEL_TOKEN") and os.getenv("VERCEL_TEAM_ID") and os.getenv("VERCEL_PROJECT_ID"))


@pytest.mark.skipif(not _LIVE, reason="VERCEL_TOKEN/TEAM_ID/PROJECT_ID not set")
@pytest.mark.asyncio
class TestVercelRuntimeLive:
    async def test_full_lifecycle(self) -> None:
        reset_sandbox_runtime_settings()
        runtime = get_sandbox_runtime()
        sandbox_id = await runtime.create(SandboxSpec(time_limit_seconds=120, tags={"sp_purpose": "unit-test"}))
        try:
            result = await runtime.exec(sandbox_id, "echo live-ok")
            assert result.ok and "live-ok" in result.stdout
            await runtime.write_file(sandbox_id, "/tmp/sp-test/x.txt", b"roundtrip")
            assert await runtime.read_file(sandbox_id, "/tmp/sp-test/x.txt") == b"roundtrip"
            assert await runtime.read_file(sandbox_id, "/tmp/absent") is None
        finally:
            await runtime.destroy(sandbox_id)
            reset_sandbox_runtime_settings()
