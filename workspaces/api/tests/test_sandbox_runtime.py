"""Tests for sandbox_runtime.py — factory, validate_available, exec argv assembly."""

from __future__ import annotations

import asyncio
import asyncio.subprocess
from pathlib import Path, PurePosixPath
from unittest.mock import AsyncMock

import pytest

from workspaces_api.agent.sandbox_runtime import (
    Mount,
    NoneRuntime,
    RunscRuntime,
    build_runtime,
)
from workspaces_api.config import Settings
from workspaces_api.errors import SandboxRuntimeUnavailable


def _settings(**overrides) -> Settings:
    base = {
        "SP_DEPLOYMENT_MODE": "local",
        "CLAUDE_CODE_OAUTH_TOKEN": "tok",
        "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    }
    base.update(overrides)
    return Settings.model_validate(base)


class TestSandboxRuntimeFactory:
    def test_none_returns_none_runtime(self) -> None:
        s = _settings(SP_SANDBOX_RUNTIME="none")
        rt = build_runtime(s)
        assert isinstance(rt, NoneRuntime)
        assert rt.name == "none"

    def test_runsc_returns_runsc_runtime(self) -> None:
        s = _settings(SP_SANDBOX_RUNTIME="runsc")
        rt = build_runtime(s)
        assert isinstance(rt, RunscRuntime)
        assert rt.name == "runsc"

    def test_runc_raises_sandbox_runtime_unavailable(self) -> None:
        s = _settings(SP_SANDBOX_RUNTIME="runc")
        with pytest.raises(SandboxRuntimeUnavailable, match="unknown SP_SANDBOX_RUNTIME"):
            build_runtime(s)

    def test_runsc_binary_from_settings(self) -> None:
        s = _settings(SP_SANDBOX_RUNTIME="runsc", SP_RUNSC_BINARY="/custom/runsc")
        rt = build_runtime(s)
        assert isinstance(rt, RunscRuntime)
        assert rt._binary == Path("/custom/runsc")


class TestNoneRuntime:
    @pytest.mark.asyncio
    async def test_validate_available_is_noop(self) -> None:
        rt = NoneRuntime()
        await rt.validate_available()  # Must not raise

    @pytest.mark.asyncio
    async def test_exec_calls_exec_fn_with_argv(self) -> None:
        calls: list[dict] = []

        async def fake_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append({"args": list(args), "kwargs": kwargs})
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            return mock_proc

        rt = NoneRuntime(_exec_fn=fake_exec)
        mounts: list[Mount] = []
        await rt.exec(
            argv=["python3", "server.py"],
            env={"FOO": "bar"},
            cwd=Path("/tmp"),
            mounts=mounts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        assert len(calls) == 1
        assert calls[0]["args"] == ["python3", "server.py"]
        assert calls[0]["kwargs"]["env"] == {"FOO": "bar"}


class TestRunscRuntime:
    @pytest.mark.asyncio
    async def test_validate_available_succeeds_with_bin_true(self) -> None:
        rt = RunscRuntime(binary=Path("/bin/true"))
        await rt.validate_available()  # /bin/true exits 0

    @pytest.mark.asyncio
    async def test_validate_available_raises_when_binary_missing(self) -> None:
        rt = RunscRuntime(binary=Path("/nonexistent/runsc"))
        with pytest.raises(SandboxRuntimeUnavailable, match="not found"):
            await rt.validate_available()

    @pytest.mark.asyncio
    async def test_exec_argv_no_mounts(self) -> None:
        """runsc do with no mounts: just ['runsc', 'do', '--', *user_argv]."""
        calls: list[list[str]] = []

        async def fake_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(list(args))
            mock_proc = AsyncMock()
            return mock_proc

        rt = RunscRuntime(binary=Path("/usr/local/bin/runsc"), _exec_fn=fake_exec)
        await rt.exec(
            argv=["python3", "server.py"],
            env={},
            cwd=Path("/tmp/run"),
            mounts=[],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        assert len(calls) == 1
        argv = calls[0]
        assert argv[0] == "/usr/local/bin/runsc"
        assert argv[1] == "do"
        assert "--" in argv
        sep_idx = argv.index("--")
        assert argv[sep_idx + 1:] == ["python3", "server.py"]

    @pytest.mark.asyncio
    async def test_exec_argv_with_writable_mount(self) -> None:
        """Writable mount becomes -volume SRC:DST (no :ro suffix)."""
        calls: list[list[str]] = []

        async def fake_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(list(args))
            mock_proc = AsyncMock()
            return mock_proc

        rt = RunscRuntime(binary=Path("/usr/local/bin/runsc"), _exec_fn=fake_exec)
        mounts = [
            Mount(
                source=Path("/tmp/run123/home/.signalpilot/resume"),
                target=PurePosixPath("/home/agentuser/.signalpilot/resume"),
                readonly=False,
            ),
        ]
        await rt.exec(
            argv=["python3", "server.py"],
            env={},
            cwd=Path("/tmp/run123/home"),
            mounts=mounts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        argv = calls[0]
        assert "-volume" in argv
        vol_idx = argv.index("-volume")
        vol_spec = argv[vol_idx + 1]
        assert "/tmp/run123/home/.signalpilot/resume" in vol_spec
        assert "/home/agentuser/.signalpilot/resume" in vol_spec
        # No :ro suffix for writable mount
        assert ":ro" not in vol_spec

    @pytest.mark.asyncio
    async def test_exec_double_dash_before_user_argv(self) -> None:
        """-- separator must appear before the user argv."""
        calls: list[list[str]] = []

        async def fake_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(list(args))
            mock_proc = AsyncMock()
            return mock_proc

        rt = RunscRuntime(binary=Path("/runsc"), _exec_fn=fake_exec)
        mount = Mount(
            source=Path("/src"),
            target=PurePosixPath("/dst"),
            readonly=False,
        )
        await rt.exec(
            argv=["python3", "server.py"],
            env={},
            cwd=Path("/cwd"),
            mounts=[mount],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        argv = calls[0]
        sep_idx = argv.index("--")
        assert argv[sep_idx + 1:] == ["python3", "server.py"]
        # -volume must appear before --
        vol_idx = argv.index("-volume")
        assert vol_idx < sep_idx

    @pytest.mark.asyncio
    async def test_exec_env_passed_through_unchanged(self) -> None:
        """env dict must reach the exec_fn unmodified."""
        received_env: dict[str, str] = {}

        async def fake_exec(*args, env=None, **kwargs):  # type: ignore[no-untyped-def]
            if env:
                received_env.update(env)
            mock_proc = AsyncMock()
            return mock_proc

        rt = RunscRuntime(binary=Path("/runsc"), _exec_fn=fake_exec)
        test_env = {"FOO": "bar", "AGENT_SECRET": "xyz"}
        await rt.exec(
            argv=["python3"],
            env=test_env,
            cwd=Path("/cwd"),
            mounts=[],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        assert received_env == test_env

    def test_runsc_runtime_name_is_runsc_constant(self) -> None:
        """RunscRuntime.name must always be 'runsc' regardless of constructor args."""
        rt = RunscRuntime(binary=Path("/x"))
        assert rt.name == "runsc"
