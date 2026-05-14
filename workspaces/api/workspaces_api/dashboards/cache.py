"""Cache key computation and cache read/write helpers for charts.

Cache key = sha256(f"{connector_name}|{sql.strip()}|{json.dumps(params, sort_keys=True, separators=(',',':'))}").hexdigest()
TTL = chart_query.refresh_interval_seconds.

result_json shape:
  {"columns": [{"name": str, "type_hint": str}], "rows": [[...]]}
  Arrow IPC migration: TODO — deferred to a later round.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ChartCache, ChartQuery


def compute_cache_key(connector_name: str, sql: str, params: dict[str, Any]) -> str:
    """Compute a deterministic cache key for a query + params combination.

    Stable across parameter dict ordering (keys are sorted).
    """
    params_json = json.dumps(params, sort_keys=True, separators=(",", ":"))
    raw = f"{connector_name}|{sql.strip()}|{params_json}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def fetch_cached(
    session: AsyncSession,
    cache_key: str,
) -> ChartCache | None:
    """Return a non-expired cache row, or None if absent or expired."""
    now = datetime.now(tz=timezone.utc)
    result = await session.execute(
        select(ChartCache).where(
            ChartCache.cache_key == cache_key,
            ChartCache.expires_at > now,
        )
    )
    return result.scalar_one_or_none()


async def persist_cache(
    session: AsyncSession,
    cache_key: str,
    query: ChartQuery,
    result_json: dict[str, Any],
) -> ChartCache:
    """Upsert a cache row for the given query result.

    Uses a simple delete-then-insert (SQLite compatible). Production Postgres
    could use ON CONFLICT DO UPDATE; this is safe because the PK is cache_key.
    """
    now = datetime.now(tz=timezone.utc)
    expires_at = now + timedelta(seconds=query.refresh_interval_seconds)

    # Delete any existing row with this key (handles expired rows too)
    existing = await session.get(ChartCache, cache_key)
    if existing is not None:
        await session.delete(existing)
        await session.flush()

    row = ChartCache(
        cache_key=cache_key,
        query_id=query.id,
        result_json=result_json,
        computed_at=now,
        expires_at=expires_at,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


__all__ = ["compute_cache_key", "fetch_cached", "persist_cache"]
