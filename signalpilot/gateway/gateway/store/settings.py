"""Settings + key-rotation persistence: org-scoped gateway settings and credential rotation count."""

from __future__ import annotations

import os

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayCredential, GatewaySetting
from gateway.models import GatewaySettings
from gateway.store._constants import CURRENT_KEY_VERSION


async def load_settings(session: AsyncSession, *, org_id: str) -> GatewaySettings:
    result = await session.execute(select(GatewaySetting).where(GatewaySetting.org_id == org_id))
    row = result.scalar_one_or_none()
    data = row.settings_json if row else {}
    # Environment variables provide defaults — user-saved settings take priority
    if os.getenv("SP_SANDBOX_MANAGER_URL") and "sandbox_manager_url" not in data:
        data["sandbox_manager_url"] = os.getenv("SP_SANDBOX_MANAGER_URL")
    if os.getenv("SP_GATEWAY_URL") and "gateway_url" not in data:
        data["gateway_url"] = os.getenv("SP_GATEWAY_URL")
    return GatewaySettings(**data)


async def save_settings(session: AsyncSession, *, org_id: str, user_id: str | None, settings: GatewaySettings) -> None:
    result = await session.execute(select(GatewaySetting).where(GatewaySetting.org_id == org_id))
    row = result.scalar_one_or_none()
    if row:
        row.settings_json = settings.model_dump()
    else:
        session.add(
            GatewaySetting(
                org_id=org_id,
                user_id=user_id,
                settings_json=settings.model_dump(),
            )
        )
    await session.commit()


async def get_credentials_needing_rotation(session: AsyncSession) -> int:
    result = await session.execute(
        select(sa_func.count())
        .select_from(GatewayCredential)
        .where(GatewayCredential.key_version < CURRENT_KEY_VERSION)
    )
    return result.scalar_one()
