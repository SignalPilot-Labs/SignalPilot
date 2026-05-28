"""Fixtures for storage tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from gateway.storage.workspace_store import WorkspaceKey


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    """A temporary directory for workspace store roots."""
    return tmp_path / "tmp_root"


@pytest.fixture
def local_workspace_root(tmp_path: Path) -> Path:
    """Root directory for LocalWorkspaceStore tests."""
    root = tmp_path / "workspace_root"
    root.mkdir()
    return root


@pytest.fixture
def make_workspace_key():
    """Factory for valid WorkspaceKey instances."""

    def _make(
        org_id: str = "org1",
        user_id: str = "user1",
        notebook_id: str = "abc123def456abc123def456abc12345",
    ) -> WorkspaceKey:
        return WorkspaceKey(org_id=org_id, user_id=user_id, notebook_id=notebook_id)

    return _make


@pytest.fixture
def disabled_store():
    """A DisabledWorkspaceStore instance."""
    from gateway.storage.disabled_store import DisabledWorkspaceStore

    return DisabledWorkspaceStore()


@pytest.fixture
def moto_s3(monkeypatch):
    """Moto-mocked S3 environment. Yields (bucket_name, s3_client)."""
    try:
        import boto3
        from moto import mock_aws
    except ImportError:
        pytest.skip("moto or boto3 not installed")

    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        bucket = "test-workspace-bucket"
        client.create_bucket(Bucket=bucket)
        yield bucket, client
