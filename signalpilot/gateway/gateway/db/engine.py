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


async def _ensure_byok_columns(engine) -> None:
    """Add BYOK columns to gateway_credentials and gateway_connections if they do not exist.

    SQLAlchemy's create_all does not add columns to existing tables, so this
    idempotent ALTER TABLE handles existing deployments. Postgres-only (no
    SQLite fallback — the gateway DB is always Postgres).

    gateway_credentials gains:
      - encryption_mode TEXT NOT NULL DEFAULT 'managed'
      - wrapped_dek BYTEA
      - byok_key_id TEXT

    gateway_connections gains:
      - org_id TEXT
      - byok_key_alias TEXT
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE gateway_credentials "
                "ADD COLUMN IF NOT EXISTS encryption_mode TEXT NOT NULL DEFAULT 'managed'"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE gateway_credentials "
                "ADD COLUMN IF NOT EXISTS wrapped_dek BYTEA"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE gateway_credentials "
                "ADD COLUMN IF NOT EXISTS byok_key_id TEXT"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE gateway_connections "
                "ADD COLUMN IF NOT EXISTS org_id TEXT"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE gateway_connections "
                "ADD COLUMN IF NOT EXISTS byok_key_alias TEXT"
            )
        )
    logger.info("Ensured BYOK columns on gateway_credentials and gateway_connections")


async def _ensure_org_id_columns(engine) -> None:
    """Add org_id columns and migrate from user_id scope to org_id scope.

    This is an additive, idempotent migration for existing deployments:
    1. Add org_id TEXT column if it does not exist (nullable initially).
    2. Backfill org_id = user_id WHERE org_id IS NULL (only runs when nullable).
    3. Set NOT NULL constraint on org_id.
    4. Drop old user-scoped unique constraints, add org-scoped ones.

    The information_schema probe makes step 2 idempotent: once NOT NULL is set,
    the probe returns 'NO' and the backfill is skipped on subsequent startups.
    """
    _migrations = [
        ("gateway_connections", "uq_gw_conn_user_name", "uq_gw_conn_org_name", "org_id, name"),
        ("gateway_credentials", "uq_gw_cred_user_conn", "uq_gw_cred_org_conn", "org_id, connection_name"),
        ("gateway_settings", "gateway_settings_user_id_key", "uq_gw_settings_org", "org_id"),
        ("gateway_audit_logs", None, None, None),
        ("gateway_projects", "uq_gw_proj_user_name", "uq_gw_proj_org_name", "org_id, name"),
        ("gateway_api_keys", None, None, None),
    ]
    for table, old_uq, new_uq, new_uq_cols in _migrations:
        async with engine.begin() as conn:
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS org_id TEXT"
            ))
            probe = await conn.execute(text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = :tname AND column_name = 'org_id'"
            ), {"tname": table})
            row = probe.fetchone()
            needs_backfill = row is not None and row[0] == "YES"
            if needs_backfill:
                if table == "gateway_settings":
                    # Dedupe: keep the most recent row per user_id before backfill
                    await conn.execute(text(
                        "DELETE FROM gateway_settings s1 "
                        "USING gateway_settings s2 "
                        "WHERE s1.user_id = s2.user_id AND s1.id > s2.id"
                    ))
                await conn.execute(text(
                    f"UPDATE {table} SET org_id = user_id WHERE org_id IS NULL"
                ))
                await conn.execute(text(
                    f"ALTER TABLE {table} ALTER COLUMN org_id SET NOT NULL"
                ))
            if old_uq:
                await conn.execute(text(
                    f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {old_uq}"
                ))
            if new_uq and new_uq_cols:
                await conn.execute(text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {new_uq} ON {table} ({new_uq_cols})"
                ))
    logger.info("Ensured org_id columns on gateway tables")


async def init_db() -> None:
    """Create gateway tables if they don't exist. Called at startup."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    await _ensure_key_version_column(engine)
    await _ensure_expires_at_column(engine)
    await _ensure_byok_columns(engine)
    await _ensure_org_id_columns(engine)
    logger.info("Gateway database tables initialized")


async def close_db() -> None:
    """Dispose engine on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
