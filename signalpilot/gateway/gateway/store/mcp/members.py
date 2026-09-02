"""Per-(connector, user) state: own switch, tool overrides, member secrets, OAuth tokens."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayMcpMemberState
from gateway.store.mcp._common import decrypt_dict, decrypt_json, encrypt_json, utcnow


async def get_member_state(
    session: AsyncSession, *, connector_id: str, user_id: str
) -> GatewayMcpMemberState | None:
    return (
        await session.execute(
            select(GatewayMcpMemberState).where(
                GatewayMcpMemberState.connector_id == connector_id,
                GatewayMcpMemberState.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def ensure_member_state(
    session: AsyncSession, *, org_id: str, connector_id: str, user_id: str
) -> GatewayMcpMemberState:
    row = await get_member_state(session, connector_id=connector_id, user_id=user_id)
    if row is None:
        row = GatewayMcpMemberState(
            org_id=org_id,
            connector_id=connector_id,
            user_id=user_id,
            enabled=True,
            disabled_tools_json=[],
            updated_at=utcnow(),
        )
        session.add(row)
        await session.flush()
    return row


async def list_member_states(session: AsyncSession, *, user_id: str, org_id: str) -> dict[str, GatewayMcpMemberState]:
    rows = (
        await session.execute(
            select(GatewayMcpMemberState).where(
                GatewayMcpMemberState.org_id == org_id,
                GatewayMcpMemberState.user_id == user_id,
            )
        )
    ).scalars()
    return {row.connector_id: row for row in rows}


async def set_member_switch(
    session: AsyncSession,
    *,
    org_id: str,
    connector_id: str,
    user_id: str,
    enabled: bool,
    disabled_tools: list[str] | None = None,
) -> GatewayMcpMemberState:
    row = await ensure_member_state(session, org_id=org_id, connector_id=connector_id, user_id=user_id)
    row.enabled = enabled
    if disabled_tools is not None:
        row.disabled_tools_json = sorted(set(disabled_tools))
    row.updated_at = utcnow()
    await session.commit()
    return row


def member_headers(row: GatewayMcpMemberState | None) -> dict[str, str]:
    return decrypt_dict(row, "headers_enc") if row else {}


def member_env(row: GatewayMcpMemberState | None) -> dict[str, str]:
    return decrypt_dict(row, "env_enc") if row else {}


def set_member_secrets(
    row: GatewayMcpMemberState,
    *,
    headers: dict[str, str] | None = None,
    env: dict[str, str] | None = None,
) -> None:
    if headers:
        merged = member_headers(row)
        merged.update(headers)
        row.headers_enc = encrypt_json(merged)
    if env:
        merged_env = member_env(row)
        merged_env.update(env)
        row.env_enc = encrypt_json(merged_env)
    row.updated_at = utcnow()


def drop_member_secret(row: GatewayMcpMemberState, name: str) -> bool:
    removed = False
    headers = member_headers(row)
    if name in headers:
        headers.pop(name)
        row.headers_enc = encrypt_json(headers) if headers else None
        removed = True
    env = member_env(row)
    if name in env:
        env.pop(name)
        row.env_enc = encrypt_json(env) if env else None
        removed = True
    row.updated_at = utcnow()
    return removed


def oauth_tokens(row: GatewayMcpMemberState | None) -> dict[str, Any] | None:
    if row is None:
        return None
    value = decrypt_json(row, "oauth_tokens_enc")
    return value if isinstance(value, dict) and value.get("access_token") else None


def set_oauth_tokens(
    row: GatewayMcpMemberState,
    tokens: dict[str, Any] | None,
    *,
    account_label: str | None = None,
) -> None:
    """Store (or clear) a member's tokens.

    ``account_label`` is the display identity of the signed-in account. A
    token refresh passes None and keeps the label from the original sign-in;
    clearing the tokens always clears the label.
    """
    row.oauth_tokens_enc = encrypt_json(tokens) if tokens else None
    row.signed_in_at = utcnow() if tokens else None
    if not tokens:
        row.account_label = None
    elif account_label is not None:
        row.account_label = account_label[:200] or None
    row.updated_at = utcnow()


async def sign_out(session: AsyncSession, *, connector_id: str, user_id: str | None) -> int:
    """Drop OAuth tokens for one member (user_id) or for everyone (None)."""
    stmt = (
        update(GatewayMcpMemberState)
        .where(GatewayMcpMemberState.connector_id == connector_id)
        .values(oauth_tokens_enc=None, signed_in_at=None, account_label=None, updated_at=utcnow())
    )
    if user_id is not None:
        stmt = stmt.where(GatewayMcpMemberState.user_id == user_id)
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount or 0)


def _has_credential():
    """Rows that hold something usable upstream: OAuth tokens or member-supplied keys."""
    return or_(
        GatewayMcpMemberState.oauth_tokens_enc.is_not(None),
        GatewayMcpMemberState.headers_enc.is_not(None),
        GatewayMcpMemberState.env_enc.is_not(None),
    )


async def count_signed_in(session: AsyncSession, *, connector_id: str) -> int:
    """Members signed in to (or holding a key for) one connector."""
    value = (
        await session.execute(
            select(func.count(GatewayMcpMemberState.id)).where(
                GatewayMcpMemberState.connector_id == connector_id,
                _has_credential(),
            )
        )
    ).scalar_one()
    return int(value or 0)


async def signed_in_counts(session: AsyncSession, *, org_id: str) -> dict[str, int]:
    """``{connector_id: members signed in or holding a key}`` for one org (missing -> 0)."""
    rows = (
        await session.execute(
            select(GatewayMcpMemberState.connector_id, func.count(GatewayMcpMemberState.id))
            .where(GatewayMcpMemberState.org_id == org_id, _has_credential())
            .group_by(GatewayMcpMemberState.connector_id)
        )
    ).all()
    return {str(connector_id): int(count or 0) for connector_id, count in rows}


async def delete_member_states(session: AsyncSession, *, connector_id: str) -> None:
    await session.execute(delete(GatewayMcpMemberState).where(GatewayMcpMemberState.connector_id == connector_id))
    await session.commit()
