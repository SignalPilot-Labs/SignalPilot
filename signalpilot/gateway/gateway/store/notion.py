"""Store operations for Notion integrations."""

from __future__ import annotations

import logging
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayNotionIntegration,
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


async def list_integrations(
    session: AsyncSession,
    org_id: str,
) -> list[NotionIntegrationInfo]:
    """List all Notion integrations for an org."""
    result = await session.execute(
        select(GatewayNotionIntegration).where(GatewayNotionIntegration.org_id == org_id)
    )
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
