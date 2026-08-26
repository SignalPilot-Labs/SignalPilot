"""dbt project directory detection + the resolve endpoint.

Hermetic: moto stands in for S3, aiosqlite for Postgres, and the app is
composed locally per test (same seam pattern as the v2 workspace scaffold —
replicated here, never imported).
"""

from __future__ import annotations

import base64
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from gateway.db.models import GatewayBase
from gateway.workspace_store.dbt_detect import (
    detect_dbt_project_dirs,
    resolve_dbt_project_dir,
    resolve_dbt_project_dir_detailed,
)

ORG = "test-org"
BUCKET = "sp-workspace-test"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dbt_mini"


def _pid() -> str:
    return str(uuid.uuid4())


# ── Detection unit tests (manifest = plain path lists) ───────────────────────


class TestDetectDbtProjectDirs:
    def test_root_project(self):
        paths = ["dbt_project.yml", "models/example.sql", "README.md"]
        assert detect_dbt_project_dirs(paths) == [""]

    def test_nested_project(self):
        paths = ["repo/analytics/dbt_project.yml", "repo/analytics/models/a.sql"]
        assert detect_dbt_project_dirs(paths) == ["repo/analytics"]

    def test_shallowest_first(self):
        paths = [
            "deep/nested/dbt_project.yml",
            "top/dbt_project.yml",
            "dbt_project.yml",
        ]
        assert detect_dbt_project_dirs(paths) == ["", "top", "deep/nested"]

    def test_same_depth_ties_break_alphabetically(self):
        paths = ["zeta/dbt_project.yml", "alpha/dbt_project.yml", "mid/dbt_project.yml"]
        assert detect_dbt_project_dirs(paths) == ["alpha", "mid", "zeta"]

    def test_lookalike_filenames_do_not_match(self):
        paths = [
            "a/not_dbt_project.yml",
            "b/dbt_project.yml.bak",
            "c/dbt_project.yaml",
            "dbt_project.yml/weird_dir_child.txt",  # a dir named like the file
        ]
        assert detect_dbt_project_dirs(paths) == []

    def test_empty_and_none_manifests(self):
        assert detect_dbt_project_dirs([]) == []
        assert detect_dbt_project_dirs(None) == []


class TestResolveDbtProjectDir:
    def test_no_setting_uses_first_detection(self):
        paths = ["b/dbt_project.yml", "a/dbt_project.yml"]
        assert resolve_dbt_project_dir(None, paths) == "a"
        assert resolve_dbt_project_dir({}, paths) == "a"

    def test_explicit_setting_overrides_detection(self):
        paths = ["a/dbt_project.yml", "b/dbt_project.yml", "b/models/x.sql"]
        assert resolve_dbt_project_dir({"dbt_project_dir": "b"}, paths) == "b"

    def test_explicit_setting_wins_even_without_a_dbt_project_yml_there(self):
        # Override is the user's call: the dir just has to exist in the manifest.
        paths = ["a/dbt_project.yml", "custom/models/x.sql"]
        value, source, detected = resolve_dbt_project_dir_detailed(
            {"dbt_project_dir": "custom"}, paths
        )
        assert (value, source) == ("custom", "setting")
        assert detected == ["a"]

    def test_setting_is_normalized(self):
        paths = ["analytics/dbt_project.yml", "analytics/models/x.sql"]
        assert resolve_dbt_project_dir({"dbt_project_dir": "/analytics/"}, paths) == "analytics"
        assert resolve_dbt_project_dir({"dbt_project_dir": "."}, paths) == ""

    def test_stale_setting_falls_back_to_detection_with_warning(self, caplog):
        paths = ["analytics/dbt_project.yml", "analytics/models/x.sql"]
        with caplog.at_level("WARNING", logger="gateway.workspace_store.dbt_detect"):
            value, source, detected = resolve_dbt_project_dir_detailed(
                {"dbt_project_dir": "gone/away"}, paths
            )
        assert (value, source, detected) == ("analytics", "detected", ["analytics"])
        assert any("dbt_project_dir" in rec.message for rec in caplog.records)

    def test_nothing_detected_and_no_setting_is_none(self):
        value, source, detected = resolve_dbt_project_dir_detailed(None, ["src/app.py"])
        assert (value, source, detected) == (None, "none", [])

    def test_non_string_setting_falls_back(self, caplog):
        with caplog.at_level("WARNING", logger="gateway.workspace_store.dbt_detect"):
            value = resolve_dbt_project_dir({"dbt_project_dir": 42}, ["a/dbt_project.yml"])
        assert value == "a"


