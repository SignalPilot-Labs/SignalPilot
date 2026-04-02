"""Tests for Redshift connector SSL temp file cleanup on connection failure."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))


class TestRedshiftSSLCleanup:
    def test_cleanup_temp_files_removes_files(self):
        """_cleanup_temp_files should remove all tracked temp files."""
        import tempfile
        from gateway.connectors.redshift import RedshiftConnector
        connector = RedshiftConnector()

        # Create actual temp files
        files = []
        for _ in range(3):
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
            f.write(b"test")
            f.close()
            files.append(f.name)
            connector._temp_files.append(f.name)

        # All files exist
        for f in files:
            assert os.path.exists(f)

        connector._cleanup_temp_files()

        # All files removed
        for f in files:
            assert not os.path.exists(f)
        assert len(connector._temp_files) == 0

    def test_cleanup_handles_missing_files(self):
        """_cleanup_temp_files should handle already-deleted files gracefully."""
        from gateway.connectors.redshift import RedshiftConnector
        connector = RedshiftConnector()
        connector._temp_files = ["/tmp/nonexistent_file_xyz.pem"]
        # Should not raise
        connector._cleanup_temp_files()
        assert len(connector._temp_files) == 0

    def test_build_ssl_kwargs_creates_temp_files(self):
        """_build_ssl_kwargs should create temp files and track them."""
        from gateway.connectors.redshift import RedshiftConnector
        connector = RedshiftConnector()
        connector._ssl_config = {
            "mode": "verify-ca",
            "ca_cert": "-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----",
        }
        kwargs = connector._build_ssl_kwargs()
        assert kwargs["sslmode"] == "verify-ca"
        assert "sslrootcert" in kwargs
        assert len(connector._temp_files) == 1
        assert os.path.exists(connector._temp_files[0])

        # Cleanup
        connector._cleanup_temp_files()

    def test_default_timeouts(self):
        """Default timeout values should be sensible."""
        from gateway.connectors.redshift import RedshiftConnector
        connector = RedshiftConnector()
        assert connector._connect_timeout == 15
        assert connector._query_timeout == 30

    def test_credential_extras_sets_timeouts(self):
        """set_credential_extras should update timeout settings."""
        from gateway.connectors.redshift import RedshiftConnector
        connector = RedshiftConnector()
        connector.set_credential_extras({
            "connection_timeout": 30,
            "query_timeout": 120,
        })
        assert connector._connect_timeout == 30
        assert connector._query_timeout == 120
