"""Run inside Linux with docker.sock mounted; no paid model invocation.

From the repository root, after building Dockerfile.agent:

    docker network create sp-agent-smoke
    docker run --rm --user 0 \\
      -v /var/run/docker.sock:/var/run/docker.sock \\
      -v "$PWD/signalpilot/gateway:/repo:ro" \\
      -e SP_AGENT_IMAGE=signalpilot-agent:mcp-test \\
      -e SP_AGENT_DOCKER_NETWORK=sp-agent-smoke \\
      -e PYTHONPATH=/repo:/tmp/driverlibs signalpilot-agent:mcp-test \\
      sh -c 'pip install --quiet --target /tmp/driverlibs httpx anyio && python3 /repo/tests/agent_docker_driver.py'
    docker network rm sp-agent-smoke

On PowerShell replace the repo volume's $PWD with the absolute checkout path.
The driver requires Docker admin access and a disposable test network.
"""
import asyncio
import base64
import os
import sys
import types
import uuid

# The driver needs only the pure path validator, not workspace-store DB clients.
workspace = types.ModuleType("gateway.workspace_store")
workspace.__path__ = ["/repo/gateway/workspace_store"]
sys.modules["gateway.workspace_store"] = workspace

async def main():
    from gateway.agent_execution.artifacts import pack, read_archive
    from gateway.agent_execution.docker import DockerAgent

    runtime = DockerAgent()
    original_post = runtime.client.post
    fake = ("import sys,json,pathlib;sys.stdin.read();"
            "pathlib.Path('my_orders.sql').write_text('select 2\\n');"
            "print(json.dumps({'type':'result','structured_output':"
            "{'status':'completed','summary':'Done','question':None,'verification':['fixture']}}))")
    script = ("import sys;sys.path.insert(0,'/opt/agent');"
              "import entrypoint;entrypoint.command=lambda payload:['python3','-c'," + repr(fake) + "];entrypoint.main()")

    async def post(url, **kwargs):
        if url == "/containers/create":
            kwargs["json"]["Cmd"] = ["python3", "-c", script]
        return await original_post(url, **kwargs)

    runtime.client.post = post

    async def event(value):
        print(value)

    async def cancelled():
        return False

    result, data = await runtime.run(run_id=uuid.uuid4().hex, payload={
        "snapshot_url": "data:application/gzip;base64," + base64.b64encode(pack({"my_orders.sql": b"select 1\n"})).decode(),
        "model": "fake", "max_turns": 2, "timeout_seconds": 20,
        "mcp_url": "https://example.invalid/mcp", "mcp_token": "fake", "api_key": "fake", "task": "fixture",
    }, on_event=event, is_cancelled=cancelled)
    assert result["status"] == "completed"
    assert read_archive(data) == {"my_orders.sql": b"select 2\n"}
    print("Full Docker Engine runtime smoke passed")


if __name__ == "__main__":
    asyncio.run(main())