# ── Hermetic fixtures (moto S3 + aiosqlite) ──────────────────────────────────


@pytest.fixture
def storage():
    from moto import mock_aws

    with mock_aws():
        import boto3

        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        from gateway.workspace_store.objects import WorkspaceObjectStorage

        yield WorkspaceObjectStorage(bucket=BUCKET, client=client)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def ws(storage):
    from gateway.workspace_store import WorkspaceStore

    return WorkspaceStore(storage)


class TestDetectionAgainstRealManifest:
    @pytest.mark.asyncio
    async def test_detection_reads_a_committed_manifest(self, ws, db):
        from gateway.workspace_store.store import Upsert

        project = _pid()
        await ws.commit(
            db,
            org_id=ORG,
            project_id=project,
            branch="main",
            base_revision=None,
            upserts=[
                Upsert(path="warehouse/dbt_project.yml", content=b"name: wh"),
                Upsert(path="warehouse/models/a.sql", content=b"select 1"),
                Upsert(path="notes.md", content=b"# notes"),
            ],
            deletes=[],
        )
        manifest = await ws.load_manifest(db, org_id=ORG, project_id=project, branch="main")
        assert detect_dbt_project_dirs(manifest) == ["warehouse"]
        assert resolve_dbt_project_dir(None, manifest) == "warehouse"


# ── App-level endpoint tests ─────────────────────────────────────────────────


def _workspace_app(storage, factory):
    """Fresh FastAPI app with just the workspace surface (local replica of the
    scaffold's composed-app seam — do not import the scaffold)."""
    from fastapi import FastAPI

    import gateway.api.workspace_files as wf
    from gateway.api.deps import require_projects_feature
    from gateway.api.workspace_files import router as files_router
    from gateway.api.workspace_projects import router as projects_router
    from gateway.auth import resolve_org_id, resolve_user_id
    from gateway.db.engine import get_db
    from gateway.security.scope_guard import _resolve_user_id as scope_resolve_user_id
    from gateway.workspace_store import WorkspaceStore

    app = FastAPI()
    app.include_router(projects_router)
    app.include_router(files_router)

    async def _get_db():
        async with factory() as session:
            yield session

    async def _user() -> str:
        return "test-user"

    async def _org() -> str:
        return ORG

    async def _no_gate() -> None:
        return None

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[resolve_user_id] = _user
    app.dependency_overrides[resolve_org_id] = _org
    app.dependency_overrides[scope_resolve_user_id] = _user
    app.dependency_overrides[require_projects_feature] = _no_gate
    app.dependency_overrides[wf.get_workspace_store] = lambda: WorkspaceStore(storage)
    return app


@pytest.fixture
def api(storage):
    import asyncio

    from fastapi.testclient import TestClient

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    async def _create_all():
        async with engine.begin() as conn:
            await conn.run_sync(GatewayBase.metadata.create_all)

    asyncio.run(_create_all())
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    client = TestClient(_workspace_app(storage, factory))
    yield client
    asyncio.run(engine.dispose())


