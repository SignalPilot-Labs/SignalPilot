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
    SQLite fallback: the gateway DB is always Postgres).
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
    SQLite fallback: the gateway DB is always Postgres).

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


async def _ensure_github_authorized_repos_column(engine) -> None:
    """Add authorized_repository_ids to gateway_github_installations if absent.

    The column stores the repository identifiers that the authorizing user can access.
    Token refresh remains restricted to this set.
    A NULL value requires the installation to reconnect before token issuance.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE gateway_github_installations ADD COLUMN IF NOT EXISTS authorized_repository_ids JSON")
        )
    logger.info("Ensured authorized_repository_ids column on gateway_github_installations")


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

    # FTS expression index: matches the hybrid-search FTS arm's expression so
    # ranking doesn't re-tokenize every doc per query. Best-effort.
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_knowledge_fts "
                    "ON gateway_knowledge_docs USING gin "
                    "(to_tsvector('english', title || ' ' || body))"
                )
            )
    except Exception:
        logger.info("Could not create FTS index on knowledge docs")

    # The embedding-based search experiment was replaced by in-process BM25;
    # drop its table on deployments that created it (best-effort).
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS gateway_knowledge_embeddings"))
    except Exception:
        pass

    logger.info("Ensured knowledge doc indexes")


async def _ensure_chat_columns(engine) -> None:
    """Add columns to gateway_chat_conversations that were added after initial table creation."""
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS agent_session_id VARCHAR")
        )
        await conn.execute(text("ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS model VARCHAR(50)"))
        await conn.execute(
            text(
                "ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS total_tokens INTEGER NOT NULL DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS total_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0"
            )
        )
    logger.info("Ensured chat conversation columns")


async def _ensure_standalone_chat_schema(engine) -> None:
    """Add standalone-chat columns and privacy/queue indexes idempotently."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE gateway_chat_conversations "
                "ADD COLUMN IF NOT EXISTS surface VARCHAR(20) NOT NULL DEFAULT 'notebook'"
            )
        )
        await conn.execute(text("ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS branch VARCHAR(100)"))
        await conn.execute(
            text(
                "ALTER TABLE gateway_chat_conversations "
                "ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'"
            )
        )
        await conn.execute(
            text("ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ")
        )
        await conn.execute(
            text("ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS internal_summary TEXT")
        )
        await conn.execute(
            text("ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS commit_sha VARCHAR(40)")
        )
        await conn.execute(
            text(
                "ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS per_query_budget_usd DOUBLE PRECISION NOT NULL DEFAULT 0.25"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS chat_budget_usd DOUBLE PRECISION NOT NULL DEFAULT 1.0"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS estimated_spend_usd DOUBLE PRECISION NOT NULL DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS actual_spend_usd DOUBLE PRECISION NOT NULL DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS reserved_spend_usd DOUBLE PRECISION NOT NULL DEFAULT 0"
            )
        )
        await conn.execute(
            text("ALTER TABLE gateway_chat_conversations ADD COLUMN IF NOT EXISTS forked_from_conversation_id VARCHAR")
        )
        await conn.execute(
            text(
                "ALTER TABLE gateway_chat_user_preferences ADD COLUMN IF NOT EXISTS default_per_query_budget_usd DOUBLE PRECISION NOT NULL DEFAULT 0.25"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE gateway_chat_user_preferences ADD COLUMN IF NOT EXISTS default_chat_budget_usd DOUBLE PRECISION NOT NULL DEFAULT 1.0"
            )
        )
        await conn.execute(text("UPDATE gateway_chat_conversations SET surface = 'notebook' WHERE surface IS NULL"))
        await conn.execute(
            text("ALTER TABLE gateway_chat_messages ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(200)")
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_gw_conv_standalone_history "
                "ON gateway_chat_conversations "
                "(org_id, user_id, surface, status, updated_at)"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_gw_chat_message_idempotency "
                "ON gateway_chat_messages (idempotency_key) "
                "WHERE idempotency_key IS NOT NULL"
            )
        )
        await conn.execute(text("DROP INDEX IF EXISTS uq_gw_chat_run_nonterminal_conversation"))
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_gw_chat_run_nonterminal_conversation "
                "ON gateway_chat_runs (conversation_id) "
                "WHERE status IN ('queued','running','waiting_for_user','waiting_for_query_approval')"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_gw_chat_artifact_publication "
                "ON gateway_chat_artifacts (run_id, kind, filename)"
            )
        )
    logger.info("Ensured standalone chat columns and indexes")


