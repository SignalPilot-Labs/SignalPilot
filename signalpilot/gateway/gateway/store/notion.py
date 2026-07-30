"""Store operations for Notion integrations."""

from __future__ import annotations

import logging
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import DBAPIError, IntegrityError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayNotionIntegration,
    NotionDeliverable,
    NotionDeliverableContextSnapshot,
    NotionDeliverableUpdate,
    NotionInstallation,
    NotionInstallationConfig,
    NotionOAuthState,
    NotionWebhookDelivery,
)
from gateway.models.notion import (
    NotionInstallationConfigInfo,
    NotionIntegrationCreate,
    NotionIntegrationInfo,
    NotionIntegrationUpdate,
    NotionOAuthInstallationInfo,
)
from gateway.store.crypto import _decrypt_with_migration, _encrypt

logger = logging.getLogger(__name__)


def _looks_like_closed_connection(exc: BaseException) -> bool:
    if isinstance(exc, DBAPIError) and getattr(exc, "connection_invalidated", False):
        return True
    message = str(exc).lower()
    return (
        "connection is closed" in message
        or "connection was closed" in message
        or "connection has been closed" in message
    )


async def _run_with_closed_connection_retry(session: AsyncSession, operation, description: str):
    try:
        return await operation()
    except (InterfaceError, OperationalError, DBAPIError) as exc:
        if not _looks_like_closed_connection(exc):
            raise
        logger.warning("Stale DB connection during %s; retrying once", description, exc_info=True)
        try:
            await session.rollback()
        except Exception:
            logger.debug("Rollback after stale DB connection failed", exc_info=True)
        return await operation()


def _normalize_notion_id(value: str | None) -> str:
    return (value or "").replace("-", "")


async def list_integrations(
    session: AsyncSession,
    org_id: str,
) -> list[NotionIntegrationInfo]:
    """List all Notion integrations for an org."""
    result = await session.execute(select(GatewayNotionIntegration).where(GatewayNotionIntegration.org_id == org_id))
    return [NotionIntegrationInfo(**row.to_info_dict()) for row in result.scalars()]


async def get_integration(
    session: AsyncSession,
    org_id: str,
    name: str,
) -> NotionIntegrationInfo | None:
    """Get a single Notion integration by name."""
    result = await session.execute(
        select(GatewayNotionIntegration).where(
            GatewayNotionIntegration.org_id == org_id,
            GatewayNotionIntegration.name == name,
        )
    )
    row = result.scalar_one_or_none()
    return NotionIntegrationInfo(**row.to_info_dict()) if row else None


