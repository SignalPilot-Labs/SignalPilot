"""Store operations for Slack integrations."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import SlackInstallation, SlackInstallationConfig, SlackOAuthState
from gateway.models.slack import (
    SlackInstallationConfigInfo,
    SlackOAuthInstallationInfo,
)
from gateway.store.crypto import _decrypt_with_migration, _encrypt
from gateway.string_utils import optional_string_value


def _scope_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [scope.strip() for scope in value.split(",") if scope.strip()]
    if isinstance(value, list):
        return [str(scope).strip() for scope in value if str(scope).strip()]
    return []


def _as_aware_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _config_info(config: SlackInstallationConfig | None) -> SlackInstallationConfigInfo | None:
    if config is None:
        return None
    return SlackInstallationConfigInfo(
        enabled=bool(config.enabled),
        default_project_id=config.default_project_id,
        default_branch=config.default_branch or "main",
        analysis_branch_mode=config.analysis_branch_mode or "per_request",
        allowed_channel_ids=list(config.allowed_channel_ids or []),
    )


async def _get_config(
    session: AsyncSession,
    installation_id: str,
) -> SlackInstallationConfig | None:
    result = await session.execute(
        select(SlackInstallationConfig).where(SlackInstallationConfig.installation_id == installation_id)
    )
    return result.scalar_one_or_none()


def _installation_info(
    row: SlackInstallation,
    config: SlackInstallationConfig | None = None,
) -> SlackOAuthInstallationInfo:
    return SlackOAuthInstallationInfo(
        id=row.id,
        team_id=row.team_id,
        team_name=row.team_name,
        enterprise_id=row.enterprise_id,
        enterprise_name=row.enterprise_name,
        app_id=row.app_id or None,
        bot_user_id=row.bot_user_id,
        authed_user_id=row.authed_user_id,
        scopes=list(row.scopes or []),
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
    """Create a short-lived Slack OAuth state value."""
    state = secrets.token_urlsafe(32)
    row = SlackOAuthState(
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
) -> SlackOAuthState | None:
    """Return and delete a valid OAuth state, or None when missing/expired."""
    result = await session.execute(select(SlackOAuthState).where(SlackOAuthState.state == state))
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
) -> SlackOAuthInstallationInfo:
    """Create or update a Slack OAuth installation from Slack's token response."""
    team = token_response.get("team") if isinstance(token_response.get("team"), dict) else {}
    enterprise = token_response.get("enterprise") if isinstance(token_response.get("enterprise"), dict) else {}
    authed_user = token_response.get("authed_user") if isinstance(token_response.get("authed_user"), dict) else {}

    team_id = optional_string_value(team.get("id"))
    bot_user_id = optional_string_value(token_response.get("bot_user_id"))
    bot_access_token = optional_string_value(token_response.get("access_token"))
    if not team_id or not bot_user_id or not bot_access_token:
        raise ValueError("Slack token response is missing team.id, bot_user_id, or access_token")

    app_id = optional_string_value(token_response.get("app_id")) or ""
    result = await session.execute(
        select(SlackInstallation).where(
            SlackInstallation.org_id == org_id,
            SlackInstallation.team_id == team_id,
            SlackInstallation.app_id == app_id,
        )
    )
    row = result.scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None:
        row = SlackInstallation(
            id=str(uuid.uuid4()),
            org_id=org_id,
            user_id=user_id,
            team_id=team_id,
            team_name=optional_string_value(team.get("name")),
            enterprise_id=optional_string_value(enterprise.get("id")),
            enterprise_name=optional_string_value(enterprise.get("name")),
            app_id=app_id,
            bot_user_id=bot_user_id,
            authed_user_id=optional_string_value(authed_user.get("id")),
            bot_access_token_enc=_encrypt(bot_access_token),
            scopes=_scope_list(token_response.get("scope")),
            status="connected",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.user_id = user_id
        row.team_name = optional_string_value(team.get("name"))
        row.enterprise_id = optional_string_value(enterprise.get("id"))
        row.enterprise_name = optional_string_value(enterprise.get("name"))
        row.bot_user_id = bot_user_id
        row.authed_user_id = optional_string_value(authed_user.get("id"))
        row.bot_access_token_enc = _encrypt(bot_access_token)
        row.scopes = _scope_list(token_response.get("scope"))
        row.status = "connected"
        row.updated_at = now

    await session.commit()
    await session.refresh(row)
    return _installation_info(row, await _get_config(session, row.id))


async def list_oauth_installations(
    session: AsyncSession,
    org_id: str,
) -> list[SlackOAuthInstallationInfo]:
    result = await session.execute(
        select(SlackInstallation)
        .where(SlackInstallation.org_id == org_id)
        .order_by(SlackInstallation.updated_at.desc())
    )
    rows = list(result.scalars())
    configs = {row.id: await _get_config(session, row.id) for row in rows}
    return [_installation_info(row, configs.get(row.id)) for row in rows]


async def get_oauth_installation(
    session: AsyncSession,
    org_id: str,
    installation_id: str,
) -> SlackOAuthInstallationInfo | None:
    result = await session.execute(
        select(SlackInstallation).where(
            SlackInstallation.org_id == org_id,
            SlackInstallation.id == installation_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return _installation_info(row, await _get_config(session, row.id))


async def save_oauth_installation_config(
    session: AsyncSession,
    org_id: str,
    installation_id: str,
    enabled: bool = True,
    default_project_id: str | None = None,
    default_branch: str = "main",
    analysis_branch_mode: str = "per_request",
    allowed_channel_ids: list[str] | None = None,
) -> SlackOAuthInstallationInfo | None:
    result = await session.execute(
        select(SlackInstallation).where(
            SlackInstallation.org_id == org_id,
            SlackInstallation.id == installation_id,
        )
    )
    install = result.scalar_one_or_none()
    if install is None:
        return None

    config = await _get_config(session, installation_id)
    if config is None:
        config = SlackInstallationConfig(installation_id=installation_id)
        session.add(config)
    config.enabled = enabled
    config.default_project_id = default_project_id
    config.default_branch = default_branch or "main"
    config.analysis_branch_mode = analysis_branch_mode or "per_request"
    config.allowed_channel_ids = allowed_channel_ids or []
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
        select(SlackInstallation).where(
            SlackInstallation.org_id == org_id,
            SlackInstallation.id == installation_id,
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


async def list_active_installation_records_for_team(
    session: AsyncSession,
    team_id: str,
) -> list[tuple[SlackInstallation, SlackInstallationConfig, str]]:
    """Return active Slack install rows, setup config, and decrypted bot token."""
    result = await session.execute(
        select(SlackInstallation).where(
            SlackInstallation.team_id == team_id,
            SlackInstallation.status.in_(["connected", "needs_setup", "active"]),
        )
    )
    rows = list(result.scalars())
    records: list[tuple[SlackInstallation, SlackInstallationConfig, str]] = []
    for row in rows:
        config = await _get_config(session, row.id)
        if config is None or not config.enabled or not config.default_project_id:
            continue
        token, _ = _decrypt_with_migration(row.bot_access_token_enc)
        records.append((row, config, token))
    return records