def _create_project(api) -> str:
    response = api.post(
        "/api/workspace-projects",
        json={"name": f"proj-{uuid.uuid4().hex[:10]}", "display_name": "Test project"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _resolve(api, project: str, branch: str = "main") -> dict:
    response = api.get(f"/api/workspace-projects/{project}/dbt-project-dir?branch={branch}")
    assert response.status_code == 200, response.text
    return response.json()


class TestDbtProjectDirEndpoint:
    def test_empty_branch_resolves_to_none(self, api):
        project = _create_project(api)
        assert _resolve(api, project) == {
            "dbt_project_dir": None,
            "detected": [],
            "source": "none",
        }

    def test_detects_nested_project_from_manifest(self, api):
        project = _create_project(api)
        api.put(
            f"/api/workspace-projects/{project}/files/analytics/dbt_project.yml",
            content=b"name: analytics",
        )
        api.put(
            f"/api/workspace-projects/{project}/files/analytics/models/a.sql",
            content=b"select 1",
        )
        body = _resolve(api, project)
        assert body == {
            "dbt_project_dir": "analytics",
            "detected": ["analytics"],
            "source": "detected",
        }

    def test_shallowest_then_alphabetical(self, api):
        project = _create_project(api)
        for path in (
            "zeta/dbt_project.yml",
            "alpha/dbt_project.yml",
            "deep/nested/dbt_project.yml",
        ):
            api.put(f"/api/workspace-projects/{project}/files/{path}", content=b"name: x")
        body = _resolve(api, project)
        assert body["dbt_project_dir"] == "alpha"
        assert body["detected"] == ["alpha", "zeta", "deep/nested"]

    def test_put_settings_merge_then_setting_wins(self, api):
        """The EXISTING PUT settings path persists dbt_project_dir and the
        resolver honors it over detection."""
        project = _create_project(api)
        for path in ("alpha/dbt_project.yml", "zeta/dbt_project.yml"):
            api.put(f"/api/workspace-projects/{project}/files/{path}", content=b"name: x")

        updated = api.put(
            f"/api/workspace-projects/{project}",
            json={"settings": {"dbt_project_dir": "zeta"}},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["settings"] == {"dbt_project_dir": "zeta"}
        # And it round-trips through a plain GET of the project.
        fetched = api.get(f"/api/workspace-projects/{project}")
        assert fetched.json()["settings"] == {"dbt_project_dir": "zeta"}

        body = _resolve(api, project)
        assert body == {
            "dbt_project_dir": "zeta",
            "detected": ["alpha", "zeta"],
            "source": "setting",
        }

    def test_stale_setting_falls_back_to_detection(self, api):
        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/real/dbt_project.yml", content=b"x")
        api.put(
            f"/api/workspace-projects/{project}",
            json={"settings": {"dbt_project_dir": "moved/away"}},
        )
        body = _resolve(api, project)
        assert body == {
            "dbt_project_dir": "real",
            "detected": ["real"],
            "source": "detected",
        }

    def test_branch_isolation(self, api):
        project = _create_project(api)
        api.put(
            f"/api/workspace-projects/{project}/files/dbt_project.yml?branch=dev",
            content=b"name: dev-only",
        )
        assert _resolve(api, project, branch="dev")["dbt_project_dir"] == ""
        assert _resolve(api, project, branch="main")["source"] == "none"

    def test_unknown_project_is_404(self, api):
        response = api.get(f"/api/workspace-projects/{uuid.uuid4()}/dbt-project-dir")
        assert response.status_code == 404

    def test_invalid_branch_is_400(self, api):
        project = _create_project(api)
        response = api.get(
            f"/api/workspace-projects/{project}/dbt-project-dir?branch=..evil"
        )
        assert response.status_code == 400


class TestDbtMiniFixtureImport:
    def test_fixture_import_via_batch_is_detected(self, api):
        """Seed for future project-creation E2E: import tests/fixtures/dbt_mini
        through files:batch and detect it at its import prefix."""
        files = sorted(p for p in FIXTURE_DIR.rglob("*") if p.is_file())
        assert files, f"fixture missing at {FIXTURE_DIR}"
        assert len(files) < 10

        project = _create_project(api)
        upserts = [
            {
                "path": f"dbt_mini/{p.relative_to(FIXTURE_DIR).as_posix()}",
                "content_b64": base64.b64encode(p.read_bytes()).decode(),
            }
            for p in files
        ]
        batch = api.post(
            f"/api/workspace-projects/{project}/files:batch",
            json={
                "branch": "main",
                "base_revision": None,
                "upserts": upserts,
                "deletes": [],
                "message": "import dbt_mini fixture",
            },
        )
        assert batch.status_code == 200, batch.text
        assert batch.json()["file_count"] == len(files)

        body = _resolve(api, project)
        assert body == {
            "dbt_project_dir": "dbt_mini",
            "detected": ["dbt_mini"],
            "source": "detected",
        }
