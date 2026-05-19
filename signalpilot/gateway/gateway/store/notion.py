"""Store operations for Notion integrations."""

from __future__ import annotations

import json
import logging
import time
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayNotionIntegration
from gateway.models.notion import (
    NotionIntegrationCreate,
    NotionIntegrationInfo,
    NotionIntegrationUpdate,
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
