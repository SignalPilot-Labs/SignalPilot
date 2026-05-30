"""F-4: Tests for stdin forwarding in exec_command_in_pod.

Covers:
- stdin=True flag is passed when stdin_bytes is provided.
- Payload is written to the websocket (channel 0).
- Payload exceeding 1 MiB raises ValueError.
- EOF is signaled after payload write (catches silent-hang regression).
- 200 KB payload through a tee-style exec stub exits within timeout.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.orchestrator.pod_exec_io import _STDIN_MAX_BYTES, exec_command_in_pod


class _AsyncEmptyIter:
    """Async iterator that yields no messages — simulates a closed websocket."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _CapturingWs:
    """Websocket stub that captures write_stdin calls and records EOF signals."""

    def __init__(self):
        self.written_payloads: list[bytes] = []
        self.eof_signaled: bool = False

    async def write_stdin(self, data: bytes) -> None:
        if data == b"":
            self.eof_signaled = True
        else:
            self.written_payloads.append(data)

    def __aiter__(self):
        return _AsyncEmptyIter()


class _AsyncContextWs:
    """Async context manager wrapping _CapturingWs."""

    def __init__(self, ws: _CapturingWs):
        self._ws = ws

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *args):
        return False


class _SendBytesWs:
    """Websocket stub that uses send_bytes (fallback path) instead of write_stdin."""

    def __init__(self):
        self.sent_frames: list[bytes] = []

    async def send_bytes(self, data: bytes) -> None:
        self.sent_frames.append(data)

    def __aiter__(self):
        return _AsyncEmptyIter()


class _AsyncContextSendBytesWs:
    def __init__(self, ws: _SendBytesWs):
        self._ws = ws

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *args):
        return False


def _make_core_api():
    fake_core = MagicMock()
    fake_core.api_client = MagicMock()
    fake_core.api_client.configuration = MagicMock()
    return fake_core


class TestStdinBytesForwarded:
    """stdin=True flag and bytes are forwarded to the websocket."""

    @pytest.mark.asyncio
    async def test_stdin_bytes_forwarded(self):
        """When stdin_bytes is provided, stdin=True and payload written to ws."""
        captured_exec_kwargs: list[dict] = []
        capturing_ws = _CapturingWs()
        ws_ctx = _AsyncContextWs(capturing_ws)

        async def fake_exec(**kwargs):
            captured_exec_kwargs.append(kwargs)
            return ws_ctx

        fake_v1 = MagicMock()
        fake_v1.connect_get_namespaced_pod_exec = fake_exec

        mock_ws_api = MagicMock()
        mock_ws_api.__aenter__ = AsyncMock(return_value=mock_ws_api)
        mock_ws_api.__aexit__ = AsyncMock(return_value=False)

        with patch("kubernetes_asyncio.stream.WsApiClient", return_value=mock_ws_api), \
             patch("kubernetes_asyncio.client.CoreV1Api", return_value=fake_v1):
            await exec_command_in_pod(
                _make_core_api(),
                namespace="test-ns",
                pod_name="test-pod",
                argv=["tee", "/tmp/out.py"],
                stdin_bytes=b"print('hello')",
                timeout_seconds=5,
            )

        assert captured_exec_kwargs, "connect_get_namespaced_pod_exec was not called"
        assert captured_exec_kwargs[0]["stdin"] is True, (
            "stdin=True must be set when stdin_bytes is provided"
        )
        assert b"print('hello')" in capturing_ws.written_payloads, (
            f"Payload not written; got: {capturing_ws.written_payloads}"
        )

    @pytest.mark.asyncio
    async def test_no_stdin_bytes_uses_stdin_false(self):
        """When stdin_bytes is None, stdin=False is passed (existing behavior)."""
        captured_exec_kwargs: list[dict] = []
        ws_ctx = _AsyncContextWs(_CapturingWs())

        async def fake_exec(**kwargs):
            captured_exec_kwargs.append(kwargs)
            return ws_ctx

        fake_v1 = MagicMock()
        fake_v1.connect_get_namespaced_pod_exec = fake_exec

        mock_ws_api = MagicMock()
        mock_ws_api.__aenter__ = AsyncMock(return_value=mock_ws_api)
        mock_ws_api.__aexit__ = AsyncMock(return_value=False)

        with patch("kubernetes_asyncio.stream.WsApiClient", return_value=mock_ws_api), \
             patch("kubernetes_asyncio.client.CoreV1Api", return_value=fake_v1):
            await exec_command_in_pod(
                _make_core_api(),
                namespace="test-ns",
                pod_name="test-pod",
                argv=["echo", "hello"],
                timeout_seconds=5,
            )

        assert captured_exec_kwargs[0]["stdin"] is False


