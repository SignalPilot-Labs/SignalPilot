"""Tests for dashboards cache helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from workspaces_api.dashboards.cache import compute_cache_key, fetch_cached, persist_cache
from workspaces_api.dashboards.models import Chart, ChartCache, ChartQuery


class TestDashboardsCache:
    async def test_compute_cache_key_deterministic(self) -> None:
        k1 = compute_cache_key("my_conn", "SELECT 1", {"a": 1, "b": 2})
        k2 = compute_cache_key("my_conn", "SELECT 1", {"b": 2, "a": 1})
        assert k1 == k2
        assert len(k1) == 64

    async def test_compute_cache_key_different_sql_differs(self) -> None:
        k1 = compute_cache_key("conn", "SELECT 1", {})
        k2 = compute_cache_key("conn", "SELECT 2", {})
        assert k1 != k2

    async def test_fetch_cached_returns_none_when_expired(self, db_session) -> None:
        chart = Chart(
            id=uuid.uuid4(),
            workspace_id="ws-1",
            title="t",
            chart_type="line",
            echarts_option={},
        )
        db_session.add(chart)
        await db_session.flush()

        cq = ChartQuery(
            id=uuid.uuid4(),
            chart_id=chart.id,
            connector_name="c",
            sql="SELECT 1",
            params={},
            refresh_interval_seconds=3600,
        )
        db_session.add(cq)
        await db_session.flush()

        now = datetime.now(tz=timezone.utc)
        cache = ChartCache(
            cache_key="expired-key",
            query_id=cq.id,
            result_json={"columns": [], "rows": []},
            computed_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),  # already expired
        )
        db_session.add(cache)
        await db_session.flush()

        result = await fetch_cached(db_session, "expired-key")
        assert result is None

    async def test_persist_cache_upserts_on_primary_key(self, db_session) -> None:
        chart = Chart(
            id=uuid.uuid4(),
            workspace_id="ws-1",
            title="t",
            chart_type="table",
            echarts_option={},
        )
        db_session.add(chart)
        await db_session.flush()

        cq = ChartQuery(
            id=uuid.uuid4(),
            chart_id=chart.id,
            connector_name="c",
            sql="SELECT 1",
            params={},
            refresh_interval_seconds=60,
        )
        db_session.add(cq)
        await db_session.flush()

        result_json = {"columns": [{"name": "x", "type_hint": "integer"}], "rows": [[1]]}
        row1 = await persist_cache(db_session, "upsert-key", cq, result_json)
        assert row1.cache_key == "upsert-key"

        result_json2 = {"columns": [{"name": "x", "type_hint": "integer"}], "rows": [[2]]}
        row2 = await persist_cache(db_session, "upsert-key", cq, result_json2)
        assert row2.cache_key == "upsert-key"
        assert row2.result_json["rows"][0][0] == 2
