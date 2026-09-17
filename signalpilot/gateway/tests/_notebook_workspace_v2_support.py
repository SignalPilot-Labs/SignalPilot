"""Shared hermetic fixtures for the Notebook Runtime v2 target suite.

moto stands in for S3, aiosqlite for Postgres. Imported by every
``test_notebook_workspace_v2_scaffold*.py`` module so they share one app
composition and one set of fixtures.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from gateway.db.models import GatewayBase

ORG = "test-org"
BUCKET = "sp-workspace-test"


def _target(section: str, gate: str):
    pytest.skip(f"v2 target — spec {section}, migration gate {gate}: not built yet")


def _pid() -> str:
    return str(uuid.uuid4())


# ── Shared hermetic fixtures ─────────────────────────────────────────────────


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


async def _put(ws, db, project, path, content: bytes, branch="main", by="tester"):
    from gateway.workspace_store.store import Upsert

    return await ws.commit_at_head(
        db,
        org_id=ORG,
        project_id=project,
        branch=branch,
        upserts=[Upsert(path=path, content=content)],
        deletes=[],
        created_by=by,
    )


# ── App composition for the §4.2 Files API tests ────────────────────────────
# App-level: the real gateway app, local API key auth, aiosqlite DB override,
# moto-backed storage injected at the module seam.


def _workspace_app(storage, factory):
    """A fresh FastAPI app carrying exactly the v2 workspace surface.

    Composed per test — no shared singleton, no middleware stack, no
    cross-module state to bleed in. Auth resolves to the fixture identity via
    ordinary dependency overrides on this app instance only; the anonymous
    client below simply omits them.
    """
    from fastapi import FastAPI

    import gateway.api.workspace_files as wf
    from gateway.api.deps import require_billable_plan
    from gateway.api.workspace_files import router as files_router
    from gateway.api.workspace_projects import router as projects_router
    from gateway.auth import resolve_org_id, resolve_user_id
    from gateway.db.engine import get_db
    from gateway.security.scope_guard import _resolve_user_id as scope_resolve_user_id

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
    app.dependency_overrides[require_billable_plan] = _no_gate
    from gateway.workspace_store import WorkspaceStore

    app.dependency_overrides[wf.get_workspace_store] = lambda: WorkspaceStore(storage)
    return app


@pytest.fixture
def api(storage):
    """Authenticated client over the fresh workspace app + aiosqlite + moto."""
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
    app = _workspace_app(storage, factory)
    client = TestClient(app)
    client.app = app  # anonymous-client tests derive from the same app
    yield client
    asyncio.run(engine.dispose())


def _create_project(api) -> str:
    response = api.post(
        "/api/workspace-projects",
        json={"name": f"proj-{uuid.uuid4().hex[:10]}", "display_name": "Test project"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _run(coroutine):
    import asyncio

    return asyncio.run(coroutine)