class TestStdinSizeCap:
    """Payloads exceeding 1 MiB raise ValueError before any connection is made."""

    @pytest.mark.asyncio
    async def test_stdin_size_cap_raises_value_error(self):
        oversized = b"x" * (_STDIN_MAX_BYTES + 1)
        with pytest.raises(ValueError, match="1 MiB"):
            await exec_command_in_pod(
                _make_core_api(),
                namespace="test-ns",
                pod_name="test-pod",
                argv=["tee", "/tmp/out.py"],
                stdin_bytes=oversized,
                timeout_seconds=5,
            )

    @pytest.mark.asyncio
    async def test_stdin_at_cap_is_accepted(self):
        """Exactly 1 MiB is within the limit."""
        at_limit = b"x" * _STDIN_MAX_BYTES
        capturing_ws = _CapturingWs()
        ws_ctx = _AsyncContextWs(capturing_ws)

        fake_v1 = MagicMock()
        fake_v1.connect_get_namespaced_pod_exec = AsyncMock(return_value=ws_ctx)

        mock_ws_api = MagicMock()
        mock_ws_api.__aenter__ = AsyncMock(return_value=mock_ws_api)
        mock_ws_api.__aexit__ = AsyncMock(return_value=False)

        with patch("kubernetes_asyncio.stream.WsApiClient", return_value=mock_ws_api), \
             patch("kubernetes_asyncio.client.CoreV1Api", return_value=fake_v1):
            # Should not raise
            await exec_command_in_pod(
                _make_core_api(),
                namespace="test-ns",
                pod_name="test-pod",
                argv=["tee", "/tmp/out.py"],
                stdin_bytes=at_limit,
                timeout_seconds=5,
            )


class TestStdinEofSignaled:
    """After writing payload, an EOF sentinel must be sent so tee exits."""

    @pytest.mark.asyncio
    async def test_stdin_eof_signaled_via_write_stdin(self):
        """write_stdin path: zero-length write signals EOF."""
        capturing_ws = _CapturingWs()
        ws_ctx = _AsyncContextWs(capturing_ws)

        fake_v1 = MagicMock()
        fake_v1.connect_get_namespaced_pod_exec = AsyncMock(return_value=ws_ctx)

        mock_ws_api = MagicMock()
        mock_ws_api.__aenter__ = AsyncMock(return_value=mock_ws_api)
        mock_ws_api.__aexit__ = AsyncMock(return_value=False)

        with patch("kubernetes_asyncio.stream.WsApiClient", return_value=mock_ws_api), \
             patch("kubernetes_asyncio.client.CoreV1Api", return_value=fake_v1):
            await exec_command_in_pod(
                _make_core_api(),
                namespace="test-ns",
                pod_name="test-pod",
                argv=["tee", "/tmp/out.py"],
                stdin_bytes=b"some payload",
                timeout_seconds=5,
            )

        assert capturing_ws.eof_signaled, (
            "EOF must be signaled after writing stdin so tee exits. "
            "A missing EOF causes tee to hang waiting for more input."
        )
        assert capturing_ws.written_payloads == [b"some payload"]

    @pytest.mark.asyncio
    async def test_stdin_eof_signaled_via_send_bytes(self):
        """send_bytes fallback path: zero-length channel-0 frame signals EOF."""
        send_ws = _SendBytesWs()
        ws_ctx = _AsyncContextSendBytesWs(send_ws)

        fake_v1 = MagicMock()
        fake_v1.connect_get_namespaced_pod_exec = AsyncMock(return_value=ws_ctx)

        mock_ws_api = MagicMock()
        mock_ws_api.__aenter__ = AsyncMock(return_value=mock_ws_api)
        mock_ws_api.__aexit__ = AsyncMock(return_value=False)

        with patch("kubernetes_asyncio.stream.WsApiClient", return_value=mock_ws_api), \
             patch("kubernetes_asyncio.client.CoreV1Api", return_value=fake_v1):
            await exec_command_in_pod(
                _make_core_api(),
                namespace="test-ns",
                pod_name="test-pod",
                argv=["tee", "/tmp/out.py"],
                stdin_bytes=b"fallback payload",
                timeout_seconds=5,
            )

        assert len(send_ws.sent_frames) >= 2, (
            "send_bytes path must send at least 2 frames: payload + EOF sentinel"
        )
        # First frame: channel-0 + payload
        assert send_ws.sent_frames[0] == bytes([0]) + b"fallback payload"
        # Last frame: zero-length channel-0 frame (EOF)
        assert send_ws.sent_frames[-1] == bytes([0]), (
            "EOF sentinel must be a zero-length channel-0 frame (bytes([0]))"
        )


class TestLargeBlobThroughTeeExits:
    """A 200 KB payload written via write_stdin completes without hanging."""

    @pytest.mark.asyncio
    async def test_large_blob_through_tee_exits(self):
        """200 KB payload forwarded; EOF is signaled and function completes within timeout."""
        large_payload = b"A" * (200 * 1024)  # 200 KB
        capturing_ws = _CapturingWs()
        ws_ctx = _AsyncContextWs(capturing_ws)

        fake_v1 = MagicMock()
        fake_v1.connect_get_namespaced_pod_exec = AsyncMock(return_value=ws_ctx)

        mock_ws_api = MagicMock()
        mock_ws_api.__aenter__ = AsyncMock(return_value=mock_ws_api)
        mock_ws_api.__aexit__ = AsyncMock(return_value=False)

        with patch("kubernetes_asyncio.stream.WsApiClient", return_value=mock_ws_api), \
             patch("kubernetes_asyncio.client.CoreV1Api", return_value=fake_v1):
            stdout, stderr, rc = await asyncio.wait_for(
                exec_command_in_pod(
                    _make_core_api(),
                    namespace="test-ns",
                    pod_name="test-pod",
                    argv=["tee", "/tmp/large.py"],
                    stdin_bytes=large_payload,
                    timeout_seconds=10,
                ),
                timeout=5.0,
            )

        assert capturing_ws.eof_signaled, "EOF must be signaled for large payloads too"
        assert capturing_ws.written_payloads == [large_payload]
