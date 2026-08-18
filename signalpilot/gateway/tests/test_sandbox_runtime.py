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


class FakeSandbox:
    def __init__(self, name: str = "sbx_123") -> None:
        self.name = name
        self.fs = FakeFs()
        self.destroyed = False
        self.run_calls: list[dict] = []
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

    def destroy(self) -> None:
        self.destroyed = True


@dataclass
class FakeOperation:
    sandbox: FakeSandbox

    def __enter__(self) -> FakeSandbox:
        return self.sandbox


@dataclass
class FakeSdk:
    sandbox: FakeSandbox = field(default_factory=FakeSandbox)
    create_calls: list[dict] = field(default_factory=list)
    known_ids: set[str] | None = None

    def create_sandbox(self, **kwargs) -> FakeOperation:
        self.create_calls.append(kwargs)
        return FakeOperation(self.sandbox)

    def get_sandbox(self, *, name: str, project_id: str | None = None) -> FakeSandbox:
        if self.known_ids is not None and name not in self.known_ids:
            raise LookupError(name)
        return self.sandbox


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
