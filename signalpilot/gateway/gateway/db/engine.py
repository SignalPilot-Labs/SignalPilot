"""Async SQLAlchemy engine for the gateway.

Shares the same DATABASE_URL as the backend but owns separate tables
(prefixed with gateway_).
"""

from __future__ import annotations

import os
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from .models import GatewayBase

logger = logging.getLogger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_database_url() -> str:
    """Get DATABASE_URL with asyncpg driver, stripping incompatible query params."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise ValueError(
            "DATABASE_URL is required but not set. "
            "Set it to a PostgreSQL connection string."
        )
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    # Strip query params that asyncpg doesn't support (sslmode, channel_binding, etc.)
    if "?" in url:
        url = url.split("?")[0]
    return url


def _requires_ssl() -> bool:
    """Check if the original DATABASE_URL had sslmode (e.g. Neon)."""
    raw = os.environ.get("DATABASE_URL", "")
    return "sslmode=" in raw


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


async def _ensure_key_version_column(engine) -> None:
    """Add key_version column to gateway_credentials if it does not exist.

    SQLAlchemy's create_all does not add columns to existing tables, so this
    idempotent ALTER TABLE handles existing deployments. Postgres-only (no
    SQLite fallback — the gateway DB is always Postgres).
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE gateway_credentials "
                "ADD COLUMN IF NOT EXISTS key_version INTEGER NOT NULL DEFAULT 1"
            )
        )
    logger.info("Ensured key_version column on gateway_credentials")


async def _ensure_expires_at_column(engine) -> None:
    """Add expires_at column to gateway_api_keys if it does not exist.

    SQLAlchemy's create_all does not add columns to existing tables, so this
    idempotent ALTER TABLE handles existing deployments.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE gateway_api_keys "
                "ADD COLUMN IF NOT EXISTS expires_at TEXT"
            )
        )
    logger.info("Ensured expires_at column on gateway_api_keys")


async def init_db() -> None:
    """Create gateway tables if they don't exist. Called at startup."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    await _ensure_key_version_column(engine)
    await _ensure_expires_at_column(engine)
    logger.info("Gateway database tables initialized")


async def close_db() -> None:
    """Dispose engine on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
