from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api import dashboards as dashboard_api
from gateway.dashboard import project_snapshot, semantic_resolver
from gateway.dashboard.project_snapshot import (
    ensure_branch_snapshot,
    materialize_workspace_snapshot,
    resolve_branch_snapshot,
)
from gateway.dashboard.semantic_resolver import DashboardSemanticError
from gateway.db.models import GatewayBase, GatewayWorkspaceRevision
from gateway.workspace_store.store import Upsert, WorkspaceStore


class MemoryWorkspaceStorage:
    bucket = "test-workspace"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    @property
    def enabled(self) -> bool:
        return True

    async def put_bytes(self, key: str, data: bytes, **_kwargs) -> None:
        self.objects[key] = data

    async def get_bytes(self, key: str) -> bytes | None:
        return self.objects.get(key)

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def head_size(self, key: str) -> int | None:
        value = self.objects.get(key)
        return len(value) if value is not None else None


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_workspace(db: AsyncSession, storage: MemoryWorkspaceStorage) -> str:
    manifest = await WorkspaceStore(storage).commit(
        db,
        org_id="org-a",
        project_id="project-a",
        branch="main",
        base_revision=None,
        upserts=[
            Upsert(
                path="dbt_project.yml",
                content=b"name: revenue\nversion: '1.0'\nprofile: revenue\nmodel-paths: ['models']\n",
            ),
            Upsert(
                path="models/orders.sql",
                content=b"select 1 as order_id\n",
            ),
        ],
        deletes=[],
        created_by="test",
        message="durable dashboard fixture",
    )
    return str(manifest.revision)


