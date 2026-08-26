"""Async SQLAlchemy engine for the gateway.

Shares the same DATABASE_URL as the backend but owns separate tables
(prefixed with gateway_).
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from urllib.parse import parse_qs, urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool

from .legacy_bootstrap import run_legacy_bootstrap
from .migrate import stamp_head, upgrade_to_head

logger = logging.getLogger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_database_url() -> str:
    """Get DATABASE_URL with asyncpg driver, stripping incompatible query params."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise ValueError("DATABASE_URL is required but not set. Set it to a PostgreSQL connection string.")
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    # Strip query params that asyncpg doesn't support (sslmode, channel_binding, etc.)
    if "?" in url:
        url = url.split("?")[0]
    return url


def _requires_ssl() -> bool:
    """Check if the original DATABASE_URL requested SSL via sslmode, ssl, or channel_binding."""
    raw = os.environ.get("DATABASE_URL", "") or ""
    if not raw:
        return False
    try:
        q = parse_qs(urlparse(raw).query)
    except Exception:
        return False
    sslmode = (q.get("sslmode", [""])[0] or "").lower()
    if sslmode in {"require", "verify-ca", "verify-full"}:
        return True
    ssl_param = (q.get("ssl", [""])[0] or "").lower()
    if ssl_param in {"true", "require"}:
        return True
    if q.get("channel_binding"):
        cb = (q.get("channel_binding", [""])[0] or "").lower()
        if cb in {"require", "prefer"}:
            return True
    return False


def get_engine():
    global _engine, _session_factory
    if _engine is None:
        url = _get_database_url()
        connect_args: dict = {}
        if _requires_ssl():
            connect_args["ssl"] = True
        connect_args["statement_cache_size"] = 0

        _engine = create_async_engine(
            url,
            poolclass=AsyncAdaptedQueuePool,
            pool_size=5,
            max_overflow=10,
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session. Use as a FastAPI dependency."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Migrate the gateway schema to the current Alembic head. Called at startup.

    Three deployment states are handled:

    - fresh database (no gateway tables): the full migration chain in
      gateway/db/migrations/versions/ builds the schema
    - pre-Alembic database (gateway tables but no gateway_alembic_version):
      the frozen legacy bootstrap (create_all + ensure helpers) runs one last
      time to reach the baseline shape, then the database is stamped at head
    - Alembic-managed database: pending migrations are applied

    Several worker processes (gateway, chat worker, slack worker) call this
    concurrently at startup, so the whole step runs under a session-level
    Postgres advisory lock.
    """
    engine = get_engine()
    database_url = os.environ["DATABASE_URL"]
    async with engine.connect() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(hashtext('gateway_schema_migration'))"))
        try:
            has_version_table = (
                await conn.execute(text("SELECT to_regclass('public.gateway_alembic_version')"))
            ).scalar()
            has_gateway_tables = (
                await conn.execute(text("SELECT to_regclass('public.gateway_connections')"))
            ).scalar()
            if has_version_table is None and has_gateway_tables is not None:
                logger.info("Pre-Alembic database detected — running legacy bootstrap, then stamping head")
                await run_legacy_bootstrap(engine)
                await asyncio.to_thread(stamp_head, database_url)
            else:
                await asyncio.to_thread(upgrade_to_head, database_url)
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(hashtext('gateway_schema_migration'))"))
    logger.info("Gateway database schema is up to date")


async def close_db() -> None:
    """Dispose engine on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
