"""Tests for dashboard chart routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from workspaces_api.dashboards.cache import compute_cache_key
from workspaces_api.dashboards.executor import ChartExecutionResult
from workspaces_api.dashboards.models import ChartCache


_BASE_CREATE = {
    "workspace_id": "ws-test",
    "title": "My Chart",
    "chart_type": "line",
    "echarts_option_json": {},
    "query": {
        "connector_name": "my_conn",
        "sql": "SELECT id FROM foo",
        "params": {},
        "refresh_interval_seconds": 3600,
    },
}

_EXECUTION_RESULT = ChartExecutionResult(
    cache_key="abc123",
    computed_at=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
    columns=[{"name": "id", "type_hint": "int"}],
    rows=[[1], [2]],
    truncated=False,
)


class _FakeExecutor:
    """Stub executor returning a deterministic ChartExecutionResult."""

    async def execute(self, chart: Any, query: Any, params: Any, session: Any) -> ChartExecutionResult:
        return _EXECUTION_RESULT


class TestDashboardRoutes:
    async def test_create_chart_happy_path(self, client, db_session) -> None:
        resp = await client.post("/v1/charts", json=_BASE_CREATE)
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "My Chart"
        assert data["chart_type"] == "line"
        assert data["query"] is not None
        assert data["query"]["connector_name"] == "my_conn"

    async def test_create_chart_sql_too_long_returns_422(self, client) -> None:
        body = dict(_BASE_CREATE)
        body["query"] = dict(body["query"])
        body["query"]["sql"] = "x" * 50_001
        resp = await client.post("/v1/charts", json=body)
        assert resp.status_code == 422

    async def test_get_chart_200_and_404(self, client, db_session) -> None:
        resp = await client.post("/v1/charts", json=_BASE_CREATE)
        assert resp.status_code == 201
        chart_id = resp.json()["id"]

        get_resp = await client.get(f"/v1/charts/{chart_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == chart_id

        missing_resp = await client.get(f"/v1/charts/{uuid.uuid4()}")
        assert missing_resp.status_code == 404

    async def test_list_charts_paginated_desc(self, client, db_session) -> None:
        # Create 3 charts
        for i in range(3):
            body = dict(_BASE_CREATE)
            body["title"] = f"Chart {i}"
            await client.post("/v1/charts", json=body)

        resp = await client.get("/v1/charts?workspace=ws-test&limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["next_cursor"] is not None

        # Follow cursor
        cursor = data["next_cursor"]
        resp2 = await client.get(f"/v1/charts?workspace=ws-test&limit=2&cursor={cursor}")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["items"]) >= 1

    async def test_run_chart_cache_hit_returns_200(self, client, db_session) -> None:
        resp = await client.post("/v1/charts", json=_BASE_CREATE)
        assert resp.status_code == 201
        chart_id = resp.json()["id"]
        chart_query_id = resp.json()["query"]["id"]

        # Directly insert a cache row
        cache_key = compute_cache_key("my_conn", "SELECT id FROM foo", {})
        now = datetime.now(tz=timezone.utc)
        cache = ChartCache(
            cache_key=cache_key,
            query_id=uuid.UUID(chart_query_id),
            result_json={
                "columns": [{"name": "id", "type_hint": "integer"}],
                "rows": [[1], [2]],
            },
            computed_at=now,
            expires_at=now + timedelta(hours=1),
        )
        db_session.add(cache)
        await db_session.commit()

        run_resp = await client.post(f"/v1/charts/{chart_id}/run", json={"force": False})
        assert run_resp.status_code == 200
        run_data = run_resp.json()
        assert run_data["cached"] is True
        assert run_data["chart_id"] == chart_id

    async def test_run_chart_cache_miss_calls_executor_returns_200(
        self, client, app
    ) -> None:
        app.state.chart_executor = _FakeExecutor()

        resp = await client.post("/v1/charts", json=_BASE_CREATE)
        assert resp.status_code == 201
        chart_id = resp.json()["id"]

        run_resp = await client.post(f"/v1/charts/{chart_id}/run", json={"force": False})
        assert run_resp.status_code == 200
        run_data = run_resp.json()
        assert run_data["cached"] is False
        assert run_data["chart_id"] == chart_id
        assert run_data["truncated"] is False
        assert run_data["rows"] == [[1], [2]]

        # Cleanup
        app.state.chart_executor = None

    async def test_run_chart_no_executor_returns_503(self, client, app) -> None:
        app.state.chart_executor = None

        resp = await client.post("/v1/charts", json=_BASE_CREATE)
        assert resp.status_code == 201
        chart_id = resp.json()["id"]

        run_resp = await client.post(f"/v1/charts/{chart_id}/run", json={"force": False})
        assert run_resp.status_code == 503
