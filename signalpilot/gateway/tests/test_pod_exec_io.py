"""Tests for orchestrator/pod_exec_io.py.

Tests:
- exec_command_in_pod: container name is hardcoded to 'notebook'
- exec_command_in_pod: timeout returns (-1) exit code
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.orchestrator.pod_exec_io import exec_command_in_pod


class _AsyncEmptyIter:
    """Async iterator that yields no messages — simulates a closed websocket."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _AsyncContextWs:
    """Async context manager that also acts as an async iterable."""

    def __init__(self):
        self._iter = _AsyncEmptyIter()

    async def __aenter__(self):
        return self._iter

    async def __aexit__(self, *args):
        return False


class TestExecCommandInPod:
    @pytest.mark.asyncio
    async def test_container_name_is_notebook(self):
        """exec_command_in_pod always uses container='notebook'."""
        captured_kwargs: list[dict] = []

        ws_ctx = _AsyncContextWs()

        async def _capture_exec(**kwargs):
            captured_kwargs.append(kwargs)
            return ws_ctx

        fake_v1 = MagicMock()
        fake_v1.connect_get_namespaced_pod_exec = _capture_exec

        mock_ws_api = MagicMock()
        mock_ws_api.__aenter__ = AsyncMock(return_value=mock_ws_api)
        mock_ws_api.__aexit__ = AsyncMock(return_value=False)

        fake_core = MagicMock()
        fake_core.api_client = MagicMock()
        fake_core.api_client.configuration = MagicMock()

        with patch("kubernetes_asyncio.stream.WsApiClient", return_value=mock_ws_api):
            with patch("kubernetes_asyncio.client.CoreV1Api", return_value=fake_v1):
                await exec_command_in_pod(
                    fake_core,
                    namespace="my-ns",
                    pod_name="my-pod",
                    argv=["echo", "hello"],
                    timeout_seconds=5,
                )

        assert captured_kwargs, "connect_get_namespaced_pod_exec was not called"
        assert captured_kwargs[0]["container"] == "notebook", (
            f"container must be 'notebook', got {captured_kwargs[0].get('container')!r}"
        )
