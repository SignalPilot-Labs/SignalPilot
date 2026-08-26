"""Env-gated live import: walk a real dbt project from disk (path from
SP_TEST_DBT_PROJECT_DIR — never hardcoded), import it into a moto-backed
workspace project via files:batch, and assert detection resolves the real
dbt project directory. Skips cleanly when the env var is unset.
"""

from __future__ import annotations

import base64
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from gateway.db.models import GatewayBase

ORG = "test-org"
BUCKET = "sp-workspace-test"
ENV_VAR = "SP_TEST_DBT_PROJECT_DIR"

_MAX_FILE_BYTES = 8 * 1024 * 1024
_MAX_BATCH_FILES = 200
_MAX_BATCH_BYTES = 4 * 1024 * 1024  # keep each JSON body comfortably small
_IGNORED_DIRS = {
    ".git",
    "target",
    "node_modules",
    "logs",
    "dbt_packages",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
}

pytestmark = pytest.mark.skipif(
    not os.environ.get(ENV_VAR),
    reason=f"{ENV_VAR} not set — live dbt-project import test skipped",
)


@pytest.fixture
def storage():
    from moto import mock_aws

    with mock_aws():
        import boto3

        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        from gateway.workspace_store.objects import WorkspaceObjectStorage

        yield WorkspaceObjectStorage(bucket=BUCKET, client=client)


def _workspace_app(storage, factory):
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


def _walk_importable(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in _IGNORED_DIRS for part in rel_parts[:-1]):
            continue
        if path.stat().st_size > _MAX_FILE_BYTES:
            continue
        files.append(path)
    return files


def test_live_dbt_project_import_and_detection(api):
    from gateway.workspace_store.dbt_detect import detect_dbt_project_dirs

    root = Path(os.environ[ENV_VAR])
    assert root.is_dir(), f"{ENV_VAR} does not point at a directory: {root}"

    files = _walk_importable(root)
    assert files, f"No importable files under {root}"

    # Ground truth straight from disk: where do dbt_project.yml files live
    # (outside the ignore list)? Shallowest-then-alphabetical, same contract.
    disk_paths = [p.relative_to(root).as_posix() for p in files]
    expected = detect_dbt_project_dirs(disk_paths)
    assert expected, f"No dbt_project.yml found under {root} — wrong directory?"

    response = api.post(
        "/api/workspace-projects",
        json={"name": f"live-{uuid.uuid4().hex[:10]}", "display_name": "Live dbt import"},
    )
    assert response.status_code == 201, response.text
    project = response.json()["id"]

    # Import through files:batch in bounded chunks (count and payload size).
    revision = None
    batch: list[dict] = []
    batch_bytes = 0

    def _flush():
        nonlocal revision, batch, batch_bytes
        if not batch:
            return
        result = api.post(
            f"/api/workspace-projects/{project}/files:batch",
            json={
                "branch": "main",
                "base_revision": revision,
                "upserts": batch,
                "deletes": [],
                "message": "live import chunk",
            },
        )
        assert result.status_code == 200, result.text
        revision = result.json()["revision"]
        batch = []
        batch_bytes = 0

    for path in files:
        content = path.read_bytes()
        batch.append(
            {
                "path": path.relative_to(root).as_posix(),
                "content_b64": base64.b64encode(content).decode(),
            }
        )
        batch_bytes += len(content)
        if len(batch) >= _MAX_BATCH_FILES or batch_bytes >= _MAX_BATCH_BYTES:
            _flush()
    _flush()

    listing = api.post(
        f"/api/workspace-projects/{project}/files:list", json={"branch": "main"}
    )
    assert len(listing.json()["files"]) == len(files)

    body = api.get(f"/api/workspace-projects/{project}/dbt-project-dir").json()
    assert body["detected"] == expected
    assert body["dbt_project_dir"] == expected[0]
    assert body["source"] == "detected"
    print(
        f"\n[live] imported {len(files)} files from {root}; "
        f"detected={body['detected']!r} resolved={body['dbt_project_dir']!r}"
    )
