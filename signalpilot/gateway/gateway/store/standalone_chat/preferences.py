"""Per-user chat preference lookups."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayChatUserPreference

DEFAULT_PER_QUERY_BUDGET_USD = 0.25
DEFAULT_CHAT_BUDGET_USD = 1.0


async def get_user_chat_preference(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
) -> GatewayChatUserPreference | None:
    return (
        await db.execute(
            select(GatewayChatUserPreference).where(
                GatewayChatUserPreference.org_id == org_id,
                GatewayChatUserPreference.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def default_chat_budgets(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
) -> tuple[float, float]:
    """Return (per_query_budget_usd, chat_budget_usd) a new chat starts with.

    The user's saved defaults win; otherwise the product defaults apply.
    Bootstrap and forking both read budgets through here.
    """
    preference = await get_user_chat_preference(db, org_id=org_id, user_id=user_id)
    if preference is None:
        return DEFAULT_PER_QUERY_BUDGET_USD, DEFAULT_CHAT_BUDGET_USD
    return preference.default_per_query_budget_usd, preference.default_chat_budget_usd
