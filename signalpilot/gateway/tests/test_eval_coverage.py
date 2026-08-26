"""Verify coverage calculations in gateway/evals/coverage.py.

The audit trail supplies observed tables for one run. SQLite filters the rows
in Python. PostgreSQL filters the rows in SQL. Partial-run coverage counts only
the executed tasks.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import gateway.db.engine as db_engine
from gateway.db.models import GatewayAuditLog, GatewayBase
from gateway.evals import coverage

ORG = "org-cov"
RUN = "run-20260101-000001-abc123"


@pytest_asyncio.fixture
async def factory(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(db_engine, "get_session_factory", lambda: maker)
    yield maker
    await engine.dispose()


def _audit(ts: float, *, run: str | None, task: str = "t1", **kw) -> GatewayAuditLog:
    meta = {"eval_run": run, "eval_task": task} if run else {}
    return GatewayAuditLog(
        org_id=kw.pop("org_id", ORG),
        timestamp=ts,
        event_type=kw.pop("event_type", "mcp_tool"),
        metadata_json=meta,
        **kw,
    )


async def _seed(factory, rows) -> None:
    async with factory() as session:
        session.add_all(rows)
        await session.commit()


def _task(tid: str, covers: list[str], builds: list[str] | None = None):
    return SimpleNamespace(id=tid, covers=covers, builds=builds or [])


class TestObservedTablesForRun:
    async def test_parses_tables_and_sql_scoped_to_the_run(self, factory) -> None:
        await _seed(
            factory,
            [
                _audit(1.0, run=RUN, tables=["analytics.fct_orders"]),
                _audit(
                    2.0,
                    run=RUN,
                    task="t2",
                    sql_text="SELECT * FROM analytics.dim_users u JOIN staging.stg_payments p ON 1=1",
                ),
                _audit(3.0, run="run-other", tables=["analytics.fct_secret"]),
                _audit(4.0, run=None, tables=["analytics.fct_ambient"]),
                _audit(5.0, run=RUN, event_type="query", tables=["analytics.not_mcp"]),
            ],
        )
        out = await coverage.observed_tables_for_run(ORG, RUN)
        assert out["t1"] == {"analytics.fct_orders"}
        assert out["t2"] == {"analytics.dim_users", "staging.stg_payments"}
        flat = set().union(*out.values())
        assert "analytics.fct_secret" not in flat
        assert "analytics.fct_ambient" not in flat
        assert "analytics.not_mcp" not in flat

    async def test_other_org_rows_are_invisible(self, factory) -> None:
        await _seed(factory, [_audit(1.0, run=RUN, org_id="org-else", tables=["x.y"])])
        assert await coverage.observed_tables_for_run(ORG, RUN) == {}


class TestComputeCoverage:
    _models = [
        {"name": "fct_orders", "layer": "marts"},
        {"name": "dim_users", "layer": "marts"},
        {"name": "stg_payments", "layer": "staging"},
        {"name": "fct_untouched", "layer": "marts"},
    ]

    def _set(self):
        return SimpleNamespace(
            tasks=[
                _task("t1", covers=["analytics.fct_orders"]),
                _task("t2", covers=["dim_users"], builds=["fct_untouched"]),
            ]
        )

    async def test_executed_task_ids_restricts_declared_union(self, factory, monkeypatch) -> None:
        async def fake_observed(org_id, run_id):
            return {"t1": {"analytics.fct_orders"}}

        monkeypatch.setattr(coverage, "observed_tables_for_run", fake_observed)
        partial = await coverage.compute_coverage(
            ORG, RUN, self._set(), self._models, executed_task_ids={"t1"}
        )
        assert partial["declared"] == ["fct_orders"]
        assert partial["models_covered"] == 1
        marts = {model["name"]: model for model in partial["models"]}
        assert marts["fct_orders"]["declared_by"] == ["t1"]
        assert marts["fct_orders"]["observed_by"] == ["t1"]
        assert marts["fct_untouched"]["covered"] is False

        full = await coverage.compute_coverage(ORG, RUN, self._set(), self._models)
        assert full["declared"] == ["dim_users", "fct_orders", "fct_untouched"]
        assert full["models_covered"] == 3

    async def test_declared_but_not_observed(self, factory, monkeypatch) -> None:
        async def fake_observed(org_id, run_id):
            return {"t1": {"analytics.fct_orders", "staging.stg_payments"}}

        monkeypatch.setattr(coverage, "observed_tables_for_run", fake_observed)
        result = await coverage.compute_coverage(ORG, RUN, self._set(), self._models)
        assert result["declared_but_not_observed"] == ["dim_users", "fct_untouched"]
        assert result["observed_not_declared"] == ["stg_payments"]

    async def test_end_to_end_on_sqlite_audit_rows(self, factory) -> None:
        await _seed(
            factory,
            [
                _audit(1.0, run=RUN, tables=["analytics.fct_orders"]),
                _audit(2.0, run=RUN, sql_text="select 1 from stg_payments"),
            ],
        )
        result = await coverage.compute_coverage(
            ORG, RUN, self._set(), self._models, executed_task_ids={"t1"}
        )
        assert result["observed"] == ["fct_orders", "stg_payments"]
        assert result["declared"] == ["fct_orders"]
        assert result["declared_but_not_observed"] == []
        assert result["observed_not_declared"] == ["stg_payments"]
        assert result["per_task_observed"]["t1"] == [
            "analytics.fct_orders",
            "stg_payments",
        ]
