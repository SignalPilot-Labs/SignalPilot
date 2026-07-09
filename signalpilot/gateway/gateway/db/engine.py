"""Async SQLAlchemy engine for the gateway.

Shares the same DATABASE_URL as the backend but owns separate tables
(prefixed with gateway_).
"""

from __future__ import annotations

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

from .models import GatewayBase

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


async def _ensure_key_version_column(engine) -> None:
    """Add key_version column to gateway_credentials if it does not exist.

    SQLAlchemy's create_all does not add columns to existing tables, so this
    idempotent ALTER TABLE handles existing deployments. Postgres-only (no
    SQLite fallback — the gateway DB is always Postgres).
    """
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE gateway_credentials ADD COLUMN IF NOT EXISTS key_version INTEGER NOT NULL DEFAULT 1")
        )
    logger.info("Ensured key_version column on gateway_credentials")


async def _ensure_expires_at_column(engine) -> None:
    """Add expires_at column to gateway_api_keys if it does not exist.

    SQLAlchemy's create_all does not add columns to existing tables, so this
    idempotent ALTER TABLE handles existing deployments.
    """
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE gateway_api_keys ADD COLUMN IF NOT EXISTS expires_at TEXT"))
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
        await conn.execute(text("ALTER TABLE gateway_credentials ADD COLUMN IF NOT EXISTS wrapped_dek BYTEA"))
        await conn.execute(text("ALTER TABLE gateway_credentials ADD COLUMN IF NOT EXISTS byok_key_id TEXT"))
        await conn.execute(text("ALTER TABLE gateway_connections ADD COLUMN IF NOT EXISTS org_id TEXT"))
        await conn.execute(text("ALTER TABLE gateway_connections ADD COLUMN IF NOT EXISTS byok_key_alias TEXT"))
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
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS org_id TEXT"))
            probe = await conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = :tname AND column_name = 'org_id'"
                ),
                {"tname": table},
            )
            row = probe.fetchone()
            needs_backfill = row is not None and row[0] == "YES"
            if needs_backfill:
                if table == "gateway_settings":
                    # Dedupe: keep the most recent row per user_id before backfill
                    await conn.execute(
                        text(
                            "DELETE FROM gateway_settings s1 "
                            "USING gateway_settings s2 "
                            "WHERE s1.user_id = s2.user_id AND s1.id > s2.id"
                        )
                    )
                await conn.execute(text(f"UPDATE {table} SET org_id = user_id WHERE org_id IS NULL"))
                await conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN org_id SET NOT NULL"))
            if old_uq:
                await conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {old_uq}"))
            if new_uq and new_uq_cols:
                await conn.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {new_uq} ON {table} ({new_uq_cols})"))
    logger.info("Ensured org_id columns on gateway tables")


async def _ensure_health_columns(engine) -> None:
    """Add health monitoring columns to gateway_connections if they do not exist."""
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE gateway_connections ADD COLUMN IF NOT EXISTS health_last_check DOUBLE PRECISION")
        )
        await conn.execute(text("ALTER TABLE gateway_connections ADD COLUMN IF NOT EXISTS health_last_error TEXT"))
        await conn.execute(
            text(
                "ALTER TABLE gateway_connections "
                "ADD COLUMN IF NOT EXISTS health_consecutive_failures INTEGER NOT NULL DEFAULT 0"
            )
        )
    logger.info("Ensured health columns on gateway_connections")


async def _ensure_plan_tier_column(engine) -> None:
    """Add plan_tier column to gateway_orgs if it does not exist."""
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE gateway_orgs ADD COLUMN IF NOT EXISTS plan_tier VARCHAR(20) NOT NULL DEFAULT 'free'")
        )
    logger.info("Ensured plan_tier column on gateway_orgs")


async def _ensure_audit_ip_columns(engine) -> None:
    """Add client_ip and user_agent columns to gateway_audit_logs if they do not exist.

    SQLAlchemy's create_all does not add columns to existing tables, so this
    idempotent ALTER TABLE handles existing deployments.
    """
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE gateway_audit_logs ADD COLUMN IF NOT EXISTS client_ip TEXT"))
        await conn.execute(text("ALTER TABLE gateway_audit_logs ADD COLUMN IF NOT EXISTS user_agent TEXT"))
    logger.info("Ensured client_ip and user_agent columns on gateway_audit_logs")


async def _ensure_audit_parent_id_column(engine) -> None:
    """Add parent_id column to gateway_audit_logs for linking child SQL to parent tool calls."""
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE gateway_audit_logs ADD COLUMN IF NOT EXISTS parent_id TEXT"))
    logger.info("Ensured parent_id column on gateway_audit_logs")


async def _ensure_audit_user_id_nullable(engine) -> None:
    """Make user_id nullable on gateway_audit_logs (was NOT NULL from original create_all)."""
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE gateway_audit_logs ALTER COLUMN user_id DROP NOT NULL"))
    logger.info("Ensured user_id is nullable on gateway_audit_logs")


