"""The upload quota must hold under genuinely concurrent initiations.

Each task gets its own database session, so these run against a real Postgres
(the reservation is serialized by a transaction-scoped advisory lock, which
sqlite cannot exercise). Skipped when no Postgres is reachable.
"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.api import uploads
from gateway.config.uploads import EvalUploadsSettings
from gateway.db.models import GatewayBase, GatewayUploadSession
from gateway.store import Store

_ADMIN_URL = os.getenv(
    "SP_TEST_PG_URL",
    "postgresql+asyncpg://signalpilot:changeme_dev_only@127.0.0.1:5601/signalpilot",
)
_TEST_DB = os.getenv("SP_TEST_PG_DB", "sp_upload_quota_test")
_TEST_URL = _ADMIN_URL.rsplit("/", 1)[0] + "/" + _TEST_DB

_ORG_ID = "test-org-upload-concurrency"
_USER_ID = "user-concurrent"

MB = 1024 * 1024


async def _ensure_test_database() -> None:
    admin = create_async_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            exists = await conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": _TEST_DB})
            if exists.scalar() is None:
                await conn.execute(text(f'CREATE DATABASE "{_TEST_DB}"'))
    finally:
        await admin.dispose()


@pytest_asyncio.fixture
async def session_factory():
    try:
        await _ensure_test_database()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not reachable for concurrency test: {exc}")

    engine = create_async_engine(_TEST_URL, pool_size=16, max_overflow=8)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(delete(GatewayUploadSession).where(GatewayUploadSession.org_id == _ORG_ID))
        await session.commit()
    yield factory
    async with factory() as session:
        await session.execute(delete(GatewayUploadSession).where(GatewayUploadSession.org_id == _ORG_ID))
        await session.commit()
    await engine.dispose()


class _FakeS3:
    def create_multipart_upload(self, **kwargs):
        return {"UploadId": "upload-concurrent"}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return "https://s3.test/part"


def _cfg(max_mb: int):
    return lambda: EvalUploadsSettings(
        SP_EVAL_UPLOADS_BUCKET="evals",
        SP_EVAL_UPLOADS_MAX_MB=max_mb,
        SP_EVAL_UPLOADS_S3_ACCESS_KEY="AK",
        SP_EVAL_UPLOADS_S3_SECRET_KEY="SK",
        SP_EVAL_UPLOADS_S3_REGION="us-east-1",
    )


@pytest.fixture(autouse=True)
def fake_s3(monkeypatch):
    monkeypatch.setattr(uploads, "_s3_client", lambda cfg, presign=False: _FakeS3())
    monkeypatch.setattr(uploads, "_notify", lambda *a, **k: None)


async def _initiate(factory, size_bytes: int) -> int:
    """Run one initiation on its own session; return the HTTP status."""
    async with factory() as session:
        store = Store(session, org_id=_ORG_ID, user_id=_USER_ID)
        try:
            await uploads.initiate_eval_upload(
                _USER_ID, store, uploads.InitiateRequest(filename="a.zip", size_bytes=size_bytes)
            )
            return 200
        except HTTPException as exc:
            return exc.status_code


async def _reserved(factory) -> list[GatewayUploadSession]:
    async with factory() as session:
        result = await session.execute(
            select(GatewayUploadSession).where(GatewayUploadSession.org_id == _ORG_ID)
        )
        return list(result.scalars())


@pytest.mark.asyncio
async def test_simultaneous_initiations_cannot_exceed_the_open_upload_cap(session_factory, monkeypatch):
    monkeypatch.setattr(uploads, "get_eval_uploads_settings", _cfg(max_mb=8192))

    statuses = await asyncio.gather(*[_initiate(session_factory, 10) for _ in range(12)])

    allowed = uploads._MAX_OPEN_UPLOADS_PER_USER
    assert statuses.count(200) == allowed
    assert statuses.count(429) == 12 - allowed
    assert len(await _reserved(session_factory)) == allowed


@pytest.mark.asyncio
async def test_simultaneous_initiations_cannot_exceed_the_byte_cap(session_factory, monkeypatch):
    # 100 MB ceiling, 60 MB per upload: only one can ever be outstanding.
    monkeypatch.setattr(uploads, "get_eval_uploads_settings", _cfg(max_mb=100))

    statuses = await asyncio.gather(*[_initiate(session_factory, 60 * MB) for _ in range(8)])

    assert statuses.count(200) == 1
    assert statuses.count(429) == 7
    rows = await _reserved(session_factory)
    assert sum(r.size_bytes for r in rows) <= 100 * MB
