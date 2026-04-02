"""Tests for connection export/import endpoints."""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))


@pytest.fixture
def client():
    from gateway.main import app
    return TestClient(app)


@pytest.fixture
def mock_connections():
    """Create mock connections for testing."""
    return [
        {
            "name": "test-pg",
            "db_type": "postgres",
            "host": "localhost",
            "port": 5432,
            "database": "testdb",
            "username": "admin",
            "description": "Test postgres",
            "tags": ["prod"],
            "schema_filter_include": [],
            "schema_filter_exclude": [],
        }
    ]


class TestExportConnections:
    def test_export_without_credentials(self, client, mock_connections):
        with patch("gateway.main.list_connections", return_value=mock_connections):
            resp = client.get("/api/connections/export")
            assert resp.status_code == 200
            data = resp.json()
            assert data["version"] == "1.0"
            assert data["connection_count"] == 1
            assert data["includes_credentials"] is False
            assert len(data["connections"]) == 1
            conn = data["connections"][0]
            assert conn["name"] == "test-pg"
            assert "connection_string" not in conn  # No credentials

    def test_export_with_credentials(self, client, mock_connections):
        with patch("gateway.main.list_connections", return_value=mock_connections), \
             patch("gateway.main.get_connection_string", return_value="postgresql://admin:secret@localhost:5432/testdb"):
            resp = client.get("/api/connections/export?include_credentials=true")
            assert resp.status_code == 200
            data = resp.json()
            assert data["includes_credentials"] is True
            conn = data["connections"][0]
            assert "connection_string" in conn


class TestImportConnections:
    def test_import_new_connections(self, client):
        manifest = {
            "version": "1.0",
            "connections": [
                {"name": "import-pg", "db_type": "postgres", "host": "localhost", "port": 5432, "database": "test"},
            ],
        }
        with patch("gateway.main.get_connection", return_value=None), \
             patch("gateway.main.create_connection") as mock_create:
            mock_create.return_value = MagicMock()
            resp = client.post("/api/connections/import", json=manifest)
            assert resp.status_code == 200
            data = resp.json()
            assert data["imported"] == 1
            assert len(data["skipped"]) == 0

    def test_import_skips_existing(self, client):
        manifest = {
            "version": "1.0",
            "connections": [
                {"name": "existing-pg", "db_type": "postgres", "host": "localhost"},
            ],
        }
        with patch("gateway.main.get_connection", return_value=MagicMock()):
            resp = client.post("/api/connections/import", json=manifest)
            assert resp.status_code == 200
            data = resp.json()
            assert data["imported"] == 0
            assert "existing-pg" in data["skipped"]

    def test_import_empty_name_error(self, client):
        manifest = {
            "version": "1.0",
            "connections": [
                {"name": "", "db_type": "postgres"},
            ],
        }
        resp = client.post("/api/connections/import", json=manifest)
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 0
        assert len(data["errors"]) == 1
