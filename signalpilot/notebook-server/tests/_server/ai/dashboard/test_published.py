"""dashboard_list_published and dashboard_load_published contracts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from signalpilot._dashboard_sql import sidecar_path, snapshot_path
from signalpilot._server.ai.dashboard.published import (
    list_published,
    load_published,
)
from signalpilot._server.ai.dashboard.tools import dashboard_sample_data

if TYPE_CHECKING:
    from pathlib import Path

GATEWAY = "https://gateway.test"
TOKEN = "scoped-token"
MONTHLY_SQL = "select month, revenue from m order by 1"

SUMMARY = {
    "id": "dash_1",
    "slug": "monthly-savings",
    "name": "Monthly savings",
    "description": "Savings by month",
    "visibility": "org",
    "project_id": "project-a",
    "created_by_user_id": "user_1",
    "created_by_label": "user_1",
    "source_conversation_id": None,
    "source_file_id": None,
    "current_version_id": "ver_3",
    "current_version_no": 3,
    "chart_count": 2,
    "refresh": {
        "interval_minutes": None,
        "anchor_time": None,
        "timezone": "UTC",
        "mode": "sql",
    },
    "notify_on_failure": True,
    "next_refresh_at": None,
    "last_refresh_at": "2026-09-01T00:00:00Z",
    "last_refresh_status": "succeeded",
    "created_at": "2026-08-01T00:00:00Z",
    "updated_at": "2026-09-01T00:00:00Z",
    "archived_at": None,
    "can_edit": True,
}
SPEC: dict[str, Any] = {
    "version": 1,
    "title": "Monthly savings",
    "datasets": {
        "monthly": {"connection": "warehouse", "sql": MONTHLY_SQL},
        "totals": {"rows": [{"revenue": 60}]},
    },
    "charts": [
        {
            "id": "rev",
            "type": "line",
            "title": "Revenue",
            "dataset": "monthly",
            "x": {"column": "month", "type": "date"},
            "y": [{"column": "revenue", "format": "integer"}],
        },
        {
            "id": "total",
            "type": "kpi",
            "title": "Total",
            "dataset": "totals",
            "value": {"column": "revenue"},
        },
    ],
}
BUNDLE = {
    "dashboard": SUMMARY,
    "version": {
        "id": "ver_3",
        "version_no": 3,
        "produced_by": "publish",
        "producer_ref": None,
        "chart_count": 2,
        "dataset_meta": {},
        "created_at": "2026-09-01T00:00:00Z",
    },
    "spec": SPEC,
    "datasets": {
        "monthly": [
            {"month": "2025-01-01", "revenue": 10},
            {"month": "2025-02-01", "revenue": 20.5},
            {"month": "2025-03-01", "revenue": None},
        ],
        "totals": [{"revenue": 60}],
    },
}


class FakeGateway:
    """Routes the dashboards API; records every request it sees."""

    def __init__(self, *, status: int | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status is not None:
            return httpx.Response(
                self.status, json={"detail": "Forbidden for this identity"}
            )
        path = request.url.path
        if path == "/api/dashboards":
            return httpx.Response(200, json={"dashboards": [SUMMARY]})
        if path in {
            "/api/dashboards/dash_1",
            "/api/dashboards/monthly-savings",
        }:
            return httpx.Response(
                200,
                json={"dashboard": SUMMARY, "versions": [], "refreshes": []},
            )
        if path == "/api/dashboards/dash_1/versions/ver_3/bundle":
            return httpx.Response(200, json=BUNDLE)
        return httpx.Response(404, json={"detail": "Dashboard not found"})


@pytest.mark.asyncio
async def test_list_published_projects_the_gallery_fields():
    gateway = FakeGateway()
    listed = await list_published(
        gateway_url=GATEWAY + "/",
        gateway_token=TOKEN,
        transport=gateway.transport(),
    )
    assert listed == {
        "dashboards": [
            {
                "id": "dash_1",
                "slug": "monthly-savings",
                "name": "Monthly savings",
                "description": "Savings by month",
                "chart_count": 2,
                "visibility": "org",
                "updated_at": "2026-09-01T00:00:00Z",
                "last_refresh_at": "2026-09-01T00:00:00Z",
                "can_edit": True,
            }
        ]
    }
    (request,) = gateway.requests
    assert str(request.url) == f"{GATEWAY}/api/dashboards"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.asyncio
async def test_load_published_restores_spec_snapshots_and_sidecars(
    tmp_path: Path,
):
    gateway = FakeGateway()
    # A stale file with the same slug is overwritten: the user edits it.
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "monthly-savings.dashboard.json").write_text(
        "{}", encoding="utf-8"
    )

    loaded = await load_published(
        scratch_directory=tmp_path,
        gateway_url=GATEWAY,
        gateway_token=TOKEN,
        dashboard="monthly-savings",
        transport=gateway.transport(),
    )

    assert loaded == {
        "path": "artifacts/monthly-savings.dashboard.json",
        "dashboard": {
            "id": "dash_1",
            "slug": "monthly-savings",
            "name": "Monthly savings",
            "version_no": 3,
            "chart_count": 2,
        },
        "datasets": {
            "monthly": {
                "rows": 3,
                "snapshot": "artifacts/datasets/monthly.csv",
            }
        },
        "next": (
            "Edit the file. If you change a dataset's SQL, call "
            "sp.dashboard_dataset for it again. The user publishes the new "
            "version from the chat panel."
        ),
    }
    assert [request.url.path for request in gateway.requests] == [
        "/api/dashboards/monthly-savings",
        "/api/dashboards/dash_1/versions/ver_3/bundle",
    ]
    assert all(
        request.headers["Authorization"] == f"Bearer {TOKEN}"
        for request in gateway.requests
    )

    spec_text = (tmp_path / loaded["path"]).read_text(encoding="utf-8")
    assert json.loads(spec_text) == SPEC
    assert spec_text.startswith("{\n  ")  # pretty-printed for editing

    snapshot = tmp_path / snapshot_path("monthly")
    assert snapshot.read_text(encoding="utf-8") == (
        "month,revenue\n2025-01-01,10\n2025-02-01,20.5\n2025-03-01,\n"
    )
    assert not (tmp_path / snapshot_path("totals")).exists()

    sidecar = json.loads(
        sidecar_path(tmp_path, "monthly").read_text(encoding="utf-8")
    )
    assert sidecar["connection"] == "warehouse"
    assert sidecar["sql"] == MONTHLY_SQL
    assert sidecar["columns"] == ["month", "revenue"]
    assert sidecar["row_count"] == 3
    assert sidecar["written_at"]
    assert sidecar["origin"] == {
        "dashboard_id": "dash_1",
        "version_id": "ver_3",
        "version_no": 3,
    }
    assert not sidecar_path(tmp_path, "totals").exists()

    # The check tools see the restored snapshot as current.
    checked = await dashboard_sample_data(
        scratch_directory=tmp_path,
        path=loaded["path"],
        chart_ids=["rev", "total"],
    )
    payload = json.loads(checked[0].text)
    assert payload["dashboard"] == {"valid": True, "errors": []}
    rev, total = payload["charts"]
    assert rev["issues"] == []
    assert rev["row_count"] == 3
    assert total["issues"] == []


@pytest.mark.asyncio
async def test_load_published_reports_not_found(tmp_path: Path):
    gateway = FakeGateway()
    missing = await load_published(
        scratch_directory=tmp_path,
        gateway_url=GATEWAY,
        gateway_token=TOKEN,
        dashboard="no-such-dashboard",
        transport=gateway.transport(),
    )
    assert missing["error"] == "not_found"
    assert "no-such-dashboard" in missing["message"]
    assert not (tmp_path / "artifacts").exists()

    bad_reference = await load_published(
        scratch_directory=tmp_path,
        gateway_url=GATEWAY,
        gateway_token=TOKEN,
        dashboard="../etc",
        transport=gateway.transport(),
    )
    assert bad_reference["error"] == "not_found"
    assert len(gateway.requests) == 1


@pytest.mark.asyncio
async def test_gateway_rejection_surfaces_the_http_status(tmp_path: Path):
    gateway = FakeGateway(status=403)
    listed = await list_published(
        gateway_url=GATEWAY,
        gateway_token=TOKEN,
        transport=gateway.transport(),
    )
    assert listed["error"] == "gateway_error"
    assert listed["status"] == 403
    assert "Forbidden for this identity" in listed["message"]

    loaded = await load_published(
        scratch_directory=tmp_path,
        gateway_url=GATEWAY,
        gateway_token=TOKEN,
        dashboard="dash_1",
        transport=gateway.transport(),
    )
    assert loaded["error"] == "gateway_error"
    assert loaded["status"] == 403

    no_identity = await list_published(gateway_url=GATEWAY, gateway_token="")
    assert no_identity["error"] == "gateway_error"
    assert no_identity["status"] is None
