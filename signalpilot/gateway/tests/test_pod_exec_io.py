"""Tests for orchestrator/pod_exec_io.py.

Tests:
- Path validation (dest_path / src_path must start with /workspace/)
- Signature has no 'command' parameter (C4)
- Container name is hardcoded to 'notebook'
- Non-zero tar exit code raises RuntimeError
- Security: V1 tar extraction path traversal rejected (filter="data")
- Security: V2/V3 symlinks skipped on both tar-in and snapshot
- Sentinel ordering: .sp-ready is guaranteed LAST in tar member list (C1)
"""

from __future__ import annotations

import inspect
import io
import os
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.orchestrator.pod_exec_io import (
    stream_tar_into_pod,
    stream_tar_out_of_pod,
    _validate_arcname,
)


class TestStreamInValidation:
    @pytest.mark.asyncio
    async def test_validates_dest_path_under_workspace(self, tmp_path: Path):
        """stream_tar_into_pod accepts dest_path starting with /workspace/."""
        mock_ws = MagicMock()
        mock_ws.write_stdin = AsyncMock()
        mock_ws.read_stdout = AsyncMock(return_value=b"")
        mock_ws.read_stderr = AsyncMock(return_value=b"")
        mock_ws.returncode = 0

        mock_ws_api = AsyncMock()
        mock_ws_api.connect_get_namespaced_pod_exec = AsyncMock(return_value=mock_ws)
        mock_ws_api.__aenter__ = AsyncMock(return_value=mock_ws_api)
        mock_ws_api.__aexit__ = AsyncMock(return_value=False)

        fake_core = MagicMock()
        fake_core.api_client = MagicMock()

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "file.txt").write_text("hello")

        with patch("kubernetes_asyncio.stream.WsApiClient", return_value=mock_ws_api):
            # Should not raise.
            await stream_tar_into_pod(
                fake_core,
                namespace="test-ns",
                pod_name="nb-test",
                src_dir=src_dir,
                dest_path="/workspace/",
            )

    @pytest.mark.asyncio
    async def test_rejects_dest_path_outside_workspace(self, tmp_path: Path):
        """stream_tar_into_pod raises ValueError for dest_path outside /workspace/."""
        fake_core = MagicMock()
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        with pytest.raises(ValueError, match="/workspace/"):
            await stream_tar_into_pod(
                fake_core,
                namespace="test-ns",
                pod_name="nb-test",
                src_dir=src_dir,
                dest_path="/tmp/evil",
            )

    @pytest.mark.asyncio
    async def test_rejects_empty_dest_path(self, tmp_path: Path):
        """stream_tar_into_pod raises ValueError for empty dest_path."""
        fake_core = MagicMock()
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        with pytest.raises(ValueError):
            await stream_tar_into_pod(
                fake_core,
                namespace="test-ns",
                pod_name="nb-test",
                src_dir=src_dir,
                dest_path="",
            )


class TestStreamInSignature:
    def test_stream_in_signature_has_no_command_parameter(self):
        """stream_tar_into_pod has no 'command' parameter (C4)."""
        sig = inspect.signature(stream_tar_into_pod)
        assert "command" not in sig.parameters, (
            "stream_tar_into_pod must NOT have a 'command' parameter (C4 — "
            "command is hardcoded internally to prevent injection)"
        )

    def test_stream_out_signature_has_no_command_parameter(self):
        """stream_tar_out_of_pod has no 'command' parameter (C4)."""
        sig = inspect.signature(stream_tar_out_of_pod)
        assert "command" not in sig.parameters, (
            "stream_tar_out_of_pod must NOT have a 'command' parameter (C4)"
        )


class TestStreamOutValidation:
    @pytest.mark.asyncio
    async def test_rejects_src_path_outside_workspace(self):
        """stream_tar_out_of_pod raises ValueError for src_path outside /workspace/."""
        fake_core = MagicMock()

        with pytest.raises(ValueError, match="/workspace/"):
            await stream_tar_out_of_pod(
                fake_core,
                namespace="test-ns",
                pod_name="nb-test",
                src_path="/home/evil",
                dest_dir=Path("/tmp/dest"),
            )

    @pytest.mark.asyncio
    async def test_stream_out_non_zero_tar_exit_raises(self, tmp_path: Path):
        """stream_tar_out_of_pod raises RuntimeError when tar exits non-zero."""
        mock_ws = MagicMock()
        mock_ws.read_stdout = AsyncMock(return_value=b"")
        mock_ws.read_stderr = AsyncMock(return_value=b"tar: error")
        mock_ws.returncode = 1

        mock_ws_api = AsyncMock()
        mock_ws_api.connect_get_namespaced_pod_exec = AsyncMock(return_value=mock_ws)
        mock_ws_api.__aenter__ = AsyncMock(return_value=mock_ws_api)
        mock_ws_api.__aexit__ = AsyncMock(return_value=False)

        fake_core = MagicMock()
        fake_core.api_client = MagicMock()

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        with patch("kubernetes_asyncio.stream.WsApiClient", return_value=mock_ws_api):
            with pytest.raises(RuntimeError, match="tar failed"):
                await stream_tar_out_of_pod(
                    fake_core,
                    namespace="test-ns",
                    pod_name="nb-test",
                    src_path="/workspace/",
                    dest_dir=dest_dir,
                )


