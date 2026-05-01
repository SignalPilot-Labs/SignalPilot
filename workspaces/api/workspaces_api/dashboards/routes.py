"""Dashboard chart routes.

auth: TODO(round-5) — routes are currently open (no JWT/Clerk auth).

Routes:
  POST  /v1/charts                      Create chart + chart_query
  GET   /v1/charts/{id}                 Fetch chart by ID
  GET   /v1/charts?workspace=<id>&...   List charts with cursor pagination
  POST  /v1/charts/{id}/run             Return cached result or 202 queued

Cache MISS behavior (R3):
  Returns 202 ChartRunQueued with error_code="execution_not_wired". No executor
  runs; no gateway HTTP call. The route shape is final; execution wires in R4.

Cursor encoding (deterministic, stable):
  base64.urlsafe_b64encode(json.dumps([created_at_iso, str(id)], separators=(',',':')).encode()).decode().rstrip('=')
  Decode reverses.

Error matrix:
  chart not found              → 404  chart_not_found
  connector not found          → 422  connector_not_found (validation time — R3 skips)
  sql > 50000 chars            → 422  sql_too_long
  chart_type not in enum       → 422  invalid_chart_type
  cache row JSON corrupt       → 500  chart_cache_corrupt
  cache MISS                   → 202  execution_not_wired
  force=true and no executor   → 202  execution_not_wired
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from workspaces_api.errors import ChartCacheCorrupt, ChartNotFound
from .cache import compute_cache_key, fetch_cached
from .models import Chart, ChartCache, ChartQuery
from .schemas import (
    ChartCreateRequest,
    ChartListResponse,
    ChartResponse,
    ChartRunQueued,
    ChartRunRequest,
    ChartRunResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/charts", tags=["charts"])


def _get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


# ─── Cursor helpers ───────────────────────────────────────────────────────────


def _encode_cursor(created_at_iso: str, chart_id: str) -> str:
    raw = json.dumps([created_at_iso, chart_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    padded = cursor + "=" * (-len(cursor) % 4)
    raw = base64.urlsafe_b64decode(padded).decode()
    created_at_iso, chart_id = json.loads(raw)
    return created_at_iso, chart_id


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _load_chart(session: AsyncSession, chart_id: uuid.UUID) -> Chart:
    """Load a chart with its query eagerly. Raises ChartNotFound if absent."""
    result = await session.execute(
        select(Chart)
        .options(selectinload(Chart.query))
        .where(Chart.id == chart_id)
    )
    chart = result.scalar_one_or_none()
    if chart is None:
        raise ChartNotFound(f"chart_id={chart_id}")
    return chart


def _build_chart_response(chart: Chart) -> ChartResponse:
    return ChartResponse.from_orm_chart(chart)


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.post("", status_code=201, response_model=ChartResponse)
async def create_chart(
    body: ChartCreateRequest,
    request: Request,
) -> ChartResponse:
    """Create a chart and its associated chart_query.

    Validation errors (sql_too_long, invalid_chart_type) are raised by Pydantic
    and mapped to 422 by FastAPI. connector_not_found validation is deferred to R4.
    """
    session_factory = _get_session_factory(request)
    async with session_factory() as session:
        chart = Chart(
            id=uuid.uuid4(),
            workspace_id=body.workspace_id,
            title=body.title,
            chart_type=body.chart_type,
            echarts_option=body.echarts_option_json,
        )
        session.add(chart)
        await session.flush()

        chart_query = ChartQuery(
            id=uuid.uuid4(),
            chart_id=chart.id,
            connector_name=body.query.connector_name,
            sql=body.query.sql,
            params=body.query.params,
            refresh_interval_seconds=body.query.refresh_interval_seconds,
        )
        session.add(chart_query)
        await session.flush()

        await session.commit()
        await session.refresh(chart)
        await session.refresh(chart_query)
        # Re-attach the query relationship
        chart.query = chart_query

    logger.info("chart_created chart_id=%s workspace=%s", chart.id, body.workspace_id)
    return _build_chart_response(chart)


@router.get("/{chart_id}", response_model=ChartResponse)
async def get_chart(
    chart_id: uuid.UUID,
    request: Request,
) -> ChartResponse:
    """Fetch a chart by ID. Returns 404 if not found."""
    session_factory = _get_session_factory(request)
    async with session_factory() as session:
        chart = await _load_chart(session, chart_id)
    return _build_chart_response(chart)


@router.get("", response_model=ChartListResponse)
async def list_charts(
    request: Request,
    workspace: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
) -> ChartListResponse:
    """List charts for a workspace, paginated by created_at DESC.

    Cursor encodes (created_at_iso, chart_id) for stable keyset pagination.
    """
    session_factory = _get_session_factory(request)
    async with session_factory() as session:
        q = (
            select(Chart)
            .options(selectinload(Chart.query))
            .where(Chart.workspace_id == workspace)
            .order_by(Chart.created_at.desc(), Chart.id.desc())
            .limit(limit + 1)
        )

        if cursor is not None:
            try:
                cursor_created_at, cursor_id = _decode_cursor(cursor)
            except Exception:
                raise HTTPException(status_code=422, detail="invalid_cursor")
            from sqlalchemy import or_, and_
            from datetime import datetime

            cursor_dt = datetime.fromisoformat(cursor_created_at)
            q = q.where(
                or_(
                    Chart.created_at < cursor_dt,
                    and_(Chart.created_at == cursor_dt, Chart.id < uuid.UUID(cursor_id)),
                )
            )

        result = await session.execute(q)
        charts = list(result.scalars().all())

    has_next = len(charts) > limit
    page = charts[:limit]

    next_cursor: str | None = None
    if has_next and page:
        last = page[-1]
        created_at_iso = last.created_at.replace(tzinfo=timezone.utc).isoformat() if last.created_at.tzinfo is None else last.created_at.isoformat()
        next_cursor = _encode_cursor(created_at_iso, str(last.id))

    return ChartListResponse(
        items=[_build_chart_response(c) for c in page],
        next_cursor=next_cursor,
    )


@router.post("/{chart_id}/run")
async def run_chart(
    chart_id: uuid.UUID,
    body: ChartRunRequest,
    request: Request,
) -> Any:
    """Return cached query result or 202 queued on cache MISS.

    R3 behavior:
      - cache HIT → 200 ChartRunResponse
      - cache MISS → 202 ChartRunQueued (execution_not_wired)
      - force=True → 202 ChartRunQueued (no executor available in R3)

    Real execution wires in R4 alongside spawn and DbtProxyExecutor.
    """
    from fastapi.responses import JSONResponse

    session_factory = _get_session_factory(request)
    async with session_factory() as session:
        chart = await _load_chart(session, chart_id)

        if chart.query is None:
            # No query attached yet — always MISS
            cache_key = ""
            return JSONResponse(
                status_code=202,
                content=ChartRunQueued(
                    status="queued",
                    reason="execution_not_wired",
                    error_code="execution_not_wired",
                    chart_id=chart_id,
                    cache_key=cache_key,
                    computed_at=None,
                ).model_dump(mode="json"),
            )

        q = chart.query
        effective_params = body.params if body.params is not None else q.params
        cache_key = compute_cache_key(q.connector_name, q.sql, effective_params)

        # force=True skips cache (but R3 has no executor, so always MISS)
        if not body.force:
            cached: ChartCache | None = await fetch_cached(session, cache_key)
            if cached is not None:
                try:
                    result_data = cached.result_json
                    columns = result_data["columns"]
                    rows = result_data["rows"]
                except (KeyError, TypeError) as exc:
                    raise ChartCacheCorrupt(f"cache_key={cache_key}: {exc}")

                return ChartRunResponse(
                    chart_id=chart_id,
                    cache_key=cache_key,
                    cached=True,
                    computed_at=cached.computed_at,
                    columns=columns,
                    rows=rows,
                )

    # Cache MISS (or force=True) — R3 returns 202
    return JSONResponse(
        status_code=202,
        content=ChartRunQueued(
            status="queued",
            reason="execution_not_wired",
            error_code="execution_not_wired",
            chart_id=chart_id,
            cache_key=cache_key,
            computed_at=None,
        ).model_dump(mode="json"),
    )


__all__ = ["router"]
