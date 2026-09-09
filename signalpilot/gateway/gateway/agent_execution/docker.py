"""Docker execution for MCP agents, with bounded live output and guaranteed cleanup."""
import asyncio
import json
import os
from collections.abc import Awaitable, Callable

import anyio
import httpx

from .artifacts import MAX_BYTES


class DockerAgent:
    HEARTBEAT_SECONDS = 20

    def __init__(self, client=None):
        self.client = client or httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=os.getenv("SP_AGENT_DOCKER_SOCKET", "/var/run/docker.sock")),
            base_url="http://docker", timeout=30)

    async def _launch(self, cid, payload):
        """Docker's archive API rejects tmpfs writes on a readonly rootfs.

        Attach stdin over the Engine's HTTP upgrade instead. Credentials never
        enter container metadata, exec argv, or a persistent host file.
        """
        socket_path = os.getenv("SP_AGENT_DOCKER_SOCKET", "/var/run/docker.sock")
        async with await anyio.connect_unix(socket_path) as stream:
            with anyio.fail_after(30):
                request = (f"POST /containers/{cid}/attach?stream=1&stdin=1&stdout=0&stderr=0 HTTP/1.1\r\n"
                           "Host: docker\r\nConnection: Upgrade\r\nUpgrade: tcp\r\nContent-Length: 0\r\n\r\n")
                await stream.send(request.encode("ascii"))
                headers = bytearray()
                while b"\r\n\r\n" not in headers:
                    headers.extend(await stream.receive(4096))
                    if len(headers) > 16384:
                        raise RuntimeError("Invalid Docker attach response")
                if not headers.startswith(b"HTTP/1.1 101 "):
                    raise RuntimeError("Docker stdin attach failed")
                await stream.send(json.dumps(payload).encode() + b"\n")

    async def run(self, *, run_id: str, payload: dict, on_event: Callable[[dict], Awaitable[None]], is_cancelled: Callable[[], Awaitable[bool]]):
        image = os.environ["SP_AGENT_IMAGE"]
        network = os.environ["SP_AGENT_DOCKER_NETWORK"]
        if network in {"host", "bridge", "none"}:
            raise ValueError("Configure a dedicated agent network")
        cid = None
        try:
            created = await self.client.post("/containers/create", params={"name": "sp-agent-" + run_id}, json={
                "Image": image, "Cmd": ["python3", "/opt/agent/entrypoint.py"],
                "User": "10002:10002", "Tty": False, "WorkingDir": "/work",
                "OpenStdin": True, "StdinOnce": True,
                "Env": ["HOME=/work", "CLAUDE_CONFIG_DIR=/work/.claude"],
                "Labels": {"signalpilot.agent": "1", "signalpilot.agent.run": run_id},
                "HostConfig": {"NetworkMode": network, "Memory": 2 * 1024**3, "NanoCpus": 2_000_000_000,
                    "ReadonlyRootfs": True, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"],
                    "AutoRemove": True, "PidsLimit": 256, "Tmpfs": {"/work": "rw,size=512m,mode=1777", "/tmp": "rw,size=128m,mode=1777"}},
            })
            created.raise_for_status()
            cid = created.json()["Id"]
            started = await self.client.post(f"/containers/{cid}/start")
            started.raise_for_status()
            await self._launch(cid, payload)
            result = None
            ready = asyncio.Event()
            began = asyncio.get_running_loop().time()
            last_activity = began

            async def logs():
                nonlocal result, last_activity
                total = 0
                pending = b""
                frames = b""
                async with self.client.stream("GET", f"/containers/{cid}/logs",
                    params={"follow": "1", "stdout": "1", "stderr": "1"}, timeout=None) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        frames += chunk
                        if total > 4 * 1024 * 1024:
                            raise ValueError("Agent event output limit exceeded")
                        # Non-TTY Docker logs multiplex stdout/stderr with an
                        # eight-byte header. TTY mode would echo secret stdin.
                        while len(frames) >= 8:
                            length = int.from_bytes(frames[4:8], "big")
                            if length > 256 * 1024:
                                raise ValueError("Agent frame exceeds limit")
                            if len(frames) < length + 8:
                                break
                            if frames[0] == 1:
                                pending += frames[8:8 + length]
                            frames = frames[8 + length:]
                        if len(pending) > 256 * 1024:
                            raise ValueError("Agent event exceeds limit")
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            try:
                                event = json.loads(line)
                            except (ValueError, UnicodeError):
                                continue
                            if not isinstance(event, dict):
                                continue
                            if event.get("type") == "result":
                                result = event.get("result")
                                ready.set()
                            elif event.get("type") == "progress":
                                await on_event(event)
                                last_activity = asyncio.get_running_loop().time()

            async def monitor():
                nonlocal last_activity
                while True:
                    if await is_cancelled():
                        raise asyncio.CancelledError()
                    now = asyncio.get_running_loop().time()
                    if now - last_activity >= self.HEARTBEAT_SECONDS:
                        await on_event({"type": "progress", "stage": "heartbeat", "status": "running",
                                        "message": "Waiting for agent activity", "elapsed_seconds": int(now - began)})
                        last_activity = now
                    await asyncio.sleep(1)

            log_task = asyncio.create_task(logs())
            cancel_task = asyncio.create_task(monitor())
            wait_task = asyncio.create_task(ready.wait())
            try:
                async with asyncio.timeout(payload["timeout_seconds"]):
                    done, _ = await asyncio.wait([log_task, cancel_task, wait_task], return_when=asyncio.FIRST_COMPLETED)
                    if cancel_task in done:
                        await cancel_task
                    if log_task in done:
                        await log_task
                    if result is None:
                        raise RuntimeError("Agent container did not produce a successful result")
            finally:
                for task in (log_task, cancel_task, wait_task):
                    task.cancel()
                await asyncio.gather(log_task, cancel_task, wait_task, return_exceptions=True)
            output = bytearray()
            executable = await self.client.post(f"/containers/{cid}/exec", json={
                "Cmd": ["cat", "/work/output.tgz"], "AttachStdout": True,
                "AttachStderr": True, "Tty": False, "User": "10002:10002"})
            executable.raise_for_status()
            exec_id = executable.json()["Id"]
            frames = bytearray()
            async with self.client.stream("POST", f"/exec/{exec_id}/start", json={"Detach": False, "Tty": False}) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if await is_cancelled():
                        raise asyncio.CancelledError()
                    frames.extend(chunk)
                    while len(frames) >= 8:
                        length = int.from_bytes(frames[4:8], "big")
                        if length > MAX_BYTES:
                            raise ValueError("Container artifact frame exceeds limit")
                        if len(frames) < length + 8:
                            break
                        if frames[0] != 1:
                            raise RuntimeError("Container artifact download failed")
                        output.extend(frames[8:8 + length])
                        del frames[:8 + length]
                        if len(output) > MAX_BYTES:
                            raise ValueError("Container artifact exceeds size limit")
            inspected = await self.client.get(f"/exec/{exec_id}/json")
            inspected.raise_for_status()
            if frames or inspected.json().get("ExitCode") != 0:
                raise RuntimeError("Incomplete container artifact")
            return result, bytes(output)
        finally:
            async def cleanup():
                try:
                    if cid:
                        response = await self.client.delete(f"/containers/{cid}", params={"force": "1", "v": "1"})
                        if response.status_code not in (204, 404):
                            response.raise_for_status()
                finally:
                    await self.client.aclose()
            cleanup_task = asyncio.create_task(cleanup())
            with anyio.CancelScope(shield=True):
                try:
                    await asyncio.shield(cleanup_task)
                except asyncio.CancelledError:
                    await cleanup_task
                    raise