async def _ensure_audit_indexes(engine) -> None:
    """Add performance indexes on gateway_audit_logs for large audit tables."""
    async with engine.begin() as conn:
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_audit_org_ts ON gateway_audit_logs (org_id, timestamp DESC)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_audit_org_event ON gateway_audit_logs (org_id, event_type)")
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_audit_parent "
                "ON gateway_audit_logs (parent_id) WHERE parent_id IS NOT NULL"
            )
        )
    logger.info("Ensured performance indexes on gateway_audit_logs")


async def _ensure_knowledge_columns(engine) -> None:
    """Create partial unique indexes and optional trigram index for knowledge docs.

    SQLAlchemy create_all cannot express partial unique indexes, so they are
    created here idempotently.  The trigram index is wrapped in a try/except
    because pg_trgm may not be installed on all deployments.
    """
    async with engine.begin() as conn:
        # Try to create pg_trgm extension (no-op if already exists)
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        except Exception:
            logger.info("pg_trgm extension not available — trigram search disabled")

        # Partial unique index: uniqueness when scope_ref IS NULL (org-scoped docs)
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_doc_org_null "
                "ON gateway_knowledge_docs (org_id, scope, category, title) "
                "WHERE scope_ref IS NULL"
            )
        )
        # Partial unique index: uniqueness when scope_ref IS NOT NULL (project/connection-scoped docs)
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_doc_scoped "
                "ON gateway_knowledge_docs (org_id, scope, scope_ref, category, title) "
                "WHERE scope_ref IS NOT NULL"
            )
        )

    # Trigram index: best-effort, requires pg_trgm
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_knowledge_title_trgm "
                    "ON gateway_knowledge_docs USING gin (title gin_trgm_ops)"
                )
            )
    except Exception:
        logger.info("Could not create trigram index on knowledge docs — pg_trgm likely unavailable")

    logger.info("Ensured knowledge doc indexes")


async def _ensure_chat_columns(engine) -> None:
    """Add columns to gateway_chat_conversations that were added after initial table creation."""
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS agent_session_id VARCHAR"))
        await conn.execute(text("ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS model VARCHAR(50)"))
        await conn.execute(
            text("ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS total_tokens INTEGER NOT NULL DEFAULT 0")
        )
        await conn.execute(
            text("ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS total_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0")
        )
    logger.info("Ensured chat conversation columns")


async def _ensure_chat_trace_indexes(engine) -> None:
    """Create durable trace lookup indexes idempotently."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_gw_trace_threads_session_org "
                "ON gateway_chat_trace_threads (org_id, session_id, updated_at)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_gw_trace_threads_source_org "
                "ON gateway_chat_trace_threads (org_id, source, updated_at)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_gw_trace_events_thread_idx_org "
                "ON gateway_chat_trace_events (org_id, thread_id, idx)"
            )
        )
    logger.info("Ensured chat trace indexes")


async def _ensure_notion_installation_config_analysis_columns(engine) -> None:
    """Add default project routing columns to Notion installation config."""
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE notion_installation_config ADD COLUMN IF NOT EXISTS default_project_id TEXT")
        )
        await conn.execute(
            text(
                "ALTER TABLE notion_installation_config "
                "ADD COLUMN IF NOT EXISTS default_branch VARCHAR(100) NOT NULL DEFAULT 'main'"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE notion_installation_config "
                "ADD COLUMN IF NOT EXISTS analysis_branch_mode VARCHAR(30) NOT NULL DEFAULT 'per_request'"
            )
        )
    logger.info("Ensured Notion analysis routing columns")


async def _ensure_report_deliverable_columns(engine) -> None:
    """Add report/dashboard metadata columns to existing report rows."""
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE gateway_reports ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'report'")
        )
        await conn.execute(text("ALTER TABLE gateway_reports ADD COLUMN IF NOT EXISTS data_json JSONB"))
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_reports_org_kind ON gateway_reports (org_id, kind, created_at)")
        )
        await conn.execute(text("ALTER TABLE notion_deliverables ADD COLUMN IF NOT EXISTS context_snapshot_id TEXT"))
        await conn.execute(text("ALTER TABLE notion_deliverables ADD COLUMN IF NOT EXISTS latest_update_id TEXT"))
        await conn.execute(
            text("ALTER TABLE notion_deliverables ADD COLUMN IF NOT EXISTS latest_file_upload_id VARCHAR(100)")
        )
        await conn.execute(text("ALTER TABLE notion_deliverables ADD COLUMN IF NOT EXISTS latest_html_bytes INTEGER"))
        await conn.execute(
            text("ALTER TABLE notion_deliverables ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'")
        )
        await conn.execute(text("ALTER TABLE notion_deliverables ADD COLUMN IF NOT EXISTS error TEXT"))
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_notion_deliverables_embed "
                "ON notion_deliverables (installation_id, embed_block_id)"
            )
        )
    logger.info("Ensured report deliverable columns")


async def _ensure_analysis_trail_indexes(engine) -> None:
    """Create durable analysis trail lookup indexes idempotently."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_gw_analysis_trail_thread "
                "ON gateway_analysis_trails (org_id, thread_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_gw_analysis_trail_project "
                "ON gateway_analysis_trails (org_id, project_id, branch)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_gw_analysis_trail_source_status "
                "ON gateway_analysis_trails (org_id, source, status)"
            )
        )
    logger.info("Ensured analysis trail indexes")


