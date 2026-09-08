"""Opt in with SP_AGENT_DOCKER_SMOKE=1 after building signalpilot-agent:mcp-test."""
import base64
import json
import os
import subprocess
import time
import uuid

import pytest

from gateway.agent_execution.artifacts import pack, read_archive


@pytest.mark.skipif(os.getenv("SP_AGENT_DOCKER_SMOKE") != "1", reason="requires built Docker agent image")
def test_real_container_entrypoint_archive_and_watchdog(tmp_path):
    image = "signalpilot-agent:mcp-test"
    name = "sp-agent-smoke-" + uuid.uuid4().hex

    def docker(*args):
        result = subprocess.run(["docker", *args], text=True, capture_output=True)
        if result.returncode:
            pytest.fail(result.stdout + result.stderr)
        return result.stdout

    started = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "read", "name": "Read", "input": {"file_path": "/work/project/my_orders.sql"}},
        {"type": "tool_use", "id": "query", "name": "mcp__signalpilot__query", "input": {"sql": "SECRET_QUERY"}},
        {"type": "text", "text": "SECRET_TRANSCRIPT"},
    ]}}
    completed = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "read", "content": "SECRET_FILE_CONTENT"},
        {"type": "tool_result", "tool_use_id": "query", "content": "SECRET_QUERY_RESULT"},
    ]}}
    fake = ("import sys,json,pathlib,time;sys.stdin.read();"
            "print(" + repr(json.dumps(started)) + ",flush=True);time.sleep(2);"
            "print(" + repr(json.dumps(completed)) + ",flush=True);"
            "pathlib.Path('my_orders.sql').write_text('select 2\\n');"
            "print(json.dumps({'type':'result','structured_output':"
            "{'status':'completed','summary':'Done','question':None,'verification':['fixture']}}))")
    script = ("import sys;sys.path.insert(0,'/opt/agent');"
              "import entrypoint;entrypoint.command=lambda payload:['python3','-c'," + repr(fake) + "];entrypoint.main()")
    payload = json.dumps({
        "snapshot_url": "data:application/gzip;base64," + base64.b64encode(pack({"my_orders.sql": b"select 1\n"})).decode(), "model": "fake", "max_turns": 2,
        "mcp_url": "https://example.invalid/mcp", "mcp_token": "fake", "api_key": "fake",
        "task": "fixture", "timeout_seconds": 1,
    })
    try:
        docker("run", "-di", "--rm", "--name", name, "--read-only", "--network", "none",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--pids-limit", "256",
               "--memory", "2g", "--tmpfs", "/work:rw,size=512m,mode=1777",
               "--tmpfs", "/tmp:rw,size=128m,mode=1777", image, "python3", "-c", script)
        attach = subprocess.Popen(["docker", "attach", name], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        attach.stdin.write((payload + "\n").encode())
        attach.stdin.close()
        deadline = time.monotonic() + 15
        observed_before_result = False
        while time.monotonic() < deadline:
            logs = docker("logs", name)
            if '"stage": "local_tool"' in logs and '"type": "result"' not in logs:
                observed_before_result = True
            if '"type": "result"' in logs:
                break
            time.sleep(0.2)
        else:
            pytest.fail("No result from container: " + logs)
        output = subprocess.check_output(["docker", "exec", name, "cat", "/work/output.tgz"])
        assert read_archive(output) == {"my_orders.sql": b"select 2\n"}
        assert "fake" not in logs
        assert "SECRET" not in logs
        assert "mcp__" not in logs
        assert observed_before_result
        local_events = [json.loads(line) for line in logs.splitlines() if '"stage": "local_tool"' in line]
        assert [e["status"] for e in local_events] == ["started", "completed"]
        # Simulate gateway death: no delete request. PID1's own deadline and
        # Docker AutoRemove must dispose of the container and its tmpfs.
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            if name not in docker("ps", "-a", "--filter", "name=" + name, "--format", "{{.Names}}"):
                break
            time.sleep(0.5)
        else:
            pytest.fail("Container survived independent watchdog")
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        if "attach" in locals():
            attach.wait(timeout=10)
