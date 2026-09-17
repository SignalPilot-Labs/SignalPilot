"""Per-user usage aggregation for the admin "usage by member" and "my usage" pages.

Sources (existing tables only, no migrations):

- gateway_chat_runs: chat run counts, cost_usd, and token counts read from
  usage_json (JSON path extraction compiles per dialect: JSON_EXTRACT on
  sqlite, ->> on Postgres).
- gateway_audit_logs: warehouse queries. A statement that reached a warehouse
  is logged as event_type "sql" (legacy rows use "query", "execute",
  "mcp_sql"). A query_database call the gateway refused never reaches a
  connector, so it only leaves an "mcp_tool" row with agent_id
  "query_database" and blocked=true; those rows count as blocked queries.

Every source is read with one grouped SQL per breakdown (by user, by day, and
for /me by conversation and by connection). Nothing iterates the raw rows.
The window is aligned to UTC midnight so ``days`` produces exactly ``days``
daily points ending today.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayAuditLog, GatewayChatConversation, GatewayChatRun
from gateway.models.usage import (
    ConnectionUsage,
    ConversationUsage,
    MemberUsage,
    MyUsageResponse,
    OrgUsageResponse,
    UsageDailyPoint,
    UsageTotals,
    UsageWindow,
)

MAX_DAYS = 90
TOP_CONVERSATIONS = 10
QUERY_EVENT_TYPES = ("sql", "query", "execute", "mcp_sql")
_DAY_SECONDS = 86400.0


def clamp_days(days: int) -> int:
    return max(1, min(MAX_DAYS, int(days)))


def make_window(days: int, now: float | None = None) -> tuple[UsageWindow, datetime]:
    """Window covering ``days`` UTC calendar days ending now (inclusive)."""
    now_ts = time.time() if now is None else now
    now_dt = datetime.fromtimestamp(now_ts, tz=UTC)
    start = (now_dt - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return UsageWindow(from_ts=start.timestamp(), to_ts=now_ts, days=days), start


# ── SQL fragments ────────────────────────────────────────────────────────────


def _is_query_event():
    return or_(
        GatewayAuditLog.event_type.in_(QUERY_EVENT_TYPES),
        and_(
            GatewayAuditLog.event_type == "mcp_tool",
            GatewayAuditLog.agent_id == "query_database",
            GatewayAuditLog.blocked.is_(True),
        ),
    )


def _run_day_expr(dialect: str):
    col = GatewayChatRun.created_at
    if dialect == "postgresql":
        return func.to_char(func.timezone("UTC", col), "YYYY-MM-DD")
    # sqlite stores the UTC wall clock as text; date() yields YYYY-MM-DD.
    return func.date(col)


def _audit_day_expr(dialect: str):
    secs = GatewayAuditLog.timestamp / _DAY_SECONDS
    if dialect == "sqlite":
        # CAST truncates toward zero on sqlite; epochs are positive.
        return cast(secs, Integer)
    # Postgres CAST(double AS integer) rounds, so floor explicitly.
    return cast(func.floor(secs), Integer)


def _tokens(key: str):
    return func.coalesce(func.sum(GatewayChatRun.usage_json[key].as_integer()), 0)


def _blocked_count():
    return func.coalesce(func.sum(case((GatewayAuditLog.blocked.is_(True), 1), else_=0)), 0)


def _epoch(value: datetime | None) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _max_ts(*values: float | None) -> float | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


# ── grouped reads ────────────────────────────────────────────────────────────


def _run_filter(org_id: str, start: datetime, user_id: str | None):
    clauses = [GatewayChatRun.org_id == org_id, GatewayChatRun.created_at >= start]
    if user_id is not None:
        clauses.append(GatewayChatRun.user_id == user_id)
    return and_(*clauses)


def _audit_filter(org_id: str, from_ts: float, user_id: str | None):
    clauses = [GatewayAuditLog.org_id == org_id, GatewayAuditLog.timestamp >= from_ts, _is_query_event()]
    if user_id is not None:
        clauses.append(GatewayAuditLog.user_id == user_id)
    return and_(*clauses)


async def _runs_by_user(session: AsyncSession, org_id: str, start: datetime, user_id: str | None) -> list[Any]:
    stmt = (
        select(
            GatewayChatRun.user_id,
            func.count(GatewayChatRun.id),
            func.count(func.distinct(GatewayChatRun.conversation_id)),
            func.coalesce(func.sum(GatewayChatRun.cost_usd), 0.0),
            _tokens("input_tokens"),
            _tokens("output_tokens"),
            _tokens("cache_read_input_tokens"),
            _tokens("cache_creation_input_tokens"),
            func.max(GatewayChatRun.created_at),
        )
        .where(_run_filter(org_id, start, user_id))
        .group_by(GatewayChatRun.user_id)
    )
    return list((await session.execute(stmt)).all())


async def _runs_by_day(
    session: AsyncSession, org_id: str, start: datetime, user_id: str | None, dialect: str
) -> dict[str, tuple[int, float]]:
    day = _run_day_expr(dialect)
    stmt = (
        select(day, func.count(GatewayChatRun.id), func.coalesce(func.sum(GatewayChatRun.cost_usd), 0.0))
        .where(_run_filter(org_id, start, user_id))
        .group_by(day)
    )
    return {str(d): (int(n), float(c)) for d, n, c in (await session.execute(stmt)).all()}


async def _audit_by_user(session: AsyncSession, org_id: str, from_ts: float, user_id: str | None) -> list[Any]:
    stmt = (
        select(
            GatewayAuditLog.user_id,
            func.count(GatewayAuditLog.id),
            _blocked_count(),
            func.coalesce(func.sum(GatewayAuditLog.rows_returned), 0),
            func.max(GatewayAuditLog.timestamp),
        )
        .where(_audit_filter(org_id, from_ts, user_id))
        .group_by(GatewayAuditLog.user_id)
    )
    return list((await session.execute(stmt)).all())


async def _audit_by_day(
    session: AsyncSession, org_id: str, from_ts: float, user_id: str | None, dialect: str
) -> dict[str, int]:
    day = _audit_day_expr(dialect)
    stmt = select(day, func.count(GatewayAuditLog.id)).where(_audit_filter(org_id, from_ts, user_id)).group_by(day)
    out: dict[str, int] = {}
    for idx, n in (await session.execute(stmt)).all():
        out[datetime.fromtimestamp(int(idx) * _DAY_SECONDS, tz=UTC).date().isoformat()] = int(n)
    return out


async def _distinct_conversations(session: AsyncSession, org_id: str, start: datetime) -> int:
    stmt = select(func.count(func.distinct(GatewayChatRun.conversation_id))).where(_run_filter(org_id, start, None))
    return int((await session.execute(stmt)).scalar_one() or 0)


# ── assembly ─────────────────────────────────────────────────────────────────


def _merge_members(run_rows: list[Any], audit_rows: list[Any]) -> tuple[dict[str | None, MemberUsage], UsageTotals]:
    """Fold the two grouped result sets into per-user rows plus org totals.

    Audit rows with no user_id (rows written before the user contextvar was
    populated) contribute to the totals but produce no member entry.
    """
    members: dict[str | None, MemberUsage] = {}

    def member(uid: str | None) -> MemberUsage:
        if uid not in members:
            members[uid] = MemberUsage(user_id=uid or "")
        return members[uid]

    for uid, runs, convs, cost, inp, out, cr, cc, last in run_rows:
        m = member(uid)
        m.chat_runs += int(runs)
        m.conversations += int(convs)
        m.cost_usd += float(cost)
        m.input_tokens += int(inp)
        m.output_tokens += int(out)
        m.cache_read_tokens += int(cr)
        m.cache_creation_tokens += int(cc)
        m.last_active_at = _max_ts(m.last_active_at, _epoch(last))

    for uid, queries, blocked, rows, last in audit_rows:
        m = member(uid)
        m.queries += int(queries)
        m.blocked_queries += int(blocked)
        m.rows_returned += int(rows)
        m.last_active_at = _max_ts(m.last_active_at, float(last) if last is not None else None)

    totals = UsageTotals()
    for m in members.values():
        totals.chat_runs += m.chat_runs
        totals.conversations += m.conversations
        totals.cost_usd += m.cost_usd
        totals.input_tokens += m.input_tokens
        totals.output_tokens += m.output_tokens
        totals.cache_read_tokens += m.cache_read_tokens
        totals.cache_creation_tokens += m.cache_creation_tokens
        totals.queries += m.queries
        totals.blocked_queries += m.blocked_queries
        totals.rows_returned += m.rows_returned
        totals.last_active_at = _max_ts(totals.last_active_at, m.last_active_at)
    return members, totals


def _fill_daily(
    start: datetime, days: int, run_days: dict[str, tuple[int, float]], audit_days: dict[str, int]
) -> list[UsageDailyPoint]:
    points: list[UsageDailyPoint] = []
    for i in range(days):
        key = (start + timedelta(days=i)).date().isoformat()
        runs, cost = run_days.get(key, (0, 0.0))
        points.append(UsageDailyPoint(date=key, chat_runs=runs, cost_usd=cost, queries=audit_days.get(key, 0)))
    return points


async def org_usage(session: AsyncSession, org_id: str, days: int, *, now: float | None = None) -> OrgUsageResponse:
    days = clamp_days(days)
    window, start = make_window(days, now)
    dialect = session.get_bind().dialect.name

    run_rows = await _runs_by_user(session, org_id, start, None)
    audit_rows = await _audit_by_user(session, org_id, window.from_ts, None)
    run_days = await _runs_by_day(session, org_id, start, None, dialect)
    audit_days = await _audit_by_day(session, org_id, window.from_ts, None, dialect)

    members, totals = _merge_members(run_rows, audit_rows)
    # A conversation is owned by one user, but count distinct org-wide to be exact.
    totals.conversations = await _distinct_conversations(session, org_id, start)
    ranked = sorted((m for uid, m in members.items() if uid), key=lambda m: (-m.cost_usd, m.user_id))
    return OrgUsageResponse(
        window=window, totals=totals, members=ranked, daily=_fill_daily(start, days, run_days, audit_days)
    )


async def _top_conversations(
    session: AsyncSession, org_id: str, user_id: str, start: datetime
) -> list[ConversationUsage]:
    cost = func.coalesce(func.sum(GatewayChatRun.cost_usd), 0.0)
    stmt = (
        select(GatewayChatRun.conversation_id, func.count(GatewayChatRun.id), cost, func.max(GatewayChatRun.created_at))
        .where(_run_filter(org_id, start, user_id))
        .group_by(GatewayChatRun.conversation_id)
        .order_by(cost.desc(), GatewayChatRun.conversation_id)
        .limit(TOP_CONVERSATIONS)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return []
    ids = [r[0] for r in rows]
    titles = dict(
        (
            await session.execute(
                select(GatewayChatConversation.id, GatewayChatConversation.title).where(
                    GatewayChatConversation.id.in_(ids)
                )
            )
        ).all()
    )
    return [
        ConversationUsage(
            conversation_id=cid, title=titles.get(cid), chat_runs=int(n), cost_usd=float(c), last_activity_at=_epoch(last)
        )
        for cid, n, c, last in rows
    ]


async def _connections(session: AsyncSession, org_id: str, user_id: str, from_ts: float) -> list[ConnectionUsage]:
    queries = func.count(GatewayAuditLog.id)
    stmt = (
        select(
            GatewayAuditLog.connection_name,
            queries,
            func.coalesce(func.sum(GatewayAuditLog.rows_returned), 0),
            _blocked_count(),
        )
        .where(_audit_filter(org_id, from_ts, user_id), GatewayAuditLog.connection_name.is_not(None))
        .group_by(GatewayAuditLog.connection_name)
        .order_by(queries.desc(), GatewayAuditLog.connection_name)
    )
    return [
        ConnectionUsage(connection_name=name, queries=int(q), rows_returned=int(r), blocked_queries=int(b))
        for name, q, r, b in (await session.execute(stmt)).all()
    ]


async def user_usage(
    session: AsyncSession, org_id: str, user_id: str, days: int, *, now: float | None = None
) -> MyUsageResponse:
    days = clamp_days(days)
    window, start = make_window(days, now)
    dialect = session.get_bind().dialect.name

    run_rows = await _runs_by_user(session, org_id, start, user_id)
    audit_rows = await _audit_by_user(session, org_id, window.from_ts, user_id)
    run_days = await _runs_by_day(session, org_id, start, user_id, dialect)
    audit_days = await _audit_by_day(session, org_id, window.from_ts, user_id, dialect)

    _members, totals = _merge_members(run_rows, audit_rows)
    return MyUsageResponse(
        window=window,
        user_id=user_id,
        totals=totals,
        daily=_fill_daily(start, days, run_days, audit_days),
        conversations=await _top_conversations(session, org_id, user_id, start),
        connections=await _connections(session, org_id, user_id, window.from_ts),
    )