async def _ensure_branch_columns(engine) -> None:
    """Add branch columns to gateway_workspace_projects."""
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE gateway_workspace_projects ADD COLUMN IF NOT EXISTS default_branch VARCHAR(100) NOT NULL DEFAULT 'main'")
        )
        await conn.execute(
            text("ALTER TABLE gateway_workspace_projects ADD COLUMN IF NOT EXISTS protected_branches JSONB")
        )
        await conn.execute(
            text("ALTER TABLE gateway_workspace_projects ADD COLUMN IF NOT EXISTS git_remote VARCHAR(500)")
        )
        await conn.execute(
            text("ALTER TABLE gateway_workspace_projects ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'managed'")
        )
    logger.info("Ensured branch columns on gateway_workspace_projects")


async def _ensure_notebook_session_columns(engine) -> None:
    """Add notebook session token columns if they don't exist."""
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE gateway_notebook_sessions ADD COLUMN IF NOT EXISTS access_token VARCHAR"))
        await conn.execute(
            text("ALTER TABLE gateway_notebook_sessions ADD COLUMN IF NOT EXISTS access_token_enc BYTEA")
        )
    logger.info("Ensured notebook session columns")


async def _ensure_notebook_session_pod_ip_internal(engine) -> None:
    """Add pod_ip_internal column to gateway_notebook_sessions if it does not exist.

    Idempotent ADD COLUMN IF NOT EXISTS. No index needed (lookup is by PK).
    The proxy uses this column to reach the pod inside the cluster, distinct
    from pod_ip which is the legacy NodePort address kept for R3 cleanup.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE gateway_notebook_sessions ADD COLUMN IF NOT EXISTS pod_ip_internal TEXT")
        )
    logger.info("Ensured pod_ip_internal column on gateway_notebook_sessions")


async def _ensure_drop_s3_prefix_column(engine) -> None:
    """Drop s3_prefix column from gateway_workspace_projects if it still exists.

    Single-phase idempotent: DROP COLUMN IF EXISTS handles both new deployments
    (column never existed) and existing deployments (column present from R4).
    """
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE gateway_workspace_projects DROP COLUMN IF EXISTS s3_prefix")
        )
    logger.info("Ensured s3_prefix column dropped from gateway_workspace_projects")


async def _ensure_notebook_session_org_id(engine) -> None:
    """Idempotent: ensure org_id column on gateway_notebook_sessions and backfill legacy NULLs.

    1. ADD COLUMN IF NOT EXISTS org_id TEXT (no-op if already present).
    2. Backfill org_id = user_id WHERE org_id IS NULL (safe default for personal/local mode).

    In local/personal mode the org_id collapses to user_id; this backfill is safe for all
    legacy rows.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE gateway_notebook_sessions ADD COLUMN IF NOT EXISTS org_id TEXT")
        )
        await conn.execute(
            text("UPDATE gateway_notebook_sessions SET org_id = user_id WHERE org_id IS NULL")
        )
    logger.info("Ensured org_id column on gateway_notebook_sessions")


async def init_db() -> None:
    """Create gateway tables if they don't exist. Called at startup."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    await _ensure_key_version_column(engine)
    await _ensure_expires_at_column(engine)
    await _ensure_byok_columns(engine)
    await _ensure_org_id_columns(engine)
    await _ensure_health_columns(engine)
    await _ensure_plan_tier_column(engine)
    await _ensure_audit_ip_columns(engine)
    await _ensure_audit_parent_id_column(engine)
    await _ensure_audit_user_id_nullable(engine)
    await _ensure_audit_indexes(engine)
    await _ensure_knowledge_columns(engine)
    await _ensure_chat_columns(engine)
    await _ensure_chat_trace_indexes(engine)
    await _ensure_notion_installation_config_analysis_columns(engine)
    await _ensure_report_deliverable_columns(engine)
    await _ensure_analysis_trail_indexes(engine)
    await _ensure_branch_columns(engine)
    await _ensure_notebook_session_columns(engine)
    await _ensure_notebook_session_org_id(engine)
    await _ensure_notebook_session_pod_ip_internal(engine)
    await _ensure_drop_s3_prefix_column(engine)
    # GitHub tables are created by metadata.create_all above; this is a placeholder
    # for future column additions via ALTER TABLE IF NOT EXISTS.
    logger.info("Gateway database tables initialized")


async def close_db() -> None:
    """Dispose engine on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
