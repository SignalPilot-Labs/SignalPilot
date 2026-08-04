"""Tests for /api/files/browse root confinement.

The sandbox manager has host filesystem access, so the endpoint must never
forward a caller-supplied path that escapes the configured browse root.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from gateway.api import files


@pytest.fixture(autouse=True)
def _root(monkeypatch):
    monkeypatch.setenv("SP_FILE_BROWSE_ROOT", "/data/warehouses")
    yield


class TestConfinedPath:
    def test_no_path_is_left_to_the_sandbox_default(self):
        assert files._confined_path(None) is None
        assert files._confined_path("   ") is None

    def test_root_escape_via_absolute_path_rejected(self):
        for bad in ["/", "/etc", "/etc/passwd", "/data", "/data/warehouses-other", "//"]:
            with pytest.raises(HTTPException) as exc:
                files._confined_path(bad)
            assert exc.value.status_code == 400, bad

    def test_traversal_rejected(self):
        for bad in [
            "..",
            "../..",
            "sub/../../../etc",
            "/data/warehouses/../../etc",
            "..\\..\\windows",
        ]:
            with pytest.raises(HTTPException) as exc:
                files._confined_path(bad)
            assert exc.value.status_code == 400, bad

    def test_nul_byte_rejected(self):
        with pytest.raises(HTTPException):
            files._confined_path("sub\x00/etc")

    def test_legitimate_relative_path_allowed(self):
        assert files._confined_path("prod") == "/data/warehouses/prod"
        assert files._confined_path("prod/2026") == "/data/warehouses/prod/2026"

    def test_legitimate_absolute_in_root_path_allowed(self):
        assert files._confined_path("/data/warehouses/prod") == "/data/warehouses/prod"
        assert files._confined_path("/data/warehouses") == "/data/warehouses"

    def test_root_falls_back_to_data_dir(self, monkeypatch):
        monkeypatch.delenv("SP_FILE_BROWSE_ROOT", raising=False)
        monkeypatch.setenv("SP_DATA_DIR", "/srv/sp-data")
        assert files._confined_path("db") == "/srv/sp-data/db"
        with pytest.raises(HTTPException):
            files._confined_path("/etc")

    def test_default_root_matches_the_sandbox_host_mount(self, monkeypatch):
        monkeypatch.delenv("SP_FILE_BROWSE_ROOT", raising=False)
        monkeypatch.delenv("SP_DATA_DIR", raising=False)
        assert files._confined_path("db") == "/host-data/db"


class TestSafePattern:
    def test_pattern_cannot_traverse(self):
        for bad in ["../*", "sub/*.duckdb", "..", "*\x00"]:
            with pytest.raises(HTTPException) as exc:
                files._safe_pattern(bad)
            assert exc.value.status_code == 400, bad

    def test_normal_pattern_allowed(self):
        assert files._safe_pattern("*.duckdb") == "*.duckdb"


class TestEndpointBehaviour:
    @pytest.mark.asyncio
    async def test_endpoint_forwards_only_confined_path(self, monkeypatch):
        forwarded: dict = {}

        class _Client:
            async def browse_files(self, path=None, pattern="*.duckdb"):
                forwarded["path"] = path
                forwarded["pattern"] = pattern
                return {"files": [], "directories": []}

        async def _get_client(store):
            return _Client()

        monkeypatch.setattr(files, "get_sandbox_client_with_store", _get_client)

        await files.browse_files(store=object(), path="prod", pattern="*.duckdb")
        assert forwarded == {"path": "/data/warehouses/prod", "pattern": "*.duckdb"}

        with pytest.raises(HTTPException):
            await files.browse_files(store=object(), path="/", pattern="*")

    def test_endpoint_requires_more_than_read_scope(self):
        """A read-only key must not be enough to enumerate host paths."""
        import inspect

        decorated = inspect.getsource(files.browse_files)
        assert 'RequireScope("read")' not in decorated
        assert 'RequireScope("write")' in decorated
