"""Shared fixtures for the published-dashboard tests: fake storage, specs, rows."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.dashboards.serializers import PublishDashboardRequest, RefreshSettingsIn
from gateway.dashboards.storage import DashboardStorage
from gateway.db.models import GatewayBase, GatewayChatFile, GatewayWorkspaceProject
from gateway.standalone_chat.object_storage import StoredObject
from gateway.store import standalone_chat as chat_store

ORG = "org-a"
USER = "user-a"
OTHER_USER = "user-b"
PROJECT = "project-a"


class FakeObjectStore:
    """In-memory stand-in for ChatObjectStorage."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}

    def _stored(self, key: str) -> StoredObject:
        data = self.objects[key]
        return StoredObject(key=key, byte_size=len(data), content_hash=hashlib.sha256(data).hexdigest())

    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> StoredObject:
        self.objects[key] = data
        self.content_types[key] = content_type
        return self._stored(key)

    async def get_bytes(self, key: str, *, max_bytes: int | None = None) -> bytes:
        return self.objects[key]

    async def delete_prefix(self, prefix: str) -> int:
        keys = [key for key in self.objects if key.startswith(prefix.rstrip("/") + "/")]
        for key in keys:
            del self.objects[key]
        return len(keys)


def fake_storage() -> tuple[DashboardStorage, FakeObjectStore]:
    backend = FakeObjectStore()
    return DashboardStorage(backend), backend


def spec_json() -> dict:
    """A valid two-dataset spec: one SQL-backed file, one static snapshot."""
    return {
        "version": 1,
        "title": "Revenue",
        "description": "Monthly revenue",
        "datasets": {
            "monthly": {
                "file": "artifacts/monthly.csv",
                "source": {"kind": "sql", "connection": "warehouse", "sql": "select month, revenue from m"},
            },
            "regions": {"file": "artifacts/regions.csv"},
            "inline": {"rows": [{"k": "a", "v": 1}]},
        },
        "charts": [
            {
                "id": "rev_line",
                "type": "line",
                "title": "Revenue by month",
                "dataset": "monthly",
                "x": {"column": "month", "type": "date"},
                "y": [{"column": "revenue"}],
            },
            {
                "id": "region_table",
                "type": "table",
                "title": "Regions",
                "dataset": "regions",
                "columns": [{"column": "region"}, {"column": "total"}],
            },
            {"id": "kpi", "type": "kpi", "title": "Inline", "dataset": "inline", "value": {"column": "v"}},
        ],
    }


MONTHLY_CSV = b"month,revenue\n2026-01-01,100\n2026-02-01,120\n"
REGIONS_CSV = b"region,total\nnorth,10\nsouth,\n"


def manifest_row(path: str, data: bytes, *, run_id: str = "run-1", file_id: str | None = None):
    return SimpleNamespace(
        id=file_id or f"file-{path.rsplit('/', 1)[-1]}",
        path=path,
        filename=path.rsplit("/", 1)[-1],
        kind="dashboard" if path.endswith(".dashboard.json") else "data",
        status="active",
        object_key=f"chat/{path}",
        origin_run_id=run_id,
        updated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def fake_manifest(backend: FakeObjectStore, spec: dict | None = None, *, run_id: str = "run-1"):
    """Manifest rows plus stored bytes for the spec and both dataset files."""
    spec = spec or spec_json()
    rows = [
        manifest_row("artifacts/revenue.dashboard.json", json.dumps(spec).encode(), run_id=run_id, file_id="file-dash"),
        manifest_row("artifacts/monthly.csv", MONTHLY_CSV, run_id=run_id),
        manifest_row("artifacts/regions.csv", REGIONS_CSV, run_id=run_id),
    ]
    for row in rows:
        backend.objects[row.object_key] = json.dumps(spec).encode() if row.kind == "dashboard" else (
            MONTHLY_CSV if row.path.endswith("monthly.csv") else REGIONS_CSV
        )
    return rows


def publish_body(**overrides) -> PublishDashboardRequest:
    values = {
        "name": "Revenue",
        "visibility": "org",
        "refresh": RefreshSettingsIn(interval_minutes=1440, anchor_time="06:00", timezone="UTC", mode="sql"),
        "notify_on_failure": True,
    }
    values.update(overrides)
    return PublishDashboardRequest(**values)


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    # File-backed, not :memory:, so each session gets its own connection and
    # concurrent sessions (the scheduler runs refreshes in parallel) are
    # isolated from one another the way they are on Postgres.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'dashboards.sqlite'}", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _fast_sqlite(connection, _record):
        # Test-only durability trade: no fsync, journal in memory.
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA journal_mode=MEMORY")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def db(session_factory):
    async with session_factory() as session:
        yield session


async def add_project(db: AsyncSession, project_id: str = PROJECT) -> GatewayWorkspaceProject:
    project = GatewayWorkspaceProject(
        id=project_id,
        org_id=ORG,
        name="revenue",
        display_name="Revenue",
        connection_name="warehouse",
        source="managed",
        status="active",
        settings={},
        file_count=1,
        total_bytes=10,
        default_branch="main",
        created_at=1.0,
        updated_at=1.0,
    )
    db.add(project)
    await db.commit()
    return project


async def add_conversation_with_files(db: AsyncSession, backend: FakeObjectStore, *, user_id: str = USER):
    """A real conversation whose manifest holds the fake dashboard files."""
    project = await add_project(db)
    conversation, run = await chat_store.create_conversation_with_run(
        db,
        org_id=ORG,
        user_id=user_id,
        project=project,
        branch="main",
        message="Build a revenue dashboard",
        commit_sha="a" * 40,
    )
    rows: list[GatewayChatFile] = []
    for entry in fake_manifest(backend, run_id=run.id):
        rows.append(
            await chat_store.upsert_conversation_file(
                db,
                org_id=ORG,
                user_id=user_id,
                conversation_id=conversation.id,
                path=entry.path,
                filename=entry.filename,
                mime_type=None,
                byte_size=len(backend.objects[entry.object_key]),
                content_hash=hashlib.sha256(backend.objects[entry.object_key]).hexdigest(),
                object_key=entry.object_key,
                origin_run_id=run.id,
                origin="mirror",
                file_id=entry.id,
            )
        )
    return conversation, run, rows


def api_store(db: AsyncSession, user_id: str = USER):
    return SimpleNamespace(session=db, user_id=user_id, org_id=ORG, _require_org_id=lambda: ORG)
