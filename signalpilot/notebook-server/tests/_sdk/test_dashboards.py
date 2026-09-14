"""``sp.dashboard_dataset``: governed query, CSV snapshot, sidecar."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import pytest

from signalpilot._dashboard_sql import (
    normalized_sql,
    normalized_sql_hash,
    sidecar_path,
    snapshot_path,
)
from signalpilot._sdk._connection import Connection
from signalpilot._sdk._dashboards import dashboard_dataset

if TYPE_CHECKING:
    from pathlib import Path

SQL = "select  month,\n  revenue from m\n"


class FakeClient:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, path: str, body: dict[str, Any], **_kwargs: Any) -> Any:
        self.calls.append((path, body))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _result(rows: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    columns = [{"name": key} for key in rows[0]] if rows else []
    return {"rows": rows, "columns": columns, "completeness": "complete", **extra}


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SP_CHAT_SCRATCH_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("SP_CHAT_ARTIFACTS_DIRECTORY", str(tmp_path / "artifacts"))
    return tmp_path


def test_normalized_sql_hash_ignores_surrounding_and_internal_whitespace():
    assert normalized_sql(SQL) == "select month, revenue from m"
    assert normalized_sql_hash(SQL) == normalized_sql_hash(
        "select month, revenue from m"
    )
    assert normalized_sql_hash("select 1") != normalized_sql_hash("select 2")
    assert snapshot_path("monthly") == "artifacts/datasets/monthly.csv"


def test_dashboard_dataset_writes_snapshot_and_sidecar(
    scratch: Path, capsys: pytest.CaptureFixture[str]
):
    rows = [
        {
            "month": date(2025, 1, 1),
            "region": "East, US",
            "revenue": 10.5,
            "orders": 3,
            "note": None,
            "flag": True,
            "seen": datetime(2025, 1, 2, 3, 4, 5),
        },
        {
            "month": "2025-02-01",
            "region": "West",
            "revenue": 20,
            "orders": None,
            "note": "x",
            "flag": False,
            "seen": None,
        },
    ]
    client = FakeClient(_result(rows))
    frame = dashboard_dataset(
        Connection("warehouse", client),  # type: ignore[arg-type]
        "monthly",
        sql=SQL,
        row_limit=100,
    )

    assert client.calls == [
        (
            "/api/query",
            {"connection_name": "warehouse", "sql": SQL, "row_limit": 100},
        )
    ]
    csv_text = (scratch / snapshot_path("monthly")).read_text(encoding="utf-8")
    assert csv_text == (
        "month,region,revenue,orders,note,flag,seen\n"
        '2025-01-01,"East, US",10.5,3,,True,2025-01-02T03:04:05\n'
        "2025-02-01,West,20,,x,False,\n"
    )
    sidecar = json.loads(
        sidecar_path(scratch, "monthly").read_text(encoding="utf-8")
    )
    assert sidecar["connection"] == "warehouse"
    assert sidecar["sql"] == SQL
    assert sidecar["sql_hash"] == normalized_sql_hash(SQL)
    assert sidecar["columns"] == [
        "month",
        "region",
        "revenue",
        "orders",
        "note",
        "flag",
        "seen",
    ]
    assert sidecar["row_count"] == 2
    assert datetime.fromisoformat(sidecar["written_at"]).tzinfo is not None
    assert list(frame.columns) == sidecar["columns"]
    assert len(frame) == 2
    assert capsys.readouterr().out == (
        "dashboard dataset 'monthly': 2 rows, columns: month, region, "
        "revenue, orders, note, flag, seen\n"
    )


def test_column_order_falls_back_to_row_keys_and_empty_results(scratch: Path):
    client = FakeClient({"rows": [{"b": 1, "a": 2}], "completeness": "complete"})
    dashboard_dataset(
        Connection("w", client),  # type: ignore[arg-type]
        "keyed",
        sql="select 1",
    )
    assert (scratch / snapshot_path("keyed")).read_text(encoding="utf-8") == (
        "b,a\n1,2\n"
    )

    empty = dashboard_dataset(
        Connection("w", FakeClient(_result([]))),  # type: ignore[arg-type]
        "empty",
        sql="select 1 where false",
    )
    assert len(empty) == 0
    assert (scratch / snapshot_path("empty")).read_text(encoding="utf-8") == "\n"
    assert json.loads(sidecar_path(scratch, "empty").read_text())["columns"] == []


def test_rejects_bad_names_empty_sql_and_row_cap(scratch: Path):
    connection = Connection("w", FakeClient(_result([{"a": 1}])))  # type: ignore[arg-type]
    for bad in ("Monthly", "1x", "a-b", "", "x" * 65):
        with pytest.raises(ValueError, match="not valid"):
            dashboard_dataset(connection, bad, sql="select 1")
    with pytest.raises(ValueError, match="has no SQL"):
        dashboard_dataset(connection, "ok", sql="  ")
    with pytest.raises(ValueError, match="row_limit"):
        dashboard_dataset(connection, "ok", sql="select 1", row_limit=0)

    truncated = Connection(  # type: ignore[arg-type]
        "w", FakeClient(_result([{"a": 1}], completeness="truncated"))
    )
    with pytest.raises(ValueError, match="Add a limit or aggregate"):
        dashboard_dataset(truncated, "big", sql="select a from t", row_limit=1)
    assert not (scratch / snapshot_path("big")).exists()
    assert not sidecar_path(scratch, "big").exists()


def test_query_failure_propagates_the_gateway_message(scratch: Path):
    failing = Connection(  # type: ignore[arg-type]
        "w", FakeClient(RuntimeError("Gateway error (HTTP 400): bad column"))
    )
    with pytest.raises(RuntimeError, match="bad column"):
        dashboard_dataset(failing, "broken", sql="select nope from t")
    assert not (scratch / snapshot_path("broken")).exists()


def test_sidecar_lives_beside_artifacts_when_only_artifacts_dir_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("SP_CHAT_SCRATCH_DIRECTORY", raising=False)
    monkeypatch.setenv("SP_CHAT_ARTIFACTS_DIRECTORY", str(tmp_path / "artifacts"))
    dashboard_dataset(
        Connection("w", FakeClient(_result([{"a": 1}]))),  # type: ignore[arg-type]
        "side",
        sql="select 1",
    )
    assert (tmp_path / "artifacts" / "datasets" / "side.csv").is_file()
    assert (tmp_path / ".dashboard-datasets" / "side.json").is_file()


@pytest.mark.usefixtures("scratch")
def test_top_level_helper_uses_the_initialized_gateway(
    monkeypatch: pytest.MonkeyPatch,
):
    import signalpilot._sdk as sdk

    with pytest.raises(RuntimeError, match="not initialized"):
        sdk.dashboard_dataset("m", connection="w", sql="select 1")

    client = FakeClient(_result([{"a": 1}]))
    monkeypatch.setattr(sdk, "_gw", client)
    frame = sdk.dashboard_dataset("m", connection="w", sql="select 1")
    assert client.calls[0][1]["connection_name"] == "w"
    assert client.calls[0][1]["row_limit"] == 50_000
    assert list(frame.columns) == ["a"]