async def _ensure_hybrid_chat_runtime_schema(engine) -> None:
    """Add object-backed result, artifact, and runtime-routing columns."""
    statements = (
        "ALTER TABLE gateway_chat_artifacts ADD COLUMN IF NOT EXISTS storage_kind VARCHAR(20) NOT NULL DEFAULT 'inline'",
        "ALTER TABLE gateway_chat_artifacts ADD COLUMN IF NOT EXISTS object_key TEXT",
        "ALTER TABLE gateway_chat_artifacts ADD COLUMN IF NOT EXISTS source_object_key TEXT",
        "ALTER TABLE gateway_chat_artifacts ADD COLUMN IF NOT EXISTS byte_size BIGINT",
        "ALTER TABLE gateway_chat_artifacts ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)",
        "ALTER TABLE gateway_structured_query_results ALTER COLUMN execution_id DROP NOT NULL",
        "ALTER TABLE gateway_structured_query_results ADD COLUMN IF NOT EXISTS conversation_id VARCHAR",
        "ALTER TABLE gateway_structured_query_results ADD COLUMN IF NOT EXISTS run_id VARCHAR",
        "ALTER TABLE gateway_structured_query_results ADD COLUMN IF NOT EXISTS preview_rows_json JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE gateway_structured_query_results ADD COLUMN IF NOT EXISTS storage_kind VARCHAR(20) NOT NULL DEFAULT 'inline'",
        "ALTER TABLE gateway_structured_query_results ADD COLUMN IF NOT EXISTS object_key TEXT",
        "ALTER TABLE gateway_structured_query_results ADD COLUMN IF NOT EXISTS byte_size BIGINT",
        "ALTER TABLE gateway_structured_query_results ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)",
        "ALTER TABLE gateway_structured_query_results ADD COLUMN IF NOT EXISTS source_result_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE gateway_structured_query_results ADD COLUMN IF NOT EXISTS code_hash VARCHAR(64)",
        "ALTER TABLE gateway_structured_query_results ADD COLUMN IF NOT EXISTS result_origin VARCHAR(20) NOT NULL DEFAULT 'mcp'",
        "ALTER TABLE gateway_governed_query_executions ADD COLUMN IF NOT EXISTS plan_id VARCHAR",
        "ALTER TABLE gateway_governed_query_executions ADD COLUMN IF NOT EXISTS actual_scan_bytes BIGINT",
        "ALTER TABLE gateway_governed_query_executions ADD COLUMN IF NOT EXISTS actual_output_bytes BIGINT",
        "ALTER TABLE gateway_governed_query_executions ADD COLUMN IF NOT EXISTS execution_ms DOUBLE PRECISION",
        "ALTER TABLE gateway_query_proposals ADD COLUMN IF NOT EXISTS plan_id VARCHAR",
        "ALTER TABLE gateway_chat_runs ADD COLUMN IF NOT EXISTS runtime_archive_id VARCHAR",
        # Existing databases can have this column as JSON while deployments
        # that received the additive migration have JSONB. Compare through an
        # explicit cast so startup remains idempotent for both histories.
        "UPDATE gateway_structured_query_results SET preview_rows_json = rows_json WHERE preview_rows_json::jsonb = '[]'::jsonb",
    )
    async with engine.begin() as conn:
        for statement in statements:
            await conn.execute(text(statement))
    logger.info("Ensured hybrid chat runtime schema")


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
            text(
                "ALTER TABLE notion_deliverables ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'"
            )
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
                "CREATE INDEX IF NOT EXISTS ix_gw_analysis_trail_thread ON gateway_analysis_trails (org_id, thread_id)"
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
            text(
                "ALTER TABLE gateway_workspace_projects ADD COLUMN IF NOT EXISTS default_branch VARCHAR(100) NOT NULL DEFAULT 'main'"
            )
        )
        await conn.execute(
            text("ALTER TABLE gateway_workspace_projects ADD COLUMN IF NOT EXISTS protected_branches JSONB")
        )
        await conn.execute(
            text("ALTER TABLE gateway_workspace_projects ADD COLUMN IF NOT EXISTS git_remote VARCHAR(500)")
        )
        await conn.execute(
            text(
                "ALTER TABLE gateway_workspace_projects ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'managed'"
            )
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
    The proxy uses this column to reach the pod inside the cluster.
    The pod_ip column contains the external NodePort address.
    """
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE gateway_notebook_sessions ADD COLUMN IF NOT EXISTS pod_ip_internal TEXT"))
    logger.info("Ensured pod_ip_internal column on gateway_notebook_sessions")


async def _ensure_drop_s3_prefix_column(engine) -> None:
    """Drop s3_prefix column from gateway_workspace_projects if it still exists.

    Single-phase idempotent: DROP COLUMN IF EXISTS handles both new deployments
    (column never existed) and existing deployments (column present from R4).
    """
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE gateway_workspace_projects DROP COLUMN IF EXISTS s3_prefix"))
    logger.info("Ensured s3_prefix column dropped from gateway_workspace_projects")


async def _ensure_notebook_token_plaintext_dropped(engine) -> None:
    """Drop the plaintext notebook access_token column.

    Store tokens only in encrypted form.
    Stop a session that contains a plaintext token before dropping the column.
    The next connection provisions a new ephemeral notebook session.
    """
    async with engine.begin() as conn:
        exists = (
            await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'gateway_notebook_sessions' "
                    "AND column_name = 'access_token'"
                )
            )
        ).first()
        if not exists:
            return
        stopped = await conn.execute(
            text("UPDATE gateway_notebook_sessions SET status = 'stopped' WHERE access_token IS NOT NULL")
        )
        if stopped.rowcount:
            logger.warning(
                "Stopped %d notebook session(s) that held a plaintext token",
                stopped.rowcount,
            )
        await conn.execute(text("ALTER TABLE gateway_notebook_sessions DROP COLUMN IF EXISTS access_token"))
    logger.info("Dropped plaintext access_token from gateway_notebook_sessions")


async def _ensure_api_key_eval_binding_columns(engine) -> None:
    """Idempotent: eval binding columns on gateway_api_keys.

    A key minted for an eval run carries its run/task/connection/doc overlay
    here so the pin cannot be dropped by the party holding the key.
    """
    async with engine.begin() as conn:
        for ddl in (
            "ALTER TABLE gateway_api_keys ADD COLUMN IF NOT EXISTS eval_run_id VARCHAR(64)",
            "ALTER TABLE gateway_api_keys ADD COLUMN IF NOT EXISTS eval_task_id VARCHAR(200)",
            "ALTER TABLE gateway_api_keys ADD COLUMN IF NOT EXISTS eval_connection VARCHAR(64)",
            "ALTER TABLE gateway_api_keys ADD COLUMN IF NOT EXISTS eval_doc_ids JSON",
        ):
            await conn.execute(text(ddl))
    logger.info("Ensured eval binding columns on gateway_api_keys")


async def _ensure_eval_regression_change_columns(engine) -> None:
    """Idempotent: the full change-set columns on gateway_eval_regressions."""
    async with engine.begin() as conn:
        for ddl in (
            "ALTER TABLE gateway_eval_regressions ADD COLUMN IF NOT EXISTS added_doc_ids JSON",
            "ALTER TABLE gateway_eval_regressions ADD COLUMN IF NOT EXISTS removed_doc_ids JSON",
            "ALTER TABLE gateway_eval_regressions ADD COLUMN IF NOT EXISTS other_changes JSON",
        ):
            await conn.execute(text(ddl))
    logger.info("Ensured change-set columns on gateway_eval_regressions")


async def _ensure_eval_run_lease_columns(engine) -> None:
    """Idempotent: lease columns on gateway_eval_runs.

    A run holds a heartbeat lease during execution.
    Startup recovery and the reaper use the lease to identify an active run.
    """
    async with engine.begin() as conn:
        for ddl in (
            "ALTER TABLE gateway_eval_runs ADD COLUMN IF NOT EXISTS lease_expires_at DOUBLE PRECISION",
            "ALTER TABLE gateway_eval_runs ADD COLUMN IF NOT EXISTS api_key_id VARCHAR",
            "ALTER TABLE gateway_eval_runs ADD COLUMN IF NOT EXISTS config_hash VARCHAR(40)",
        ):
            await conn.execute(text(ddl))
    logger.info("Ensured lease columns on gateway_eval_runs")


async def _ensure_notebook_session_org_id(engine) -> None:
    """Add org_id to gateway_notebook_sessions and fill NULL values.

    Add the column only when it does not exist.
    Set org_id to user_id when org_id is NULL.

    Local and personal modes use the user identifier as the organization identifier.
    """
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE gateway_notebook_sessions ADD COLUMN IF NOT EXISTS org_id TEXT"))
        await conn.execute(text("UPDATE gateway_notebook_sessions SET org_id = user_id WHERE org_id IS NULL"))
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
    await _ensure_standalone_chat_schema(engine)
    await _ensure_hybrid_chat_runtime_schema(engine)
    await _ensure_chat_trace_indexes(engine)
    await _ensure_notion_installation_config_analysis_columns(engine)
    await _ensure_report_deliverable_columns(engine)
    await _ensure_analysis_trail_indexes(engine)
    await _ensure_branch_columns(engine)
    await _ensure_notebook_session_columns(engine)
    await _ensure_notebook_session_org_id(engine)
    await _ensure_notebook_session_pod_ip_internal(engine)
    await _ensure_drop_s3_prefix_column(engine)
    await _ensure_github_authorized_repos_column(engine)
    await _ensure_notebook_token_plaintext_dropped(engine)
    await _ensure_api_key_eval_binding_columns(engine)
    await _ensure_eval_run_lease_columns(engine)
    await _ensure_eval_regression_change_columns(engine)
    # Backfill a bounded batch on every startup. New artifacts are always
    # hashed at publication; this converges older inline rows without making
    # startup duration depend on library size.
    from gateway.store.chat_reports import backfill_inline_artifact_hashes

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        backfilled = await backfill_inline_artifact_hashes(session, limit=200)
    if backfilled:
        logger.info("Backfilled canonical hashes for %d Data Chat artifacts", backfilled)
    logger.info("Gateway database tables initialized")


async def close_db() -> None:
    """Dispose engine on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
