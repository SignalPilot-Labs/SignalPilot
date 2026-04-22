"""Unit and integration tests for the dbt project system."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Point store at a temp directory so tests don't touch real ~/.signalpilot
_test_dir = tempfile.mkdtemp(prefix="sp-test-projects-")
os.environ["SP_DATA_DIR"] = _test_dir

from signalpilot.gateway.gateway.models import (
    ConnectionInfo,
    DBType,
    ProjectCreate,
    ProjectInfo,
    ProjectSource,
    ProjectStatus,
    ProjectStorage,
    ProjectUpdate,
)
from signalpilot.gateway.gateway.store import (
    PROJECTS_FILE,
    _generate_dbt_project_yml,
    _generate_profiles_yml,
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_connection(name: str, db_type: str) -> ConnectionInfo:
    """Create a minimal ConnectionInfo for testing."""
    return ConnectionInfo(
        id="test-conn-id",
        name=name,
        db_type=DBType(db_type),
        host="localhost",
        port=5432,
        database="testdb",
        username="testuser",
        status="healthy",
    )


@pytest.fixture(autouse=True)
def _clean_projects():
    """Wipe projects.json before each test."""
    if PROJECTS_FILE.exists():
        PROJECTS_FILE.unlink()
    projects_dir = Path(_test_dir) / "projects"
    if projects_dir.exists():
        shutil.rmtree(projects_dir)
    yield
    if PROJECTS_FILE.exists():
        PROJECTS_FILE.unlink()
    if projects_dir.exists():
        shutil.rmtree(projects_dir)


# ─── Scaffold helpers ────────────────────────────────────────────────────────

class TestGenerateDbtProjectYml:
    """Tests for dbt_project.yml generation."""

    def test_contains_project_name(self):
        yml = _generate_dbt_project_yml("my-analytics")
        assert "my-analytics" in yml

    def test_contains_required_keys(self):
        yml = _generate_dbt_project_yml("test-proj")
        assert "model-paths" in yml
        assert "config-version" in yml
        assert "profile:" in yml


class TestGenerateProfilesYml:
    """Tests for profiles.yml generation per db_type."""

    def test_duckdb_profile(self):
        conn = _make_connection("duck", "duckdb")
        yml = _generate_profiles_yml("proj", conn)
        assert "type: duckdb" in yml
        assert "proj:" in yml

    def test_postgres_profile(self):
        conn = _make_connection("pg", "postgres")
        yml = _generate_profiles_yml("proj", conn)
        assert "type: postgres" in yml
        assert "localhost" in yml

    def test_snowflake_profile(self):
        conn = _make_connection("sf", "snowflake")
        conn.account = "xy12345"
        yml = _generate_profiles_yml("proj", conn)
        assert "type: snowflake" in yml
        assert "xy12345" in yml

    def test_bigquery_profile(self):
        conn = _make_connection("bq", "bigquery")
        conn.project = "my-gcp-project"
        conn.dataset = "analytics"
        yml = _generate_profiles_yml("proj", conn)
        assert "type: bigquery" in yml
        assert "my-gcp-project" in yml

    def test_unsupported_db_gets_placeholder(self):
        conn = _make_connection("ms", "mssql")
        yml = _generate_profiles_yml("proj", conn)
        assert "TODO" in yml
        assert "mssql" in yml


# ─── Store CRUD ──────────────────────────────────────────────────────────────

class TestCreateProject:
    """Tests for create_project store function."""

    def test_create_new_project(self):
        conn = _make_connection("prod-pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            proj = create_project(ProjectCreate(
                name="my-proj",
                connection_name="prod-pg",
                source=ProjectSource.new,
            ))
        assert proj.name == "my-proj"
        assert proj.storage == ProjectStorage.managed
        assert proj.source == ProjectSource.new
        assert proj.db_type == "postgres"
        assert proj.status == ProjectStatus.active

    def test_scaffolds_directory_structure(self):
        conn = _make_connection("prod-pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            proj = create_project(ProjectCreate(
                name="scaffold-test",
                connection_name="prod-pg",
                source=ProjectSource.new,
            ))
        project_dir = Path(proj.project_dir)
        assert (project_dir / "dbt_project.yml").exists()
        assert (project_dir / "profiles.yml").exists()
        assert (project_dir / "packages.yml").exists()
        assert (project_dir / "models" / "staging").is_dir()
        assert (project_dir / "models" / "marts").is_dir()

    def test_duplicate_name_raises(self):
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            create_project(ProjectCreate(name="dup", connection_name="pg"))
            with pytest.raises(ValueError, match="already exists"):
                create_project(ProjectCreate(name="dup", connection_name="pg"))

    def test_missing_connection_raises(self):
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=None):
            with pytest.raises(ValueError, match="not found"):
                create_project(ProjectCreate(name="bad", connection_name="nope"))

    def test_create_local_linked(self):
        local_dir = Path(tempfile.mkdtemp())
        (local_dir / "dbt_project.yml").write_text("name: test")
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            proj = create_project(ProjectCreate(
                name="linked-proj",
                connection_name="pg",
                source=ProjectSource.local,
                local_path=str(local_dir),
                link_mode="link",
            ))
        assert proj.storage == ProjectStorage.linked
        assert proj.project_dir == str(local_dir)
        shutil.rmtree(local_dir)

    def test_create_local_copy(self):
        local_dir = Path(tempfile.mkdtemp())
        (local_dir / "dbt_project.yml").write_text("name: test")
        (local_dir / "models").mkdir()
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            proj = create_project(ProjectCreate(
                name="copied-proj",
                connection_name="pg",
                source=ProjectSource.local,
                local_path=str(local_dir),
                link_mode="copy",
            ))
        assert proj.storage == ProjectStorage.managed
        assert proj.project_dir != str(local_dir)
        assert Path(proj.project_dir).exists()
        shutil.rmtree(local_dir)

    def test_create_github_project(self):
        conn = _make_connection("pg", "postgres")
        mock_run = MagicMock(returncode=0, stderr="", stdout="")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn), \
             patch("subprocess.run", return_value=mock_run) as mock_sub:
            # Pre-create the dir with dbt_project.yml to simulate clone
            project_dir = Path(_test_dir) / "projects" / "gh-proj"
            project_dir.mkdir(parents=True, exist_ok=True)
            (project_dir / "dbt_project.yml").write_text("name: test")
            proj = create_project(ProjectCreate(
                name="gh-proj",
                connection_name="pg",
                source=ProjectSource.github,
                git_url="https://github.com/org/repo.git",
                git_branch="develop",
            ))
        assert proj.storage == ProjectStorage.managed
        assert proj.source == ProjectSource.github
        assert proj.git_remote == "https://github.com/org/repo.git"
        assert proj.git_branch == "develop"
        mock_sub.assert_called_once()
        assert "--branch" in mock_sub.call_args[0][0]

    def test_create_github_missing_url_raises(self):
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            with pytest.raises(ValueError, match="git_url is required"):
                create_project(ProjectCreate(
                    name="no-url",
                    connection_name="pg",
                    source=ProjectSource.github,
                ))

    def test_create_github_clone_failure_raises(self):
        conn = _make_connection("pg", "postgres")
        mock_run = MagicMock(returncode=128, stderr="fatal: repo not found", stdout="")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn), \
             patch("subprocess.run", return_value=mock_run):
            with pytest.raises(ValueError, match="git clone failed"):
                create_project(ProjectCreate(
                    name="bad-clone",
                    connection_name="pg",
                    source=ProjectSource.github,
                    git_url="https://github.com/org/nope.git",
                ))

    def test_create_local_missing_path_raises(self):
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            with pytest.raises(ValueError, match="does not exist"):
                create_project(ProjectCreate(
                    name="bad-local",
                    connection_name="pg",
                    source=ProjectSource.local,
                    local_path="/nonexistent/path",
                ))


class TestListProjects:
    """Tests for list_projects store function."""

    def test_empty_list(self):
        assert list_projects() == []

    def test_returns_created_projects(self):
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            create_project(ProjectCreate(name="a", connection_name="pg"))
            create_project(ProjectCreate(name="b", connection_name="pg"))
        projects = list_projects()
        assert len(projects) == 2
        names = {p.name for p in projects}
        assert names == {"a", "b"}


class TestGetProject:
    """Tests for get_project store function."""

    def test_get_existing(self):
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            create_project(ProjectCreate(name="exists", connection_name="pg"))
        proj = get_project("exists")
        assert proj is not None
        assert proj.name == "exists"

    def test_get_missing_returns_none(self):
        assert get_project("nope") is None


class TestUpdateProject:
    """Tests for update_project store function."""

    def test_update_description(self):
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            create_project(ProjectCreate(name="upd", connection_name="pg"))
        result = update_project("upd", ProjectUpdate(description="new desc"))
        assert result is not None
        assert result.description == "new desc"

    def test_update_tags(self):
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            create_project(ProjectCreate(name="tagged", connection_name="pg"))
        result = update_project("tagged", ProjectUpdate(tags=["prod", "analytics"]))
        assert result.tags == ["prod", "analytics"]

    def test_update_missing_returns_none(self):
        assert update_project("ghost", ProjectUpdate(description="x")) is None

    def test_update_preserves_other_fields(self):
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            create_project(ProjectCreate(
                name="preserve",
                connection_name="pg",
                description="original",
                tags=["keep"],
            ))
        result = update_project("preserve", ProjectUpdate(description="changed"))
        assert result.description == "changed"
        assert result.tags == ["keep"]


class TestDeleteProject:
    """Tests for delete_project store function."""

    def test_delete_managed_removes_directory(self):
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            proj = create_project(ProjectCreate(name="to-delete", connection_name="pg"))
        project_dir = Path(proj.project_dir)
        assert project_dir.exists()
        assert delete_project("to-delete") is True
        assert not project_dir.exists()
        assert get_project("to-delete") is None

    def test_delete_linked_keeps_directory(self):
        local_dir = Path(tempfile.mkdtemp())
        (local_dir / "dbt_project.yml").write_text("name: test")
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            create_project(ProjectCreate(
                name="linked-del",
                connection_name="pg",
                source=ProjectSource.local,
                local_path=str(local_dir),
                link_mode="link",
            ))
        assert delete_project("linked-del") is True
        assert local_dir.exists()
        assert (local_dir / "dbt_project.yml").exists()
        shutil.rmtree(local_dir)

    def test_delete_missing_returns_false(self):
        assert delete_project("nope") is False


# ─── API Router ──────────────────────────────────────────────────────────────

class TestProjectsAPI:
    """Integration tests for the projects REST API."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from signalpilot.gateway.gateway.api.projects import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_list_empty(self, client):
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_and_get(self, client):
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            resp = client.post("/api/projects", json={
                "name": "api-proj",
                "connection_name": "pg",
                "source": "new",
            })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "api-proj"
        assert data["storage"] == "managed"

        resp = client.get("/api/projects/api-proj")
        assert resp.status_code == 200
        assert resp.json()["name"] == "api-proj"

    def test_create_duplicate_returns_409(self, client):
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            client.post("/api/projects", json={"name": "dup-api", "connection_name": "pg"})
            resp = client.post("/api/projects", json={"name": "dup-api", "connection_name": "pg"})
        assert resp.status_code == 409

    def test_get_missing_returns_404(self, client):
        resp = client.get("/api/projects/nope")
        assert resp.status_code == 404

    def test_update(self, client):
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            client.post("/api/projects", json={"name": "upd-api", "connection_name": "pg"})
        resp = client.put("/api/projects/upd-api", json={"description": "updated"})
        assert resp.status_code == 200
        assert resp.json()["description"] == "updated"

    def test_delete(self, client):
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            client.post("/api/projects", json={"name": "del-api", "connection_name": "pg"})
        resp = client.delete("/api/projects/del-api")
        assert resp.status_code == 204
        resp = client.get("/api/projects/del-api")
        assert resp.status_code == 404

    def test_delete_missing_returns_404(self, client):
        resp = client.delete("/api/projects/ghost")
        assert resp.status_code == 404

    def test_scan(self, client):
        conn = _make_connection("pg", "postgres")
        with patch("signalpilot.gateway.gateway.store.get_connection", return_value=conn):
            client.post("/api/projects", json={"name": "scan-api", "connection_name": "pg"})
        resp = client.post("/api/projects/scan-api/scan")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project"] == "scan-api"
        assert "scanned_at" in data

    def test_scan_missing_returns_404(self, client):
        resp = client.post("/api/projects/ghost/scan")
        assert resp.status_code == 404