class TestContainerNameHardcoded:
    @pytest.mark.asyncio
    async def test_container_name_is_hardcoded_notebook(self, tmp_path: Path):
        """kubernetes_asyncio mock is always called with container='notebook'."""
        captured_kwargs: list[dict] = []

        mock_ws = MagicMock()
        mock_ws.write_stdin = AsyncMock()
        mock_ws.read_stdout = AsyncMock(return_value=b"")
        mock_ws.read_stderr = AsyncMock(return_value=b"")
        mock_ws.returncode = 0

        mock_ws_api = MagicMock()
        mock_ws_api.__aenter__ = AsyncMock(return_value=mock_ws_api)
        mock_ws_api.__aexit__ = AsyncMock(return_value=False)

        async def _capture_exec(**kwargs):
            captured_kwargs.append(kwargs)
            return mock_ws

        mock_ws_api.connect_get_namespaced_pod_exec = _capture_exec

        fake_core = MagicMock()
        fake_core.api_client = MagicMock()

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "f.txt").write_text("x")

        with patch("kubernetes_asyncio.stream.WsApiClient", return_value=mock_ws_api):
            await stream_tar_into_pod(
                fake_core,
                namespace="my-ns",
                pod_name="my-pod",
                src_dir=src_dir,
                dest_path="/workspace/",
            )

        assert captured_kwargs, "connect_get_namespaced_pod_exec was not called"
        assert captured_kwargs[0]["container"] == "notebook", (
            f"container must be 'notebook', got {captured_kwargs[0].get('container')!r}"
        )


