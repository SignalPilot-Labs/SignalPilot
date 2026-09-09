"""The one seam through which dashboards run SQL.

The publish gate and the sql-mode refresh both call ``run_dataset_query``.
Tests inject a fake ``QueryExecutor``; production uses the governed executor,
so every dashboard query is audited and policed like any other query.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from gateway.governance.query_executor import GovernedQueryContext, GovernedQueryError
from gateway.store import Store

from .datasets import Row, result_columns

# The refresh reproduces the whole dataset; the publish gate only needs the
# columns, so it asks for one row.
REFRESH_ROW_LIMIT = 50_000
REFRESH_TIMEOUT_SECONDS = 120
GATE_ROW_LIMIT = 1
GATE_TIMEOUT_SECONDS = 60
# Grace on top of the executor's own timeout before the awaiting side gives up.
TIMEOUT_GRACE_SECONDS = 30


class QueryExecutor(Protocol):
    async def execute(
        self,
        store: Store,
        *,
        connection_name: str,
        sql: str,
        row_limit: int,
        timeout_seconds: int,
        context: GovernedQueryContext,
    ) -> Any: ...


def governed_executor() -> QueryExecutor:
    from gateway.governance.query_executor import GovernedQueryExecutor

    return GovernedQueryExecutor()


class DatasetQueryError(Exception):
    """A dataset query did not produce rows. ``str(error)`` is the user-facing text."""


@dataclass(frozen=True)
class DatasetQueryResult:
    columns: list[str]
    rows: list[Row]


async def run_dataset_query(
    executor: QueryExecutor,
    query_store: Store,
    *,
    connection: str,
    sql: str,
    row_limit: int,
    timeout_seconds: int,
    context: GovernedQueryContext,
) -> DatasetQueryResult:
    """Run one dataset's SQL. Raises ``DatasetQueryError`` with a plain message."""
    try:
        result = await asyncio.wait_for(
            executor.execute(
                query_store,
                connection_name=connection,
                sql=sql,
                row_limit=row_limit,
                timeout_seconds=timeout_seconds,
                context=context,
            ),
            timeout=timeout_seconds + TIMEOUT_GRACE_SECONDS,
        )
    except GovernedQueryError as exc:
        raise DatasetQueryError(f"{exc.code}: {exc}") from exc
    except TimeoutError as exc:
        raise DatasetQueryError(f"Query timed out after {timeout_seconds}s") from exc
    except Exception as exc:
        raise DatasetQueryError(f"Query failed: {exc}") from exc
    rows = [dict(row) for row in result.rows or []]
    return DatasetQueryResult(columns=result_columns(getattr(result, "columns", None), rows), rows=rows)
