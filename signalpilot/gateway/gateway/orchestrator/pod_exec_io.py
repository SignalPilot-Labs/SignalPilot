"""Pod exec I/O — SOLE authorized caller of kubernetes pods/exec.

This module is the ONLY file that may import or call:
    kubernetes_asyncio.stream.WsApiClient
    connect_get_namespaced_pod_exec
    kubernetes_asyncio.stream

All other gateway code that needs to execute commands in a pod must go
through exec_command_in_pod — never by calling the K8s exec API directly.
This is enforced by an AST test (C4):
    tests/test_pod_exec_caller_invariant.py

Design constraints (C4):
    - Container name is hardcoded to "notebook".

kubernetes_asyncio 32.x exec API (S9):
    ws_api = WsApiClient(aiohttp_client_session=session)  # wraps core_api.api_client
    ws = await ws_api.connect_get_namespaced_pod_exec(
        name=pod_name, namespace=namespace, container="notebook",
        command=[...], stderr=True, stdin=True, stdout=True, tty=False
    )
    The returned object exposes write_stdin(bytes), read_stdout(), read_stderr(),
    read_channel(n), returncode. Used as async context manager.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_CONTAINER_NAME = "notebook"


async def exec_command_in_pod(
    core_api,
    *,
    namespace: str,
    pod_name: str,
    argv: list[str],
    timeout_seconds: int = 300,
) -> tuple[str, str, int]:
    """Execute a command in the pod and return (stdout, stderr, exit_code).

    The caller is responsible for validating the command.
    """
    import asyncio
    import json as _json

    from kubernetes_asyncio import client
    from kubernetes_asyncio.stream import WsApiClient

    cfg = core_api.api_client.configuration
    async with WsApiClient(configuration=cfg) as ws_client:
        v1 = client.CoreV1Api(api_client=ws_client)
        ws_connect = await v1.connect_get_namespaced_pod_exec(
            name=pod_name,
            namespace=namespace,
            container=_CONTAINER_NAME,
            command=argv,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _preload_content=False,
        )
        stdout_buf = bytearray()
        stderr_buf = bytearray()
        rc = None
        try:
            async with asyncio.timeout(timeout_seconds):
                async with ws_connect as ws:
                    async for msg in ws:
                        data = msg.data
                        if isinstance(data, str):
                            data = data.encode("utf-8")
                        if len(data) < 1:
                            continue
                        channel = data[0]
                        payload = data[1:]
                        if channel == 1:
                            stdout_buf.extend(payload)
                        elif channel == 2:
                            stderr_buf.extend(payload)
                        elif channel == 3:
                            try:
                                status = _json.loads(payload.decode("utf-8"))
                                rc = 0 if status.get("status") == "Success" else int(
                                    status["details"]["causes"][0]["message"]
                                )
                            except Exception:
                                rc = 1
        except TimeoutError:
            logger.warning("exec_command_in_pod timed out after %ds: %s", timeout_seconds, argv)
            return bytes(stdout_buf).decode("utf-8", errors="replace"), "Timed out", -1

    if rc is None:
        rc = 0
    return (
        bytes(stdout_buf).decode("utf-8", errors="replace"),
        bytes(stderr_buf).decode("utf-8", errors="replace"),
        rc,
    )
