"""Tests for the sandbox VM MCP tools (capability gating + behavior)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from gateway.mcp.context import (
    mcp_capabilities_var,
    mcp_execution_identity_var,
    mcp_scopes_var,
)
from gateway.mcp.tools import sandbox_vm
from gateway.mcp.tools.sandbox_vm import (
    SANDBOX_CAPABILITY,
    release_session_sandbox,
    sandbox_exec,
    sandbox_read_file,
    sandbox_write_file,
)
from gateway.sandbox_runtime import ExecResult, SandboxSpec


@dataclass
class FakeRuntime:
    provider: str = "fake"
    created: list[SandboxSpec] = field(default_factory=list)
    execs: list[tuple[str, str, dict]] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)
    destroyed: list[str] = field(default_factory=list)
    next_exec: ExecResult = ExecResult(returncode=0, stdout="ok", stderr="")

    async def create(self, spec: SandboxSpec) -> str:
        self.created.append(spec)
        return f"sbx-{len(self.created)}"

    async def exec(self, sandbox_id, command, *, cwd=None, env=None, timeout_seconds=None):
        self.execs.append((sandbox_id, command, {"cwd": cwd, "timeout_seconds": timeout_seconds}))
        return self.next_exec

    async def write_file(self, sandbox_id, path, content) -> None:
        self.files[path] = content

    async def read_file(self, sandbox_id, path):
        return self.files.get(path)

    async def destroy(self, sandbox_id) -> None:
        self.destroyed.append(sandbox_id)


@pytest.fixture()
def runtime(monkeypatch: pytest.MonkeyPatch) -> FakeRuntime:
    fake = FakeRuntime()
    monkeypatch.setattr(sandbox_vm, "get_sandbox_runtime", lambda: fake)
    sandbox_vm._session_sandboxes.clear()
    yield fake
    sandbox_vm._session_sandboxes.clear()


@pytest.fixture()
def improvement_identity():
    scope_token = mcp_scopes_var.set(["read", "query", "execute"])
    cap_token = mcp_capabilities_var.set([SANDBOX_CAPABILITY, "query:read"])
    id_token = mcp_execution_identity_var.set("chat:run-42")
    yield
    mcp_scopes_var.reset(scope_token)
    mcp_capabilities_var.reset(cap_token)
    mcp_execution_identity_var.reset(id_token)


@pytest.mark.asyncio
class TestCapabilityGate:
    async def test_denied_without_capability(self, runtime: FakeRuntime) -> None:
        scope_token = mcp_scopes_var.set(["read", "query", "execute"])
        cap_token = mcp_capabilities_var.set(["query:read"])
        id_token = mcp_execution_identity_var.set("chat:run-42")
        try:
            for call in (
                sandbox_exec(command="echo hi"),
                sandbox_write_file(path="/x", content="y"),
                sandbox_read_file(path="/x"),
            ):
                result = await call
                assert "not enabled for this session" in result
        finally:
            mcp_scopes_var.reset(scope_token)
            mcp_capabilities_var.reset(cap_token)
            mcp_execution_identity_var.reset(id_token)
        assert runtime.created == []

    async def test_denied_without_capability_context(self, runtime: FakeRuntime) -> None:
        result = await sandbox_exec(command="echo hi")
        assert result.startswith("Error:")
        assert runtime.created == []

    async def test_denied_without_chat_identity(self, runtime: FakeRuntime) -> None:
        scope_token = mcp_scopes_var.set(["read", "query", "execute"])
        cap_token = mcp_capabilities_var.set([SANDBOX_CAPABILITY])
        id_token = mcp_execution_identity_var.set(None)
        try:
            result = await sandbox_exec(command="echo hi")
            assert "execution identity" in result
        finally:
            mcp_scopes_var.reset(scope_token)
            mcp_capabilities_var.reset(cap_token)
            mcp_execution_identity_var.reset(id_token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("improvement_identity")
class TestSandboxTools:
    async def test_exec_creates_sandbox_once_and_formats_output(self, runtime: FakeRuntime) -> None:
        runtime.next_exec = ExecResult(returncode=0, stdout="hello", stderr="warn")
        first = await sandbox_exec(command="echo hello")
        second = await sandbox_exec(command="echo again", cwd="/proj", timeout_seconds=60)
        assert len(runtime.created) == 1
        spec = runtime.created[0]
        assert spec.tags["sp_execution_identity"] == "chat:run-42"
        assert "exit_code: 0" in first
        assert "stdout:\nhello" in first
        assert "stderr:\nwarn" in first
        assert runtime.execs[1][2] == {"cwd": "/proj", "timeout_seconds": 60.0}
        assert runtime.execs[0][2]["timeout_seconds"] == 300.0
        assert second.startswith("exit_code")

    async def test_exec_nonzero_exit_reported(self, runtime: FakeRuntime) -> None:
        runtime.next_exec = ExecResult(returncode=2, stdout="", stderr="boom")
        result = await sandbox_exec(command="false")
        assert "exit_code: 2" in result
        assert "boom" in result

    async def test_exec_rejects_empty_and_oversized_commands(self, runtime: FakeRuntime) -> None:
        assert (await sandbox_exec(command="  ")).startswith("Error")
        assert (await sandbox_exec(command="x" * 20_001)).startswith("Error")
        assert runtime.created == []

    async def test_exec_output_is_clipped(self, runtime: FakeRuntime) -> None:
        runtime.next_exec = ExecResult(returncode=0, stdout="a" * 40_000, stderr="")
        result = await sandbox_exec(command="cat big")
        assert "truncated" in result
        assert len(result) < 40_000

    async def test_write_and_read_roundtrip(self, runtime: FakeRuntime) -> None:
        wrote = await sandbox_write_file(path="/work/a.txt", content="content")
        assert "Wrote 7 bytes" in wrote
        read = await sandbox_read_file(path="/work/a.txt")
        assert read == "content"

    async def test_write_requires_absolute_path(self, runtime: FakeRuntime) -> None:
        assert (await sandbox_write_file(path="rel.txt", content="x")).startswith("Error")
        assert (await sandbox_read_file(path="rel.txt")).startswith("Error")

    async def test_read_missing_file(self, runtime: FakeRuntime) -> None:
        result = await sandbox_read_file(path="/absent")
        assert "does not exist" in result

    async def test_read_non_utf8(self, runtime: FakeRuntime) -> None:
        runtime.files["/bin.dat"] = b"\xff\xfe\x00"
        # bind session so read hits the same sandbox
        await sandbox_exec(command="true")
        result = await sandbox_read_file(path="/bin.dat")
        assert "not UTF-8" in result

    async def test_release_destroys_and_forgets(self, runtime: FakeRuntime) -> None:
        await sandbox_exec(command="true")
        assert sandbox_vm._session_sandboxes.get("chat:run-42") == "sbx-1"
        await release_session_sandbox("chat:run-42")
        assert runtime.destroyed == ["sbx-1"]
        assert "chat:run-42" not in sandbox_vm._session_sandboxes
        # release of unknown identity is a no-op
        await release_session_sandbox("chat:other")
        assert runtime.destroyed == ["sbx-1"]

    async def test_separate_identities_get_separate_sandboxes(self, runtime: FakeRuntime) -> None:
        await sandbox_exec(command="true")
        token = mcp_execution_identity_var.set("chat:run-99")
        try:
            await sandbox_exec(command="true")
        finally:
            mcp_execution_identity_var.reset(token)
        assert len(runtime.created) == 2
        assert sandbox_vm._session_sandboxes["chat:run-42"] != sandbox_vm._session_sandboxes["chat:run-99"]


class TestRegistration:
    def test_tools_have_execute_scope(self) -> None:
        from gateway.mcp.audit import MCP_TOOL_SCOPES, STANDALONE_CHAT_TOOL_ALLOWLIST

        for name in ("sandbox_exec", "sandbox_write_file", "sandbox_read_file"):
            assert MCP_TOOL_SCOPES[name] == "execute"
            assert name in STANDALONE_CHAT_TOOL_ALLOWLIST
