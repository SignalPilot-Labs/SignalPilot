"""Tests for WorkspaceStorageSettings validation."""

from __future__ import annotations

import pytest


def _clear_cache():
    """Clear the workspace storage settings lru_cache between tests."""
    from gateway.config.workspace_storage import get_workspace_storage_settings

    get_workspace_storage_settings.cache_clear()


class TestS3BackendValidation:
    def test_s3_backend_without_bucket_raises(self, monkeypatch):
        """s3 backend without bucket → ValueError."""
        _clear_cache()
        monkeypatch.setenv("SP_WORKSPACE_BACKEND", "s3")
        monkeypatch.delenv("SP_WORKSPACE_S3_BUCKET", raising=False)
        monkeypatch.setenv("SP_WORKSPACE_S3_REGION", "us-east-1")

        from gateway.config.workspace_storage import WorkspaceStorageSettings

        with pytest.raises(ValueError, match="S3_BUCKET"):
            WorkspaceStorageSettings()

    def test_s3_backend_without_region_raises(self, monkeypatch):
        """s3 backend without region → ValueError."""
        _clear_cache()
        monkeypatch.setenv("SP_WORKSPACE_BACKEND", "s3")
        monkeypatch.setenv("SP_WORKSPACE_S3_BUCKET", "my-bucket")
        monkeypatch.delenv("SP_WORKSPACE_S3_REGION", raising=False)

        from gateway.config.workspace_storage import WorkspaceStorageSettings

        with pytest.raises(ValueError, match="S3_REGION"):
            WorkspaceStorageSettings()

    def test_s3_backend_with_bucket_and_region_ok(self, monkeypatch):
        """s3 backend with bucket + region → no error."""
        _clear_cache()
        monkeypatch.setenv("SP_WORKSPACE_BACKEND", "s3")
        monkeypatch.setenv("SP_WORKSPACE_S3_BUCKET", "my-bucket")
        monkeypatch.setenv("SP_WORKSPACE_S3_REGION", "us-east-1")

        from gateway.config.workspace_storage import WorkspaceStorageSettings

        settings = WorkspaceStorageSettings()
        assert settings.sp_workspace_backend == "s3"
        assert settings.sp_workspace_s3_bucket == "my-bucket"


class TestLocalBackendValidation:
    def test_local_backend_without_root_raises(self, monkeypatch):
        """local backend without local_root → ValueError."""
        _clear_cache()
        monkeypatch.setenv("SP_WORKSPACE_BACKEND", "local")
        monkeypatch.delenv("SP_WORKSPACE_LOCAL_ROOT", raising=False)

        from gateway.config.workspace_storage import WorkspaceStorageSettings

        with pytest.raises(ValueError, match="LOCAL_ROOT"):
            WorkspaceStorageSettings()

    def test_local_backend_with_root_ok(self, monkeypatch, tmp_path):
        """local backend with local_root → no error."""
        _clear_cache()
        monkeypatch.setenv("SP_WORKSPACE_BACKEND", "local")
        monkeypatch.setenv("SP_WORKSPACE_LOCAL_ROOT", str(tmp_path))

        from gateway.config.workspace_storage import WorkspaceStorageSettings

        settings = WorkspaceStorageSettings()
        assert settings.sp_workspace_backend == "local"


class TestDisabledBackendValidation:
    def test_disabled_plus_cloud_mode_raises(self, monkeypatch):
        """disabled backend + SP_DEPLOYMENT_MODE=cloud → ValueError (S11)."""
        _clear_cache()
        monkeypatch.setenv("SP_WORKSPACE_BACKEND", "disabled")
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        # cloud mode also requires SP_PUBLIC_GATEWAY_URL — set it
        monkeypatch.setenv("SP_PUBLIC_GATEWAY_URL", "https://gateway.example.com")

        from gateway.config.workspace_storage import WorkspaceStorageSettings

        with pytest.raises(ValueError, match="disabled backend forbidden in cloud mode"):
            WorkspaceStorageSettings()

    def test_disabled_plus_local_mode_ok(self, monkeypatch):
        """disabled backend + local mode → no error."""
        _clear_cache()
        monkeypatch.setenv("SP_WORKSPACE_BACKEND", "disabled")
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")

        from gateway.config.workspace_storage import WorkspaceStorageSettings

        settings = WorkspaceStorageSettings()
        assert settings.sp_workspace_backend == "disabled"

    def test_disabled_default_is_not_cloud_forbidden(self, monkeypatch):
        """Default backend (disabled) is fine in non-cloud mode."""
        _clear_cache()
        monkeypatch.delenv("SP_WORKSPACE_BACKEND", raising=False)
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")

        from gateway.config.workspace_storage import WorkspaceStorageSettings

        settings = WorkspaceStorageSettings()
        assert settings.sp_workspace_backend == "disabled"


class TestSnapshotIntervalValidation:
    def test_interval_below_minimum_raises(self, monkeypatch):
        """interval < 30 → ValueError."""
        _clear_cache()
        monkeypatch.setenv("SP_WORKSPACE_BACKEND", "disabled")
        monkeypatch.setenv("SP_WORKSPACE_SNAPSHOT_INTERVAL_SECONDS", "10")

        from gateway.config.workspace_storage import WorkspaceStorageSettings

        with pytest.raises(ValueError):
            WorkspaceStorageSettings()

    def test_interval_above_maximum_raises(self, monkeypatch):
        """interval > 3600 → ValueError."""
        _clear_cache()
        monkeypatch.setenv("SP_WORKSPACE_BACKEND", "disabled")
        monkeypatch.setenv("SP_WORKSPACE_SNAPSHOT_INTERVAL_SECONDS", "9999")

        from gateway.config.workspace_storage import WorkspaceStorageSettings

        with pytest.raises(ValueError):
            WorkspaceStorageSettings()

    def test_default_interval_is_60(self, monkeypatch):
        """Default interval is 60 seconds (S6)."""
        _clear_cache()
        monkeypatch.setenv("SP_WORKSPACE_BACKEND", "disabled")
        monkeypatch.delenv("SP_WORKSPACE_SNAPSHOT_INTERVAL_SECONDS", raising=False)

        from gateway.config.workspace_storage import WorkspaceStorageSettings

        settings = WorkspaceStorageSettings()
        assert settings.sp_workspace_snapshot_interval_seconds == 60
