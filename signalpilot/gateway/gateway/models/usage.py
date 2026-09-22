"""Response models for the per-user usage endpoints (/api/usage/org, /api/usage/me).

The web "usage by member" and "my usage" pages are built against these exact
field names; do not rename fields without updating the frontend contract.
"""

from __future__ import annotations

from pydantic import BaseModel


class UsageWindow(BaseModel):
    from_ts: float
    to_ts: float
    days: int


class UsageTotals(BaseModel):
    chat_runs: int = 0
    conversations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    queries: int = 0
    blocked_queries: int = 0
    rows_returned: int = 0
    eval_runs: int | None = None
    last_active_at: float | None = None


class UsageDailyPoint(BaseModel):
    date: str  # YYYY-MM-DD, UTC
    chat_runs: int = 0
    cost_usd: float = 0.0
    queries: int = 0


class MemberUsage(UsageTotals):
    user_id: str


class OrgUsageResponse(BaseModel):
    window: UsageWindow
    totals: UsageTotals
    members: list[MemberUsage]  # sorted by cost_usd desc
    daily: list[UsageDailyPoint]  # one point per day in the window, zeros filled


class ConversationUsage(BaseModel):
    conversation_id: str
    title: str | None = None
    chat_runs: int = 0
    cost_usd: float = 0.0
    last_activity_at: float | None = None


class ConnectionUsage(BaseModel):
    connection_name: str
    queries: int = 0
    rows_returned: int = 0
    blocked_queries: int = 0


class MyUsageResponse(BaseModel):
    window: UsageWindow
    user_id: str
    totals: UsageTotals
    daily: list[UsageDailyPoint]
    conversations: list[ConversationUsage]  # top 10 by cost
    connections: list[ConnectionUsage]