async def create_integration(
    session: AsyncSession,
    org_id: str,
    integration: NotionIntegrationCreate,
) -> NotionIntegrationInfo:
    """Create a new Notion integration with encrypted API key."""
    existing = await get_integration(session, org_id, integration.name)
    if existing:
        raise ValueError(f"Notion integration '{integration.name}' already exists")

    row = GatewayNotionIntegration(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=integration.name,
        api_key_enc=_encrypt(integration.api_key),
        search_page_ids=integration.search_page_ids,
        report_parent_page_id=integration.report_parent_page_id,
        created_at=time.time(),
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise ValueError(f"Notion integration '{integration.name}' already exists") from e
    await session.refresh(row)
    return NotionIntegrationInfo(**row.to_info_dict())


async def update_integration(
    session: AsyncSession,
    org_id: str,
    name: str,
    update: NotionIntegrationUpdate,
) -> NotionIntegrationInfo | None:
    """Update an existing Notion integration."""
    result = await session.execute(
        select(GatewayNotionIntegration).where(
            GatewayNotionIntegration.org_id == org_id,
            GatewayNotionIntegration.name == name,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return None

    update_fields = update.model_dump(exclude_none=True)
    if "api_key" in update_fields:
        row.api_key_enc = _encrypt(update_fields.pop("api_key"))
    for key, value in update_fields.items():
        if hasattr(row, key):
            setattr(row, key, value)

    await session.commit()
    await session.refresh(row)
    return NotionIntegrationInfo(**row.to_info_dict())


async def delete_integration(
    session: AsyncSession,
    org_id: str,
    name: str,
) -> bool:
    """Delete a Notion integration by name."""
    result = await session.execute(
        select(GatewayNotionIntegration).where(
            GatewayNotionIntegration.org_id == org_id,
            GatewayNotionIntegration.name == name,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def get_api_key(
    session: AsyncSession,
    org_id: str,
    name: str,
) -> str | None:
    """Decrypt and return the API key for a Notion integration."""
    result = await session.execute(
        select(GatewayNotionIntegration).where(
            GatewayNotionIntegration.org_id == org_id,
            GatewayNotionIntegration.name == name,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    plaintext, _ = _decrypt_with_migration(row.api_key_enc)
    return plaintext


# ─── OAuth Installations ────────────────────────────────────────────────────


def _owner_user_id(owner: dict | None) -> str | None:
    if not isinstance(owner, dict):
        return None
    user = owner.get("user")
    if isinstance(user, dict):
        value = user.get("id")
        return str(value) if value else None
    return None


def _as_aware_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _config_info(config: NotionInstallationConfig | None) -> NotionInstallationConfigInfo | None:
    if config is None:
        return None
    return NotionInstallationConfigInfo(
        parent_page_id=config.parent_page_id,
        trigger_page_id=config.trigger_page_id,
        requests_data_source_id=config.requests_data_source_id,
        requests_database_page_id=config.requests_database_page_id,
        enabled=bool(config.enabled),
        default_project_id=config.default_project_id,
        default_branch=config.default_branch or "main",
        analysis_branch_mode=config.analysis_branch_mode or "per_request",
    )


async def _get_config(
    session: AsyncSession,
    installation_id: str,
) -> NotionInstallationConfig | None:
    result = await session.execute(
        select(NotionInstallationConfig).where(NotionInstallationConfig.installation_id == installation_id)
    )
    return result.scalar_one_or_none()


def _installation_info(
    row: NotionInstallation,
    config: NotionInstallationConfig | None = None,
) -> NotionOAuthInstallationInfo:
    return NotionOAuthInstallationInfo(
        id=row.id,
        workspace_id=row.workspace_id,
        workspace_name=row.workspace_name,
        bot_id=row.bot_id,
        owner_user_id=row.owner_user_id,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        org_id=row.org_id,
        config=_config_info(config),
    )


async def create_oauth_state(
    session: AsyncSession,
    org_id: str,
    user_id: str | None,
    redirect_after: str | None,
    ttl_seconds: int = 600,
) -> str:
    """Create a short-lived OAuth state value."""
    state = secrets.token_urlsafe(32)
    row = NotionOAuthState(
        state=state,
        org_id=org_id,
        user_id=user_id,
        redirect_after=redirect_after,
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
    )
    session.add(row)
    await session.commit()
    return state


async def consume_oauth_state(
    session: AsyncSession,
    state: str,
) -> NotionOAuthState | None:
    """Return and delete a valid OAuth state, or None when missing/expired."""
    result = await session.execute(select(NotionOAuthState).where(NotionOAuthState.state == state))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    await session.delete(row)
    await session.commit()
    if _as_aware_utc(row.expires_at) < datetime.now(UTC):
        return None
    return row


async def record_deliverable(
    session: AsyncSession,
    *,
    org_id: str,
    installation_id: str,
    page_id: str,
    request_id: str,
    report_id: str,
    kind: str,
    request_page_id: str | None = None,
    discussion_id: str | None = None,
    embed_block_id: str | None = None,
    file_upload_id: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
) -> NotionDeliverable:
    row = NotionDeliverable(
        org_id=org_id,
        installation_id=installation_id,
        page_id=page_id,
        request_page_id=request_page_id,
        discussion_id=discussion_id,
        request_id=request_id,
        report_id=report_id,
        kind=kind,
        embed_block_id=embed_block_id,
        file_upload_id=file_upload_id,
        session_id=session_id,
        metadata_json=metadata,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def find_deliverable_by_embed_block(
    session: AsyncSession,
    *,
    org_id: str,
    installation_id: str,
    embed_block_id: str | None,
) -> NotionDeliverable | None:
    """Find a deliverable by Notion embed block ID, accepting dashed/undashed IDs."""
    normalized = _normalize_notion_id(embed_block_id)
    if not normalized:
        return None
    result = await session.execute(
        select(NotionDeliverable)
        .where(
            NotionDeliverable.org_id == org_id,
            NotionDeliverable.installation_id == installation_id,
            NotionDeliverable.embed_block_id.isnot(None),
        )
        .order_by(NotionDeliverable.updated_at.desc(), NotionDeliverable.created_at.desc())
    )
    for row in result.scalars():
        if _normalize_notion_id(row.embed_block_id) == normalized:
            return row
    return None


async def find_deliverable_by_discussion(
    session: AsyncSession,
    *,
    org_id: str,
    installation_id: str,
    discussion_id: str | None,
) -> NotionDeliverable | None:
    """Find the latest deliverable created from a Notion comment discussion."""
    normalized = _normalize_notion_id(discussion_id)
    if not normalized:
        return None
    result = await session.execute(
        select(NotionDeliverable)
        .where(
            NotionDeliverable.org_id == org_id,
            NotionDeliverable.installation_id == installation_id,
            NotionDeliverable.discussion_id.isnot(None),
        )
        .order_by(NotionDeliverable.updated_at.desc(), NotionDeliverable.created_at.desc())
    )
    for row in result.scalars():
        if _normalize_notion_id(row.discussion_id) == normalized:
            return row
    return None


async def update_deliverable_discussion(
    session: AsyncSession,
    *,
    deliverable_id: str,
    discussion_id: str,
) -> NotionDeliverable | None:
    row = await session.get(NotionDeliverable, deliverable_id)
    if row is None:
        return None
    metadata = dict(row.metadata_json or {})
    if row.discussion_id and row.discussion_id != discussion_id and "initial_discussion_id" not in metadata:
        metadata["initial_discussion_id"] = row.discussion_id
    row.discussion_id = discussion_id
    row.metadata_json = metadata
    row.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return row


async def record_deliverable_context_snapshot(
    session: AsyncSession,
    *,
    deliverable_id: str,
    org_id: str,
    request_id: str,
    base_notebook_code: str,
    session_id: str | None = None,
    base_chat_events: list[dict] | None = None,
    base_final_packet: dict | None = None,
    base_notebook_sha256: str | None = None,
    base_notebook_path: str | None = None,
    project_id: str | None = None,
    branch: str | None = None,
    source_prompt: str | None = None,
    metadata: dict | None = None,
) -> NotionDeliverableContextSnapshot:
    row = NotionDeliverableContextSnapshot(
        id=str(uuid.uuid4()),
        deliverable_id=deliverable_id,
        org_id=org_id,
        request_id=request_id,
        session_id=session_id,
        base_notebook_code=base_notebook_code,
        base_chat_events=base_chat_events or [],
        base_final_packet=base_final_packet or {},
        base_notebook_sha256=base_notebook_sha256,
        base_notebook_path=base_notebook_path,
        project_id=project_id,
        branch=branch,
        source_prompt=source_prompt,
        metadata_json=metadata,
    )
    session.add(row)
    deliverable = await session.get(NotionDeliverable, deliverable_id)
    if deliverable is not None:
        deliverable.context_snapshot_id = row.id
        deliverable.status = "active"
        deliverable.error = None
    await session.commit()
    await session.refresh(row)
    return row


async def latest_deliverable_context_snapshot(
    session: AsyncSession,
    *,
    deliverable_id: str,
) -> NotionDeliverableContextSnapshot | None:
    result = await session.execute(
        select(NotionDeliverableContextSnapshot)
        .where(NotionDeliverableContextSnapshot.deliverable_id == deliverable_id)
        .order_by(NotionDeliverableContextSnapshot.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_deliverable_update(
    session: AsyncSession,
    *,
    deliverable_id: str,
    org_id: str,
    mode: str,
    prompt: str,
    data_instruction: str,
    render_instruction: str,
    old_file_upload_id: str | None,
    ephemeral_run_id: str | None = None,
    metadata: dict | None = None,
) -> NotionDeliverableUpdate:
    row = NotionDeliverableUpdate(
        id=str(uuid.uuid4()),
        deliverable_id=deliverable_id,
        org_id=org_id,
        mode=mode,
        status="running",
        prompt=prompt,
        data_instruction=data_instruction,
        render_instruction=render_instruction,
        ephemeral_run_id=ephemeral_run_id,
        old_file_upload_id=old_file_upload_id,
        metadata_json=metadata,
    )
    session.add(row)
    deliverable = await session.get(NotionDeliverable, deliverable_id)
    if deliverable is not None:
        deliverable.latest_update_id = row.id
        deliverable.status = "updating"
        deliverable.error = None
    await session.commit()
    await session.refresh(row)
    return row


async def mark_deliverable_update_succeeded(
    session: AsyncSession,
    *,
    update_id: str,
    deliverable_id: str,
    new_file_upload_id: str | None,
    html_bytes: int,
) -> NotionDeliverableUpdate | None:
    now = datetime.now(UTC)

    async def _write() -> bool:
        result = await session.execute(
            sa_update(NotionDeliverableUpdate)
            .where(NotionDeliverableUpdate.id == update_id)
            .values(
                status="succeeded",
                error=None,
                new_file_upload_id=new_file_upload_id,
                html_bytes=html_bytes,
                updated_at=now,
            )
            .execution_options(synchronize_session="fetch")
        )
        if not result.rowcount:
            await session.commit()
            return False
        values: dict[str, object | None] = {
            "latest_file_upload_id": new_file_upload_id,
            "latest_html_bytes": html_bytes,
            "status": "active",
            "error": None,
            "updated_at": now,
        }
        if new_file_upload_id:
            values["file_upload_id"] = new_file_upload_id
        await session.execute(
            sa_update(NotionDeliverable)
            .where(
                NotionDeliverable.id == deliverable_id,
                NotionDeliverable.latest_update_id == update_id,
            )
            .values(**values)
            .execution_options(synchronize_session="fetch")
        )
        await session.commit()
        return True

    updated = await _run_with_closed_connection_retry(
        session,
        _write,
        "mark Notion deliverable update succeeded",
    )
    return await session.get(NotionDeliverableUpdate, update_id) if updated else None


async def mark_deliverable_update_failed(
    session: AsyncSession,
    *,
    update_id: str | None,
    deliverable_id: str,
    error: str,
) -> NotionDeliverableUpdate | None:
    now = datetime.now(UTC)

    async def _write() -> bool:
        if update_id is not None:
            result = await session.execute(
                sa_update(NotionDeliverableUpdate)
                .where(NotionDeliverableUpdate.id == update_id)
                .values(status="failed", error=error, updated_at=now)
                .execution_options(synchronize_session="fetch")
            )
            if not result.rowcount:
                await session.commit()
                return False
            await session.execute(
                sa_update(NotionDeliverable)
                .where(
                    NotionDeliverable.id == deliverable_id,
                    NotionDeliverable.latest_update_id == update_id,
                )
                .values(
                    status="failed",
                    error=error,
                    updated_at=now,
                )
                .execution_options(synchronize_session="fetch")
            )
        else:
            await session.execute(
                sa_update(NotionDeliverable)
                .where(NotionDeliverable.id == deliverable_id)
                .values(status="failed", error=error, updated_at=now)
                .execution_options(synchronize_session="fetch")
            )
        await session.commit()
        return True

    updated = await _run_with_closed_connection_retry(
        session,
        _write,
        "mark Notion deliverable update failed",
    )
    return await session.get(NotionDeliverableUpdate, update_id) if update_id and updated else None


async def upsert_oauth_installation(
    session: AsyncSession,
    org_id: str,
    user_id: str | None,
    token_response: dict,
) -> NotionOAuthInstallationInfo:
    """Create or update a Notion OAuth installation from Notion's token response."""
    workspace_id = str(token_response.get("workspace_id") or "")
    bot_id = str(token_response.get("bot_id") or "")
    access_token = str(token_response.get("access_token") or "")
    if not workspace_id or not bot_id or not access_token:
        raise ValueError("Notion token response is missing workspace_id, bot_id, or access_token")

    refresh_token_raw = token_response.get("refresh_token")
    refresh_token = str(refresh_token_raw) if refresh_token_raw else None
    owner = token_response.get("owner") if isinstance(token_response.get("owner"), dict) else None

    result = await session.execute(
        select(NotionInstallation).where(
            NotionInstallation.org_id == org_id,
            NotionInstallation.workspace_id == workspace_id,
            NotionInstallation.bot_id == bot_id,
        )
    )
    row = result.scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None:
        row = NotionInstallation(
            id=str(uuid.uuid4()),
            org_id=org_id,
            user_id=user_id,
            workspace_id=workspace_id,
            workspace_name=token_response.get("workspace_name"),
            bot_id=bot_id,
            owner_user_id=_owner_user_id(owner),
            access_token_enc=_encrypt(access_token),
            refresh_token_enc=_encrypt(refresh_token) if refresh_token else None,
            owner=owner,
            status="connected",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.user_id = user_id
        row.workspace_name = token_response.get("workspace_name")
        row.owner_user_id = _owner_user_id(owner)
        row.access_token_enc = _encrypt(access_token)
        if refresh_token:
            row.refresh_token_enc = _encrypt(refresh_token)
        row.owner = owner
        row.status = "connected"
        row.updated_at = now

    await session.commit()
    await session.refresh(row)
    return _installation_info(row, await _get_config(session, row.id))


async def list_oauth_installations(
    session: AsyncSession,
    org_id: str,
) -> list[NotionOAuthInstallationInfo]:
    result = await session.execute(
        select(NotionInstallation)
        .where(NotionInstallation.org_id == org_id)
        .order_by(NotionInstallation.updated_at.desc())
    )
    rows = list(result.scalars())
    configs = {row.id: await _get_config(session, row.id) for row in rows}
    return [_installation_info(row, configs.get(row.id)) for row in rows]


async def get_oauth_installation(
    session: AsyncSession,
    org_id: str,
    installation_id: str,
) -> NotionOAuthInstallationInfo | None:
    result = await session.execute(
        select(NotionInstallation).where(
            NotionInstallation.org_id == org_id,
            NotionInstallation.id == installation_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return _installation_info(row, await _get_config(session, row.id))


async def get_oauth_installation_token(
    session: AsyncSession,
    org_id: str,
    installation_id: str,
) -> str | None:
    result = await session.execute(
        select(NotionInstallation).where(
            NotionInstallation.org_id == org_id,
            NotionInstallation.id == installation_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    token, _ = _decrypt_with_migration(row.access_token_enc)
    return token


async def get_oauth_installation_tokens(
    session: AsyncSession,
    org_id: str,
    installation_id: str,
) -> tuple[str, str | None] | None:
    result = await session.execute(
        select(NotionInstallation).where(
            NotionInstallation.org_id == org_id,
            NotionInstallation.id == installation_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    access_token, _ = _decrypt_with_migration(row.access_token_enc)
    refresh_token = None
    if row.refresh_token_enc:
        refresh_token, _ = _decrypt_with_migration(row.refresh_token_enc)
    return access_token, refresh_token


async def update_oauth_installation_tokens(
    session: AsyncSession,
    org_id: str,
    installation_id: str,
    access_token: str,
    refresh_token: str | None,
) -> None:
    result = await session.execute(
        select(NotionInstallation).where(
            NotionInstallation.org_id == org_id,
            NotionInstallation.id == installation_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ValueError("Notion installation not found")
    row.access_token_enc = _encrypt(access_token)
    if refresh_token:
        row.refresh_token_enc = _encrypt(refresh_token)
    row.updated_at = datetime.now(UTC)
    await session.commit()


async def save_oauth_installation_config(
    session: AsyncSession,
    org_id: str,
    installation_id: str,
    parent_page_id: str | None,
    trigger_page_id: str,
    requests_data_source_id: str,
    requests_database_page_id: str,
    enabled: bool = True,
    default_project_id: str | None = None,
    default_branch: str = "main",
    analysis_branch_mode: str = "per_request",
) -> NotionOAuthInstallationInfo | None:
    result = await session.execute(
        select(NotionInstallation).where(
            NotionInstallation.org_id == org_id,
            NotionInstallation.id == installation_id,
        )
    )
    install = result.scalar_one_or_none()
    if install is None:
        return None

    config = await _get_config(session, installation_id)
    if config is None:
        config = NotionInstallationConfig(installation_id=installation_id)
        session.add(config)
    config.parent_page_id = parent_page_id
    config.trigger_page_id = trigger_page_id
    config.requests_data_source_id = requests_data_source_id
    config.requests_database_page_id = requests_database_page_id
    config.enabled = enabled
    config.default_project_id = default_project_id
    config.default_branch = default_branch or "main"
    config.analysis_branch_mode = analysis_branch_mode or "per_request"
    install.status = "active" if enabled else "needs_setup"
    install.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(install)
    return _installation_info(install, config)


async def disable_oauth_installation(
    session: AsyncSession,
    org_id: str,
    installation_id: str,
) -> bool:
    result = await session.execute(
        select(NotionInstallation).where(
            NotionInstallation.org_id == org_id,
            NotionInstallation.id == installation_id,
        )
    )
    install = result.scalar_one_or_none()
    if install is None:
        return False
    config = await _get_config(session, installation_id)
    if config is not None:
        config.enabled = False
    install.status = "disconnected"
    install.updated_at = datetime.now(UTC)
    await session.commit()
    return True


async def list_active_installation_records_for_workspace(
    session: AsyncSession,
    workspace_id: str,
) -> list[tuple[NotionInstallation, NotionInstallationConfig | None, str]]:
    """Return active installation rows, setup config, and decrypted access token."""
    result = await session.execute(
        select(NotionInstallation).where(
            NotionInstallation.workspace_id == workspace_id,
            NotionInstallation.status.in_(["connected", "needs_setup", "active"]),
        )
    )
    rows = list(result.scalars())
    records: list[tuple[NotionInstallation, NotionInstallationConfig | None, str]] = []
    for row in rows:
        token, _ = _decrypt_with_migration(row.access_token_enc)
        records.append((row, await _get_config(session, row.id), token))
    return records


async def get_installation_record(
    session: AsyncSession,
    installation_id: str,
) -> tuple[NotionInstallation, NotionInstallationConfig | None, str] | None:
    result = await session.execute(select(NotionInstallation).where(NotionInstallation.id == installation_id))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    token, _ = _decrypt_with_migration(row.access_token_enc)
    return row, await _get_config(session, row.id), token


async def get_webhook_delivery(
    session: AsyncSession,
    event_id: str,
) -> NotionWebhookDelivery | None:
    result = await session.execute(select(NotionWebhookDelivery).where(NotionWebhookDelivery.event_id == event_id))
    return result.scalar_one_or_none()


async def record_webhook_delivery(
    session: AsyncSession,
    event_id: str,
    status: str,
    attempt_number: int | None = None,
    installation_id: str | None = None,
    org_id: str | None = None,
    error: str | None = None,
    processed: bool = False,
) -> NotionWebhookDelivery:
    """Create or update a webhook delivery audit row."""
    result = await session.execute(select(NotionWebhookDelivery).where(NotionWebhookDelivery.event_id == event_id))
    row = result.scalar_one_or_none()
    if row is None:
        row = NotionWebhookDelivery(
            event_id=event_id,
            installation_id=installation_id,
            org_id=org_id,
            status=status,
            attempt_number=attempt_number,
            error=error,
            processed_at=datetime.now(UTC) if processed else None,
        )
        session.add(row)
    else:
        row.installation_id = installation_id or row.installation_id
        row.org_id = org_id or row.org_id
        row.status = status
        row.attempt_number = attempt_number if attempt_number is not None else row.attempt_number
        row.error = error
        if processed:
            row.processed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return row
