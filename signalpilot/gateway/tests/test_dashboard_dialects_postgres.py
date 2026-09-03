"""Required Docker-backed PostgreSQL dashboard acceptance path."""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.connectors.drivers.postgres import PostgresConnector
from gateway.dashboard.compiler import compile_distinct_values_query, compile_metric_query
from gateway.dashboard.domain import SemanticChartQuery
from gateway.db.models import GatewayBase
from gateway.governance.plan_limits import PLAN_TIERS
from gateway.governance.query_executor import GovernedQueryContext, GovernedQueryExecutor
from gateway.models import ConnectionCreate, DBType
from gateway.models.dashboards import (
    DashboardSemanticContext,
    DashboardSemanticExplore,
    DashboardSemanticField,
    DashboardSemanticMetric,
)
from gateway.store import Store

COMPOSE_FILE = Path(__file__).parent / "fixtures" / "dashboard-postgres-compose.yml"


def _context() -> DashboardSemanticContext:
    return DashboardSemanticContext(
        project_id="postgres-project",
        commit_sha="b" * 40,
        connection_name="postgres-dashboard",
        connection_type="postgres",
        physical_schema_fingerprint="physical",
        semantic_fingerprint="semantic",
        explores=[
            DashboardSemanticExplore(
                name="orders",
                label="Orders",
                relation="analytics.orders",
                dimensions=[
                    DashboardSemanticField(
                        field_id="orders.region",
                        column="region",
                        logical_type="string",
                    ),
                    DashboardSemanticField(
                        field_id="orders.ordered_at",
                        column="ordered_at",
                        logical_type="timestamp",
                    ),
                ],
                metrics=[
                    DashboardSemanticMetric(
                        field_id="orders.revenue",
                        column="revenue",
                        logical_type="number",
                        aggregation="sum",
                        label="Revenue",
                        semantic_source="dbt_project",
                        aggregation_inferred=True,
                    )
                ],
            )
        ],
    )


def _query() -> SemanticChartQuery:
    return SemanticChartQuery.model_validate(
        {
            "kind": "semantic",
            "projectId": "postgres-project",
            "commitSha": "b" * 40,
            "exploreName": "orders",
            "dimensions": ["orders.region"],
            "metrics": ["orders.revenue"],
            "filters": {
                "dimensions": {
                    "id": "all",
                    "and": [
                        {
                            "id": "region",
                            "operator": "equals",
                            "values": ["North", "South"],
                            "target": {"fieldId": "orders.region"},
                        },
                        {
                            "id": "date",
                            "operator": "inBetween",
                            "values": ["2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"],
                            "target": {"fieldId": "orders.ordered_at"},
                        },
                    ],
                }
            },
            "sorts": [{"fieldId": "orders.revenue", "descending": True}],
            "limit": 100,
        }
    )


def _compose(*args: str, project: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-p", project, "-f", str(COMPOSE_FILE), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.mark.asyncio
async def test_postgres_dashboard_golden_path(monkeypatch) -> None:
    compose_project = f"sp-dashboard-{uuid.uuid4().hex[:10]}"
    _compose("up", "-d", "--wait", project=compose_project)
    try:
        port_output = _compose("port", "dashboard-postgres", "5432", project=compose_project).stdout.strip()
        port = int(port_output.rsplit(":", 1)[1])
        connection_string = f"postgresql://signalpilot:signalpilot-test@127.0.0.1:{port}/signalpilot_dashboard"
        seed = None
        for _ in range(40):
            try:
                seed = await asyncpg.connect(connection_string)
                break
            except (ConnectionError, OSError, asyncpg.PostgresConnectionError):
                await asyncio.sleep(0.25)
        assert seed is not None, "PostgreSQL 17 fixture did not accept connections"
        try:
            await seed.execute("CREATE SCHEMA analytics")
            await seed.execute(
                "CREATE TABLE analytics.orders ("
                "region TEXT NOT NULL, ordered_at TIMESTAMPTZ NOT NULL, revenue NUMERIC NOT NULL)"
            )
            await seed.executemany(
                "INSERT INTO analytics.orders VALUES ($1, $2, $3)",
                [
                    ("North", datetime(2026, 1, 3, tzinfo=UTC), Decimal("10")),
                    ("North", datetime(2026, 1, 4, tzinfo=UTC), Decimal("15")),
                    ("South", datetime(2026, 1, 5, tzinfo=UTC), Decimal("8")),
                    ("East", datetime(2026, 1, 6, tzinfo=UTC), Decimal("99")),
                ],
            )
        finally:
            await seed.close()

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as metadata_connection:
            await metadata_connection.run_sync(GatewayBase.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            store = Store(session, org_id="postgres-org", user_id="postgres-user")
            await store.create_connection(
                ConnectionCreate(
                    name="postgres-dashboard",
                    db_type=DBType.postgres,
                    connection_string=connection_string,
                )
            )

            async def unlimited(_org_id: str):
                return PLAN_TIERS["unlimited"]

            monkeypatch.setattr("gateway.governance.query_executor.get_org_limits", unlimited)
            compiled = compile_metric_query(_query(), _context())
            assert "$1" in compiled.sql and "$4" in compiled.sql
            result = await GovernedQueryExecutor().execute(
                store,
                connection_name="postgres-dashboard",
                sql=compiled.sql,
                parameters=compiled.parameters,
                bound_query=compiled.bound_query,
                row_limit=10,
                timeout_seconds=10,
                context=GovernedQueryContext(
                    path="dashboard",
                    project_id="postgres-project",
                    commit_sha="b" * 40,
                ),
            )
            assert result.completeness == "complete"
            assert result.rows == [
                {"orders.region": "North", "orders.revenue": Decimal("25")},
                {"orders.region": "South", "orders.revenue": Decimal("8")},
            ]

            payload = "North' OR 1=1 --"
            distinct = compile_distinct_values_query(
                explore_name="orders",
                field_id="orders.region",
                context=_context(),
                search=payload,
            )
            distinct_result = await GovernedQueryExecutor().execute(
                store,
                connection_name="postgres-dashboard",
                sql=distinct.sql,
                parameters=distinct.parameters,
                bound_query=distinct.bound_query,
                row_limit=100,
                timeout_seconds=10,
                context=GovernedQueryContext(path="dashboard", project_id="postgres-project"),
            )
            assert distinct_result.rows == []
            assert payload not in distinct.sql

        await engine.dispose()

        connector = PostgresConnector()
        await connector.connect(connection_string)
        running = asyncio.create_task(connector.execute("SELECT pg_sleep(30)", timeout=40))
        for _ in range(200):
            if getattr(connector, "_active_backend_pid", None) is not None:
                break
            await asyncio.sleep(0.01)
        assert await connector.cancel_current_query() is True
        with pytest.raises(asyncpg.QueryCanceledError):
            await running
        assert await connector.execute("SELECT 1 AS ready") == [{"ready": 1}]
        await connector.close()
    finally:
        _compose("down", "-v", "--remove-orphans", project=compose_project)
