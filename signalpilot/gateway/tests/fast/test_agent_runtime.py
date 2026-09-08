import asyncio
import io
import json
import tarfile

import httpx
import pytest

from gateway.agent_execution.artifacts import pack, read_archive
from gateway.agent_execution.docker import DockerAgent
from gateway.agent_execution.entrypoint import LocalActivity, collect, command, public_path


@pytest.mark.parametrize("path", ["/etc/passwd", "../secret", "models/../../secret", ".env",
                                 "models/.env.production", "models/a\nsecret", "C:\\secret", "https://secret"])
def test_activity_hides_nonproject_or_sensitive_paths(path):
    assert public_path(path) is None


def test_activity_only_reports_observed_local_tool_lifecycle():
    activity = LocalActivity()
    assert activity.consume({"type": "assistant", "message": {"content": [
        {"type": "thinking", "thinking": "SECRET"},
        {"type": "text", "text": "SECRET"},
        {"type": "tool_use", "id": "mcp", "name": "mcp__signalpilot__query", "input": {"sql": "SECRET"}},
    ]}}) == []
    started = activity.consume({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "edit", "name": "Edit", "input": {
            "file_path": "/work/project/models/my_orders.sql", "old_string": "SECRET", "new_string": "SECRET"}},
        {"type": "tool_use", "id": "bash", "name": "Bash", "input": {"command": "SECRET", "description": "tests passed"}},
    ]}})
    assert [e["status"] for e in started] == ["started", "started"]
    assert started[0]["path"] == "models/my_orders.sql"
    assert "path" not in started[1]
    assert "SECRET" not in json.dumps(started)
    completed = activity.consume({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "edit", "content": "SECRET"},
        {"type": "tool_result", "tool_use_id": "bash", "is_error": True, "content": "SECRET"},
    ]}})
    assert [e["status"] for e in completed] == ["completed", "failed"]
    assert "SECRET" not in json.dumps(completed)
    assert activity.consume({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "unobserved", "content": "SECRET"},
    ]}}) == []


@pytest.mark.parametrize("name,kind", [("../escape", tarfile.REGTYPE), ("x\ny", tarfile.REGTYPE),
                                       ("link", tarfile.SYMTYPE), ("link", tarfile.LNKTYPE)])
def test_archive_rejects_unsafe_entries(name, kind):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as archive:
        item = tarfile.TarInfo(name)
        item.type = kind
        archive.addfile(item)
    with pytest.raises(ValueError):
        read_archive(buf.getvalue())


def test_collect_roundtrip_and_secret_exclusion(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "my_orders.sql").write_bytes(b"select 1\n")
    (tmp_path / ".env").write_text("SECRET=not-for-publication")
    assert read_archive(collect(tmp_path)) == {"models/my_orders.sql": b"select 1\n"}


def test_command_does_not_contain_credentials():
    cmd = command({"model": "test-model", "max_turns": 3, "api_key": "secret"})
    assert "secret" not in cmd
    assert "--strict-mcp-config" in cmd


def artifact():
    buf = io.BytesIO()
    data = pack({"my_orders.sql": b"select 1\n"})
    with tarfile.open(fileobj=buf, mode="w") as archive:
        item = tarfile.TarInfo("output.tgz")
        item.size = len(data)
        archive.addfile(item, io.BytesIO(data))
    return buf.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("events,succeeds", [
    (b'{"type":"result","result":{"status":"completed"}}\n', True),
    (b'{"type":"progress","message":"Working"}\n', False),
])
async def test_container_result_or_eof_always_removes_container(monkeypatch, events, succeeds):
    monkeypatch.setenv("SP_AGENT_IMAGE", "agent:test")
    monkeypatch.setenv("SP_AGENT_DOCKER_NETWORK", "agent-network")
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/containers/create":
            config = json.loads(request.content)
            assert config["HostConfig"]["AutoRemove"] is True
            assert config["HostConfig"]["ReadonlyRootfs"] is True
            return httpx.Response(201, json={"Id": "container"})
        if request.url.path.endswith("/logs"):
            return httpx.Response(200, content=b"\x01\x00\x00\x00" + len(events).to_bytes(4, "big") + events)
        if request.url.path.endswith("/exec"):
            return httpx.Response(201, json={"Id": "output"})
        if request.url.path == "/exec/output/start":
            data = pack({"my_orders.sql": b"select 1\n"})
            return httpx.Response(200, content=b"\x01\x00\x00\x00" + len(data).to_bytes(4, "big") + data)
        if request.method == "GET":
            return httpx.Response(200, json={"ExitCode": 0})
        return httpx.Response(204)

    async def callback(*args):
        return False

    runtime = DockerAgent(httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker"))
    runtime._launch = callback
    run = runtime.run(run_id="test", payload={"timeout_seconds": 2}, on_event=callback, is_cancelled=callback)
    if succeeds:
        result, snapshot = await run
        assert result["status"] == "completed"
        assert read_archive(snapshot) == {"my_orders.sql": b"select 1\n"}
    else:
        with pytest.raises(RuntimeError):
            await run
    assert calls[-1] == ("DELETE", "/containers/container")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cancel", "log_failure", "external_cancel", "heartbeat"])
async def test_active_container_cancel_and_log_error_are_not_lost(monkeypatch, mode):
    monkeypatch.setenv("SP_AGENT_IMAGE", "agent:test")
    monkeypatch.setenv("SP_AGENT_DOCKER_NETWORK", "agent-network")
    removed = asyncio.Event()
    streaming = asyncio.Event()
    events = []

    class Pending(httpx.AsyncByteStream):
        async def __aiter__(self):
            streaming.set()
            if mode == "log_failure":
                raise httpx.ReadError("disconnected")
            await asyncio.Event().wait()
            yield b""

    def handler(request):
        if request.url.path == "/containers/create":
            return httpx.Response(201, json={"Id": "container"})
        if request.url.path.endswith("/logs"):
            return httpx.Response(200, stream=Pending())
        if request.method == "DELETE":
            removed.set()
        return httpx.Response(204)

    async def progress(event):
        events.append(event)

    async def cancelled():
        return mode == "cancel" or (mode == "heartbeat" and bool(events))

    runtime = DockerAgent(httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker"))
    async def launch(*args):
        pass
    runtime._launch = launch
    if mode == "heartbeat":
        runtime.HEARTBEAT_SECONDS = 0
    task = asyncio.create_task(runtime.run(run_id="test", payload={"timeout_seconds": 2},
                                          on_event=progress, is_cancelled=cancelled))
    if mode == "external_cancel":
        await streaming.wait()
        task.cancel()
    with pytest.raises(httpx.ReadError if mode == "log_failure" else asyncio.CancelledError):
        await asyncio.wait_for(task, 3)
    assert removed.is_set()
    if mode == "heartbeat":
        assert events == [{"type": "progress", "stage": "heartbeat", "status": "running",
                           "message": "Waiting for agent activity", "elapsed_seconds": 0}]
