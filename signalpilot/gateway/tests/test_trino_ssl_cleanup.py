"""Tests for Trino SSL temp file tracking and cleanup.

Verifies that:
- _write_ssl_temp_file() tracks files in _temp_files.
- _cleanup_temp_files() removes tracked files from disk and clears the list.
- Calling close() on the TrinoConnector triggers temp file cleanup.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gateway.connectors.base import BaseConnector

# ─── Minimal concrete subclass for testing BaseConnector ─────────────────────


class _ConcreteConnector(BaseConnector):
    """Minimal concrete implementation of BaseConnector for unit testing."""

    async def connect(self, connection_string: str) -> None:
        pass

    async def execute(self, sql: str, params=None, timeout=None):
        return []

    async def get_schema(self):
        return {}


class TestWriteSslTempFile:
    def test_file_is_created_and_tracked(self):
        """_write_ssl_temp_file must create the file and add its path to _temp_files."""
        connector = _ConcreteConnector()
        assert connector._temp_files == []

        path = connector._write_ssl_temp_file("fake-pem-content")

        assert os.path.exists(path), "Temp file must exist after writing"
        assert path in connector._temp_files, "Path must be tracked in _temp_files"

        # Cleanup manually for test hygiene
        os.unlink(path)

    def test_file_content_is_correct(self):
        """_write_ssl_temp_file must write the given PEM content to the file."""
        connector = _ConcreteConnector()
        content = "-----BEGIN CERTIFICATE-----\nABCDEF==\n-----END CERTIFICATE-----\n"

        path = connector._write_ssl_temp_file(content)

        try:
            actual = Path(path).read_bytes().decode()
            assert actual == content
        finally:
            os.unlink(path)

    def test_chmod_is_applied(self):
        """_write_ssl_temp_file must apply the specified chmod mode."""
        connector = _ConcreteConnector()
        path = connector._write_ssl_temp_file("secret-key", chmod=0o600)

        try:
            mode = oct(os.stat(path).st_mode & 0o777)
            assert mode == oct(0o600), f"Expected 0o600, got {mode}"
        finally:
            os.unlink(path)

    def test_multiple_files_all_tracked(self):
        """Multiple calls must track all files."""
        connector = _ConcreteConnector()

        path1 = connector._write_ssl_temp_file("cert-pem", chmod=0o600)
        path2 = connector._write_ssl_temp_file("key-pem", chmod=0o600)

        assert path1 in connector._temp_files
        assert path2 in connector._temp_files
        assert len(connector._temp_files) == 2

        os.unlink(path1)
        os.unlink(path2)


class TestCleanupTempFiles:
    def test_cleanup_removes_tracked_files(self):
        """_cleanup_temp_files must delete all tracked temp files from disk."""
        connector = _ConcreteConnector()

        path1 = connector._write_ssl_temp_file("cert1")
        path2 = connector._write_ssl_temp_file("cert2")
        assert os.path.exists(path1)
        assert os.path.exists(path2)

        connector._cleanup_temp_files()

        assert not os.path.exists(path1), "File should be deleted after cleanup"
        assert not os.path.exists(path2), "File should be deleted after cleanup"

    def test_cleanup_clears_temp_files_list(self):
        """After _cleanup_temp_files, _temp_files must be empty."""
        connector = _ConcreteConnector()

        path = connector._write_ssl_temp_file("data")
        assert len(connector._temp_files) == 1

        connector._cleanup_temp_files()

        assert connector._temp_files == []
        # Ensure file was removed (even though list is clear)
        assert not os.path.exists(path)

    def test_cleanup_is_idempotent(self):
        """Calling _cleanup_temp_files twice must not raise errors."""
        connector = _ConcreteConnector()
        connector._write_ssl_temp_file("data")

        connector._cleanup_temp_files()
        connector._cleanup_temp_files()  # Second call must not raise

        assert connector._temp_files == []

    def test_cleanup_tolerates_missing_file(self):
        """_cleanup_temp_files must not raise if a tracked file has already been removed."""
        connector = _ConcreteConnector()
        path = connector._write_ssl_temp_file("data")
        os.unlink(path)  # Remove manually before cleanup

        # Must not raise OSError
        connector._cleanup_temp_files()
        assert connector._temp_files == []


class TestTrinoConnectorCloseCleanup:
    def test_close_triggers_cleanup(self):
        """TrinoConnector.close() must call _cleanup_temp_files."""
        try:
            from gateway.connectors.trino import TrinoConnector
        except ImportError:
            pytest.skip("trino package not installed")

        connector = TrinoConnector()

        # Write a real temp file to track
        path = connector._write_ssl_temp_file("fake-cert", chmod=0o600)
        assert os.path.exists(path)

        # Mock the trino connection so close() doesn't fail
        mock_conn = MagicMock()
        connector._conn = mock_conn

        asyncio.run(connector.close())

        # Temp file must be removed after close()
        assert not os.path.exists(path), "SSL temp files must be cleaned up on close()"
        assert connector._temp_files == []
        mock_conn.close.assert_called_once()

    def test_close_without_connection_still_cleans_up(self):
        """close() with no active connection must still clean up temp files."""
        try:
            from gateway.connectors.trino import TrinoConnector
        except ImportError:
            pytest.skip("trino package not installed")

        connector = TrinoConnector()
        path = connector._write_ssl_temp_file("fake-cert", chmod=0o600)
        assert os.path.exists(path)

        # No connection open
        assert connector._conn is None

        asyncio.run(connector.close())

        assert not os.path.exists(path), "SSL temp files must be cleaned up even without a connection"
        assert connector._temp_files == []
