"""DbtProxyExecutor — executes a chart SQL query via the dbt-proxy.

Per-request flow:
  1. Mint a short-lived run-token for this chart-execute call.
  2. Open an async psycopg connection to the proxy.
  3. Execute the SQL with statement_timeout and total deadline.
  4. Capture rows with row/cell caps.
  5. Persist results to chart_cache.
  6. Revoke the token (always, in finally).
  7. Return ChartExecutionResult to the caller.

Connection is NOT pooled — one connection per request, closed when done.
Pooling is deferred to a later round.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import psycopg
from psycopg.conninfo import make_conninfo

from workspaces_api.dashboards.cache import compute_cache_key, persist_cache
from workspaces_api.dashboards.errors import ChartExecutionFailed, ChartExecutionTimeout
from workspaces_api.dashboards.result_capture import accumulate_rows

if TYPE_CHECKING:
    from workspaces_api.config import Settings

logger = logging.getLogger(__name__)


@runtime_checkable
class _TokenClientProtocol(Protocol):
    """Structural protocol satisfied by ProxyTokenClient and test fakes."""

    async def mint(
        self, run_id: uuid.UUID, connector_name: str, ttl_seconds: int
    ) -> Any: ...

    async def revoke(self, run_id: uuid.UUID) -> None: ...


@dataclass
class ChartExecutionResult:
    """Result returned from DbtProxyExecutor.execute()."""

    cache_key: str
    computed_at: datetime
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    truncated: bool


class DbtProxyExecutor:
    """Executes chart SQL via the dbt-proxy and persists the result to chart_cache.

    connect_factory is injected for testability; defaults to
    psycopg.AsyncConnection.connect.
    """

    def __init__(
        self,
        settings: "Settings",
        token_client: _TokenClientProtocol,
        connect_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._settings = settings
        self._token_client = token_client
        self._connect_factory: Callable[..., Any] = (
            connect_factory
            if connect_factory is not None
            else psycopg.AsyncConnection.connect
        )

    async def execute(
        self,
        chart: Any,
        query: Any,
        effective_params: dict[str, Any],
        session: Any,
    ) -> ChartExecutionResult:
        """Execute query SQL and return a ChartExecutionResult.

        Raises:
            ProxyTokenMintFailed: if token minting fails (propagates unchanged).
            ChartExecutionFailed: on psycopg errors during execution.
            ChartExecutionTimeout: if total_deadline_seconds exceeded.
        """
        settings = self._settings
        cid = uuid.uuid4().hex[:16]
        exec_run_id = uuid.uuid4()

        lease = await self._token_client.mint(
            run_id=exec_run_id,
            connector_name=query.connector_name,
            ttl_seconds=settings.sp_chart_execute_token_ttl_seconds,
        )

        try:
            async with asyncio.timeout(settings.sp_chart_total_deadline_seconds):
                conninfo = self._build_conninfo(lease, exec_run_id, query.connector_name)
                try:
                    async with await self._connect_factory(
                        conninfo, autocommit=True
                    ) as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(query.sql, effective_params or {})
                            columns, rows, truncated = await accumulate_rows(
                                cur,
                                settings.sp_chart_max_rows,
                                settings.sp_chart_max_cell_bytes,
                            )
                except asyncio.TimeoutError:
                    raise
                except psycopg.Error as exc:
                    logger.error(
                        "chart_execution_failed cid=%s connector=%s exc=%r",
                        cid,
                        query.connector_name,
                        exc,
                        extra={"correlation_id": cid},
                    )
                    raise ChartExecutionFailed(cid) from exc
        except asyncio.TimeoutError:
            logger.error(
                "chart_execution_timeout cid=%s connector=%s",
                cid,
                query.connector_name,
                extra={"correlation_id": cid},
            )
            raise ChartExecutionTimeout(cid)
        finally:
            try:
                await self._token_client.revoke(exec_run_id)
            except Exception as revoke_exc:
                logger.warning(
                    "chart_execute_revoke_failed cid=%s err=%s",
                    cid,
                    type(revoke_exc).__name__,
                    extra={"correlation_id": cid},
                )

        cache_key = compute_cache_key(query.connector_name, query.sql, effective_params)
        result_json: dict[str, Any] = {"columns": columns, "rows": rows}
        if truncated:
            result_json["truncated"] = True

        await persist_cache(session, cache_key, query, result_json)
        await session.commit()

        computed_at = datetime.now(tz=timezone.utc)
        return ChartExecutionResult(
            cache_key=cache_key,
            computed_at=computed_at,
            columns=columns,
            rows=rows,
            truncated=truncated,
        )

    def _build_conninfo(
        self,
        lease: Any,
        exec_run_id: uuid.UUID,
        connector_name: str,
    ) -> str:
        """Build a libpq conninfo string for connecting to the dbt-proxy.

        The gateway ignores the database field for routing (routing is via
        claims.connector_name from the token). We pass connector_name as dbname
        for log clarity per spec-reviewer Q3 adjustment.
        """
        settings = self._settings
        return make_conninfo(
            host=settings.sp_dbt_proxy_host,
            port=lease.host_port,
            user=f"run-{exec_run_id}",
            password=lease.token,
            dbname=connector_name,
            connect_timeout=settings.sp_chart_connect_timeout_seconds,
            sslmode="disable",
            options=f"-c statement_timeout={settings.sp_chart_statement_timeout_ms}",
            application_name=f"signalpilot-chart-exec/{exec_run_id}",
        )


__all__ = ["DbtProxyExecutor", "ChartExecutionResult"]
