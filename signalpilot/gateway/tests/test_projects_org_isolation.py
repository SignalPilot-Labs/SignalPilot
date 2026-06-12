"""Tests for F-1: org-keyed dbt project directory isolation."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase, GatewayProject
from gateway.models import ConnectionInfo, ProjectCreate
from gateway.store import _constants
from gateway.store.projects import (
    _org_projects_root,
    create_local_project,
    create_new_project,
    delete_project,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session(tmp_path):
    """In-memory SQLite session scoped per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Override DATA_DIR to a temp dir for FS isolation."""
    monkeypatch.setattr(_constants, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def dummy_connection() -> ConnectionInfo:
    return ConnectionInfo(
        id=str(uuid.uuid4()),
        org_id="test-org",
        name="conn",
        db_type="duckdb",
        database=":memory:",
    )


def _make_proj(name: str) -> ProjectCreate:
    return ProjectCreate(name=name, connection_name="conn", source="new")


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestProjectOrgIsolation:
    def test_two_orgs_same_name_get_distinct_dirs(self, data_dir, dummy_connection):
        """Org A and org B both create 'foo'; dirs are under their own org_id subtrees."""
        proj_a = create_new_project(_make_proj("foo"), dummy_connection, org_id="org-a")
        proj_b = create_new_project(_make_proj("foo"), dummy_connection, org_id="org-b")

        dir_a = Path(proj_a.project_dir)
        dir_b = Path(proj_b.project_dir)

        assert dir_a != dir_b
        assert dir_a.parts[-2] == "org-a"
        assert dir_b.parts[-2] == "org-b"
        assert (dir_a / "profiles.yml").exists()
        assert (dir_b / "profiles.yml").exists()
        # A's directory is untouched after B's create.
        assert dir_a.exists()

    def test_create_refuses_existing_dir(self, data_dir, dummy_connection):
        """Pre-existing non-empty dir causes ValueError — no silent overwrite."""
        org_id = "test-org"
        pre = _org_projects_root(org_id) / "myproj"
        pre.mkdir(parents=True)
        (pre / "somefile.txt").write_text("existing")

        with pytest.raises(ValueError, match="already exists on disk"):
            create_new_project(_make_proj("myproj"), dummy_connection, org_id=org_id)

    def test_invalid_org_id_rejected(self, data_dir, dummy_connection):
        """Org id with path traversal characters raises before any FS op."""
        with pytest.raises(ValueError, match="Invalid org_id"):
            create_new_project(_make_proj("proj"), dummy_connection, org_id="../etc")

    @pytest.mark.asyncio
    async def test_delete_refuses_path_outside_org_root(self, data_dir, db_session):
        """Managed storage project_dir outside org root raises; no rmtree."""
        outside_dir = data_dir / "outside" / "somedir"
        outside_dir.mkdir(parents=True)
        (outside_dir / "dbt_project.yml").write_text("name: somedir")

        row = GatewayProject(
            id=str(uuid.uuid4()),
            org_id="org-x",
            name="proj",
            connection_name="conn",
            project_dir=str(outside_dir),
            storage="managed",
        )
        db_session.add(row)
        await db_session.commit()

        with pytest.raises(ValueError, match="outside org root"):
            await delete_project(db_session, org_id="org-x", name="proj")

        # On-disk dir untouched.
        assert outside_dir.exists()

    @pytest.mark.asyncio
    async def test_delete_linked_project_skips_containment_check(self, data_dir, db_session, tmp_path):
        """Linked projects are deleted from DB without containment check or rmtree."""
        external_dir = tmp_path / "external_project"
        external_dir.mkdir()
        (external_dir / "dbt_project.yml").write_text("name: ext")

        row = GatewayProject(
            id=str(uuid.uuid4()),
            org_id="org-y",
            name="linked-proj",
            connection_name="conn",
            project_dir=str(external_dir),
            storage="linked",
        )
        db_session.add(row)
        await db_session.commit()

        result = await delete_project(db_session, org_id="org-y", name="linked-proj")

        assert result is True
        # On-disk dir is NOT removed.
        assert external_dir.exists()

    @pytest.mark.asyncio
    async def test_migrate_unambiguous_legacy_dir_moves_on_delete(self, data_dir, db_session):
        """Legacy DATA_DIR/projects/<name> is migrated to org-keyed path on delete."""
        legacy_dir = data_dir / "projects" / "legacy-proj"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "profiles.yml").write_text("target: dev")

        row = GatewayProject(
            id=str(uuid.uuid4()),
            org_id="org-z",
            name="legacy-proj",
            connection_name="conn",
            project_dir=str(legacy_dir),
            storage="managed",
        )
        db_session.add(row)
        await db_session.commit()

        result = await delete_project(db_session, org_id="org-z", name="legacy-proj")

        assert result is True
        # Legacy dir should be gone (migrated then rmtree'd).
        assert not legacy_dir.exists()
        # New org-keyed path should also be gone (rmtree'd after migration).
        new_dir = _org_projects_root("org-z") / "legacy-proj"
        assert not new_dir.exists()

    @pytest.mark.asyncio
    async def test_migrate_ambiguous_legacy_dir_raises(self, data_dir, db_session):
        """Two rows in different orgs sharing a legacy dir raise; dir and rows untouched."""
        legacy_dir = data_dir / "projects" / "shared-proj"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "dbt_project.yml").write_text("name: shared")

        row_a = GatewayProject(
            id=str(uuid.uuid4()),
            org_id="org-alpha",
            name="shared-proj",
            connection_name="conn",
            project_dir=str(legacy_dir),
            storage="managed",
        )
        row_b = GatewayProject(
            id=str(uuid.uuid4()),
            org_id="org-beta",
            name="shared-proj",
            connection_name="conn",
            project_dir=str(legacy_dir),
            storage="managed",
        )
        db_session.add(row_a)
        db_session.add(row_b)
        await db_session.commit()

        with pytest.raises(ValueError, match="shared by multiple orgs"):
            await delete_project(db_session, org_id="org-alpha", name="shared-proj")

        # On-disk dir untouched.
        assert legacy_dir.exists()