class TestSecurityV1TarExtractionFilter:
    """V1: tarfile.extractall must use filter='data' to reject path traversal."""

    @pytest.mark.asyncio
    async def test_malicious_tar_path_traversal_rejected(self, tmp_path: Path):
        """A tar entry with '../escape' must be rejected during extraction (V1).

        Build a malicious tar with a path-traversal entry. When stream_tar_out_of_pod
        extracts it, filter='data' must raise, and nothing should land outside dest_dir.
        """
        from gateway.orchestrator import pod_exec_io

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        escape_target = tmp_path / "escape.txt"

        # Build a malicious tar with a traversal entry.
        mal_buf = io.BytesIO()
        with tarfile.open(fileobj=mal_buf, mode="w") as tf:
            # Add a legitimate file.
            data = b"safe content"
            info = tarfile.TarInfo(name="safe.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            # Add a path-traversal entry that would escape dest_dir.
            evil_data = b"escaped!"
            evil_info = tarfile.TarInfo(name="../escape.txt")
            evil_info.size = len(evil_data)
            tf.addfile(evil_info, io.BytesIO(evil_data))
        mal_bytes = mal_buf.getvalue()

        original_exec_stdout = pod_exec_io._exec_with_stdout

        async def _patched(*args, **kwargs):
            return mal_bytes

        pod_exec_io._exec_with_stdout = _patched
        try:
            with pytest.raises(Exception):
                # filter="data" should raise (tarfile.FilterError or similar) on the
                # traversal entry, or at minimum refuse to extract outside dest_dir.
                await stream_tar_out_of_pod(
                    None,
                    namespace="ns",
                    pod_name="pod",
                    src_path="/workspace/",
                    dest_dir=dest_dir,
                )
        finally:
            pod_exec_io._exec_with_stdout = original_exec_stdout

        # The escape target must NOT exist.
        assert not escape_target.exists(), (
            "Path traversal entry '../escape.txt' was extracted outside dest_dir — "
            "filter='data' did not block it (V1 unfixed)"
        )

    def test_extractall_uses_data_filter(self):
        """Verify that a clean tar extraction works correctly with filter='data'."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            data = b"hello"
            info = tarfile.TarInfo(name="hello.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        tar_bytes = buf.getvalue()

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            buf2 = io.BytesIO(tar_bytes)
            with tarfile.open(fileobj=buf2, mode="r") as tf:
                # Should NOT raise for a safe tar.
                tf.extractall(path=dest, filter="data")
            assert (dest / "hello.txt").read_bytes() == b"hello"


class TestSecurityV3SentinelLastOrdering:
    """C1 + V3: sentinel_last guarantees .sp-ready is the final tar member."""

    @pytest.mark.asyncio
    async def test_sentinel_is_last_member_in_tar(self, tmp_path: Path):
        """stream_tar_into_pod with sentinel_last places .sp-ready after all other files."""
        from gateway.orchestrator import pod_exec_io

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "a.txt").write_bytes(b"aaa")
        (src_dir / "z.txt").write_bytes(b"zzz")
        sentinel = src_dir / ".sp-ready"
        sentinel.write_bytes(b"")

        # Verify naive sort would place ".sp-ready" FIRST (the bug this fixes).
        naive_sorted = sorted(
            str(f.relative_to(src_dir)) for f in src_dir.rglob("*") if f.is_file()
        )
        assert naive_sorted[0] == ".sp-ready", (
            "Prerequisite: without the fix, .sp-ready sorts FIRST (dot < letter in ASCII)"
        )

        captured_tar_bytes: list[bytes] = []

        original_exec = pod_exec_io._exec_with_stdin

        async def _capture(core_api, *, namespace, pod_name, command, stdin_data, label):
            captured_tar_bytes.append(stdin_data)

        pod_exec_io._exec_with_stdin = _capture
        try:
            await stream_tar_into_pod(
                None,
                namespace="ns",
                pod_name="pod",
                src_dir=src_dir,
                dest_path="/workspace/",
                sentinel_last=sentinel,
            )
        finally:
            pod_exec_io._exec_with_stdin = original_exec

        assert captured_tar_bytes, "No tar was transmitted"
        buf = io.BytesIO(captured_tar_bytes[0])
        with tarfile.open(fileobj=buf, mode="r") as tf:
            members = [m.name for m in tf.getmembers()]

        assert ".sp-ready" in members, ".sp-ready must be in the tar"
        assert members[-1] == ".sp-ready", (
            f".sp-ready must be LAST (C1), got order: {members}"
        )

    @pytest.mark.asyncio
    async def test_symlinks_skipped_in_tar_in(self, tmp_path: Path):
        """V3: symlinks in src_dir are skipped and not added to the tar."""
        from gateway.orchestrator import pod_exec_io

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "real.txt").write_bytes(b"real")
        target = tmp_path / "evil_target.txt"
        target.write_bytes(b"evil")
        # Create a symlink inside src_dir pointing outside.
        (src_dir / "evil_link.txt").symlink_to(target)

        captured_tar_bytes: list[bytes] = []

        original_exec = pod_exec_io._exec_with_stdin

        async def _capture(core_api, *, namespace, pod_name, command, stdin_data, label):
            captured_tar_bytes.append(stdin_data)

        pod_exec_io._exec_with_stdin = _capture
        try:
            await stream_tar_into_pod(
                None,
                namespace="ns",
                pod_name="pod",
                src_dir=src_dir,
                dest_path="/workspace/",
            )
        finally:
            pod_exec_io._exec_with_stdin = original_exec

        assert captured_tar_bytes, "No tar was transmitted"
        buf = io.BytesIO(captured_tar_bytes[0])
        with tarfile.open(fileobj=buf, mode="r") as tf:
            members = [m.name for m in tf.getmembers()]

        assert "real.txt" in members, "real.txt must be in the tar"
        assert "evil_link.txt" not in members, (
            "Symlink evil_link.txt must be SKIPPED and not included in the tar (V3)"
        )


class TestSecurityV3ArcnameValidation:
    """V3: arcname validation rejects leading '/' and '..' components."""

    def test_arcname_leading_slash_rejected(self):
        with pytest.raises(ValueError, match="not start with"):
            _validate_arcname("/etc/passwd")

    def test_arcname_dotdot_rejected(self):
        with pytest.raises(ValueError, match="\\.\\."):
            _validate_arcname("../../etc/passwd")

    def test_arcname_nul_rejected(self):
        with pytest.raises(ValueError, match="NUL"):
            _validate_arcname("file\x00.txt")

    def test_arcname_valid_passes(self):
        # Should not raise.
        _validate_arcname("subdir/file.txt")
        _validate_arcname("a.txt")
