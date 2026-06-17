"""Unit tests for sp-sandbox/executor.py — gVisor executor logic."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add sp-sandbox to path so we can import directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sp-sandbox"))

from executor import GVisorExecutor, _strip_gvisor_warnings


class TestStripGvisorWarnings:
    """Tests for gVisor warning line removal."""

    def test_strips_warning_line(self):
        text = "*** Warning: sandbox network isn't supported\nhello"
        assert _strip_gvisor_warnings(text) == "hello"

    def test_strips_multiple_warnings(self):
        text = "*** Warning: foo\n*** Warning: bar\noutput"
        assert _strip_gvisor_warnings(text) == "output"

    def test_preserves_normal_output(self):
        text = "line 1\nline 2\nline 3"
        assert _strip_gvisor_warnings(text) == text

    def test_empty_string(self):
        assert _strip_gvisor_warnings("") == ""

    def test_only_warnings_returns_empty(self):
        text = "*** Warning: only warning"
        assert _strip_gvisor_warnings(text) == ""


class TestGVisorExecutorExecute:
    """Tests for GVisorExecutor.execute with mocked subprocess."""

    @pytest.fixture
    def executor(self):
        return GVisorExecutor()

    @pytest.mark.asyncio
    async def test_successful_execution(self, executor):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"hello world\n", b"")
        mock_proc.returncode = 0
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("executor.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await executor.execute("print('hello world')", "test-vm-1", 10)

        assert result.success is True
        assert "hello world" in result.output
        assert result.error is None
        assert result.vm_id == "test-vm-1"
        assert result.execution_ms > 0

    @pytest.mark.asyncio
    async def test_runtime_error(self, executor):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"ZeroDivisionError: division by zero\n")
        mock_proc.returncode = 1
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("executor.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await executor.execute("1/0", "test-vm-2", 10)

        assert result.success is False
        assert "ZeroDivisionError" in result.error
        assert result.vm_id == "test-vm-2"

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self, executor):
        mock_proc = AsyncMock()
        mock_proc.communicate.side_effect = asyncio.TimeoutError()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("executor.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await executor.execute("import time; time.sleep(999)", "test-vm-3", 2)

        assert result.success is False
        assert "timed out after 2s" in result.error
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_runsc_not_found(self, executor):
        with patch("executor.asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
            result = await executor.execute("print(1)", "test-vm-4", 10)

        assert result.success is False
        assert "runsc not found" in result.error

    @pytest.mark.asyncio
    async def test_strips_gvisor_warnings_from_output(self, executor):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"*** Warning: sandbox network isn't supported\nactual output\n",
            b"",
        )
        mock_proc.returncode = 0
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("executor.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await executor.execute("print('actual output')", "test-vm-5", 10)

        assert result.success is True
        assert "Warning" not in result.output
        assert "actual output" in result.output

    @pytest.mark.asyncio
    async def test_cleans_up_workdir(self, executor):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok\n", b"")
        mock_proc.returncode = 0
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("executor.asyncio.create_subprocess_exec", return_value=mock_proc):
            await executor.execute("print('ok')", "test-vm-6", 10)

        assert "test-vm-6" not in executor._workdirs


class TestGVisorExecutorKill:
    """Tests for GVisorExecutor.kill."""

    @pytest.fixture
    def executor(self):
        return GVisorExecutor()

    @pytest.mark.asyncio
    async def test_kill_unknown_vm_returns_false(self, executor):
        result = await executor.kill("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_kill_active_vm_returns_true(self, executor):
        mock_proc = AsyncMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()
        executor._active["vm-to-kill"] = mock_proc

        result = await executor.kill("vm-to-kill")
        assert result is True
        mock_proc.kill.assert_called_once()
        assert "vm-to-kill" not in executor._active


class TestGVisorExecutorCleanup:
    """Tests for GVisorExecutor.cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_clears_all_state(self):
        executor = GVisorExecutor()
        mock_proc = AsyncMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()
        executor._active["a"] = mock_proc
        executor._active["b"] = mock_proc

        await executor.cleanup()

        assert len(executor._active) == 0
        assert len(executor._workdirs) == 0