@pytest.mark.asyncio
async def test_workspace_snapshot_resolves_and_materializes_without_git(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    storage = MemoryWorkspaceStorage()
    await _seed_workspace(db_session, storage)

    snapshot_ref = await resolve_branch_snapshot(
        db_session,
        storage,
        org_id="org-a",
        project_id="project-a",
        branch="main",
    )

    assert snapshot_ref is not None
    assert len(snapshot_ref) == 40
    assert await materialize_workspace_snapshot(
        db_session,
        storage,
        org_id="org-a",
        project_id="project-a",
        snapshot_ref=snapshot_ref,
        destination=tmp_path,
    )
    assert (tmp_path / "dbt_project.yml").read_text().startswith("name: revenue")
    assert (tmp_path / "models/orders.sql").read_text() == "select 1 as order_id\n"


@pytest.mark.asyncio
async def test_exported_legacy_git_sha_materializes_from_its_workspace_revision(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    storage = MemoryWorkspaceStorage()
    await _seed_workspace(db_session, storage)
    legacy_commit_sha = "a" * 40
    await db_session.execute(
        update(GatewayWorkspaceRevision)
        .where(
            GatewayWorkspaceRevision.org_id == "org-a",
            GatewayWorkspaceRevision.project_id == "project-a",
            GatewayWorkspaceRevision.branch == "main",
            GatewayWorkspaceRevision.revision == 0,
        )
        .values(export_commit_sha=legacy_commit_sha)
    )
    await db_session.commit()

    assert project_snapshot._snapshot_revision(legacy_commit_sha) is None
    assert await materialize_workspace_snapshot(
        db_session,
        storage,
        org_id="org-a",
        project_id="project-a",
        snapshot_ref=legacy_commit_sha,
        destination=tmp_path,
    )
    assert (tmp_path / "models/orders.sql").read_text() == "select 1 as order_id\n"


@pytest.mark.asyncio
async def test_semantic_scan_uses_workspace_snapshot_when_local_repo_is_absent(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = MemoryWorkspaceStorage()
    await _seed_workspace(db_session, storage)
    snapshot_ref = await resolve_branch_snapshot(
        db_session,
        storage,
        org_id="org-a",
        project_id="project-a",
        branch="main",
    )
    assert snapshot_ref is not None
    monkeypatch.setattr(semantic_resolver, "workspace_object_storage", lambda: storage)
    monkeypatch.setattr(
        semantic_resolver,
        "_scan_commit",
        lambda *_args, **_kwargs: pytest.fail("local git fallback must not run"),
    )

    project_map = await semantic_resolver._scan_pinned_project(
        SimpleNamespace(session=db_session),
        org_id="org-a",
        project_id="project-a",
        commit_sha=snapshot_ref,
    )

    assert project_map.project_name == "revenue"
    assert "orders" in project_map.models


@pytest.mark.asyncio
async def test_authoring_head_prefers_durable_snapshot_over_local_git(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = MemoryWorkspaceStorage()
    await _seed_workspace(db_session, storage)
    monkeypatch.setattr(dashboard_api, "workspace_object_storage", lambda: storage)
    monkeypatch.setattr(
        dashboard_api,
        "branch_head_sha",
        lambda *_args, **_kwargs: pytest.fail("local git fallback must not run"),
    )

    resolved = await dashboard_api._resolve_project_immutable_head(
        SimpleNamespace(session=db_session),
        org_id="org-a",
        project_id="project-a",
        branch="main",
    )

    assert resolved == await resolve_branch_snapshot(
        db_session,
        storage,
        org_id="org-a",
        project_id="project-a",
        branch="main",
    )


@pytest.mark.asyncio
async def test_cloud_authoring_never_persists_an_ephemeral_git_head(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = MemoryWorkspaceStorage()

    async def no_durable_snapshot(*_args, **_kwargs):
        return None

    monkeypatch.setattr(dashboard_api, "workspace_object_storage", lambda: storage)
    monkeypatch.setattr(dashboard_api, "ensure_branch_snapshot", no_durable_snapshot)
    monkeypatch.setattr(
        dashboard_api,
        "branch_head_sha",
        lambda *_args, **_kwargs: pytest.fail("cloud must not use an ephemeral git head"),
    )

    assert (
        await dashboard_api._resolve_project_immutable_head(
            SimpleNamespace(session=db_session),
            org_id="org-a",
            project_id="project-a",
            branch="main",
        )
        is None
    )


@pytest.mark.asyncio
async def test_missing_mirror_is_hydrated_and_imported_to_a_durable_snapshot(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = MemoryWorkspaceStorage()
    resolved_snapshots = iter([None, "d" * 40])
    imported: list[str] = []

    async def fake_resolve(*_args, **_kwargs):
        return next(resolved_snapshots)

    async def fake_hydrate(*_args, **_kwargs):
        return True

    async def fake_import(*_args, **kwargs):
        imported.append(kwargs["branch"])

    from gateway.git import repos
    from gateway.workspace_store import github_sync

    monkeypatch.setattr(project_snapshot, "resolve_branch_snapshot", fake_resolve)
    monkeypatch.setattr(project_snapshot, "hydrate_github_mirror", fake_hydrate)
    monkeypatch.setattr(repos, "branch_head_sha", lambda *_args: None)
    monkeypatch.setattr(github_sync, "import_repo_to_revisions", fake_import)

    assert (
        await ensure_branch_snapshot(
            db_session,
            storage,
            org_id="org-a",
            project_id="project-a",
            branch="main",
        )
        == "d" * 40
    )
    assert imported == ["main"]


@pytest.mark.asyncio
async def test_legacy_git_commit_rehydrates_missing_mirror(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scans = 0

    async def no_workspace_snapshot(*_args, **_kwargs):
        return False

    def scan_after_recovery(*_args, **_kwargs):
        nonlocal scans
        scans += 1
        if scans == 1:
            raise DashboardSemanticError("The pinned project commit is unavailable")
        return "recovered-project-map"

    async def fake_hydrate(*_args, **_kwargs):
        return True

    monkeypatch.setattr(semantic_resolver, "workspace_object_storage", MemoryWorkspaceStorage)
    monkeypatch.setattr(semantic_resolver, "materialize_workspace_snapshot", no_workspace_snapshot)
    monkeypatch.setattr(semantic_resolver, "_scan_commit", scan_after_recovery)
    monkeypatch.setattr(semantic_resolver, "hydrate_github_mirror", fake_hydrate)

    assert (
        await semantic_resolver._scan_pinned_project(
            SimpleNamespace(session=db_session),
            org_id="org-a",
            project_id="project-a",
            commit_sha="a" * 40,
        )
        == "recovered-project-map"
    )
    assert scans == 2
