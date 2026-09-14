"""Dataset loading: CSV coercion, snapshot and sidecar checks, path safety."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from signalpilot._dashboard_sql import sidecar_path, snapshot_path
from signalpilot._sdk._dashboards import write_sidecar, write_snapshot
from signalpilot._server.ai.dashboard.datasets import (
    coerce_cell,
    load_dataset,
    load_datasets,
    parse_csv,
    resolve_scratch_path,
)

if TYPE_CHECKING:
    from pathlib import Path

SQL = "select month, revenue from m"
DEFINITION = {"connection": "warehouse", "sql": SQL}


def write_dataset(
    scratch: Path,
    name: str,
    rows: list[dict[str, Any]],
    *,
    connection: str = "warehouse",
    sql: str = SQL,
    columns: list[str] | None = None,
) -> None:
    """Write a snapshot and sidecar the way ``sp.dashboard_dataset`` does."""
    names = columns or (list(rows[0]) if rows else [])
    write_snapshot(scratch / snapshot_path(name), names, rows)
    write_sidecar(
        sidecar_path(scratch, name),
        connection=connection,
        sql=sql,
        columns=names,
        row_count=len(rows),
    )


def test_coerce_cell_numeric_and_empty():
    assert coerce_cell("12") == 12
    assert isinstance(coerce_cell("12"), int)
    assert coerce_cell(" 3.5 ") == 3.5
    assert coerce_cell("-1e3") == -1000.0
    assert coerce_cell("") is None
    assert coerce_cell("   ") is None
    assert coerce_cell("abc") == "abc"
    assert coerce_cell("12abc") == "12abc"
    assert coerce_cell("nan") == "nan"
    assert coerce_cell("2025-01-01") == "2025-01-01"


def test_parse_csv_with_quotes_and_blank_lines():
    text = 'month,region,revenue\n2025-01-01,"East, US",10.5\n2025-02-01,West,\n\n'
    header, rows = parse_csv(text)
    assert header == ["month", "region", "revenue"]
    assert rows == [
        {"month": "2025-01-01", "region": "East, US", "revenue": 10.5},
        {"month": "2025-02-01", "region": "West", "revenue": None},
    ]
    assert parse_csv("") == ([], [])
    assert parse_csv("a,b\n") == (["a", "b"], [])


def test_resolve_scratch_path_rejects_escapes(tmp_path: Path):
    (tmp_path / "artifacts").mkdir()
    ok = resolve_scratch_path(tmp_path, "artifacts/sub/x.csv")
    assert ok == (tmp_path / "artifacts" / "sub" / "x.csv").resolve()
    for bad in (
        "x.csv",
        "artifacts",
        "artifacts/",
        "/artifacts/x.csv",
        "artifacts/../secret.csv",
        "artifacts/./x.csv",
        "../artifacts/x.csv",
        "notebooks/x.csv",
    ):
        with pytest.raises(ValueError, match="Path"):
            resolve_scratch_path(tmp_path, bad)


def test_sql_dataset_loads_from_snapshot_with_matching_sidecar(tmp_path: Path):
    write_dataset(tmp_path, "monthly", [{"month": "2025-01-01", "revenue": 10}])
    loaded = load_dataset(
        tmp_path,
        "monthly",
        {"connection": "warehouse", "sql": "  select month,\n revenue  from m "},
    )
    assert loaded.error is None
    assert loaded.code is None
    assert loaded.resolved_file == "artifacts/datasets/monthly.csv"
    assert loaded.rows == [{"month": "2025-01-01", "revenue": 10}]


def test_static_rows_are_inline(tmp_path: Path):
    inline = load_dataset(tmp_path, "labels", {"rows": [{"a": 1}, "junk"]})
    assert inline.rows == [{"a": 1}]
    assert inline.resolved_file is None
    assert inline.error is None


def test_snapshot_missing(tmp_path: Path):
    loaded = load_dataset(tmp_path, "monthly", DEFINITION)
    assert loaded.code == "snapshot_missing"
    assert loaded.resolved_file == "artifacts/datasets/monthly.csv"
    assert loaded.error == (
        "Dataset 'monthly' has no snapshot. Call "
        "sp.dashboard_dataset('monthly', connection=..., sql=...) in the "
        "notebook."
    )


def test_snapshot_stale_when_sidecar_is_absent(tmp_path: Path):
    write_dataset(tmp_path, "monthly", [{"month": "2025-01-01", "revenue": 10}])
    sidecar_path(tmp_path, "monthly").unlink()
    loaded = load_dataset(tmp_path, "monthly", DEFINITION)
    assert loaded.code == "snapshot_stale"
    assert loaded.rows == []
    assert "has no record of the SQL that produced it" in loaded.error
    assert "sp.dashboard_dataset('monthly'" in loaded.error


def test_snapshot_stale_when_sql_differs(tmp_path: Path):
    write_dataset(tmp_path, "monthly", [{"month": "2025-01-01", "revenue": 10}])
    loaded = load_dataset(
        tmp_path,
        "monthly",
        {"connection": "warehouse", "sql": "select month, revenue * 2 from m"},
    )
    assert loaded.code == "snapshot_stale"
    assert (
        "the SQL in the dashboard file is not the SQL that produced the snapshot"
        in loaded.error
    )


def test_snapshot_stale_when_connection_differs(tmp_path: Path):
    write_dataset(tmp_path, "monthly", [{"month": "2025-01-01", "revenue": 10}])
    loaded = load_dataset(
        tmp_path, "monthly", {"connection": "other", "sql": SQL}
    )
    assert loaded.code == "snapshot_stale"
    assert "('other')" in loaded.error
    assert "('warehouse')" in loaded.error


def test_snapshot_stale_when_csv_header_differs_from_sidecar(tmp_path: Path):
    write_dataset(tmp_path, "monthly", [{"month": "2025-01-01", "revenue": 10}])
    (tmp_path / snapshot_path("monthly")).write_text(
        "month,region,revenue\n2025-01-01,east,10\n", encoding="utf-8"
    )
    loaded = load_dataset(tmp_path, "monthly", DEFINITION)
    assert loaded.code == "snapshot_stale"
    assert "snapshot columns (month, region, revenue)" in loaded.error
    assert "recorded columns (month, revenue)" in loaded.error


def test_unreadable_and_malformed_definitions(tmp_path: Path):
    write_dataset(tmp_path, "monthly", [{"month": "2025-01-01", "revenue": 10}])
    (tmp_path / snapshot_path("monthly")).write_bytes(b"\xff\xfe\x00bad")
    broken = load_dataset(tmp_path, "monthly", DEFINITION)
    assert broken.code == "dataset_unreadable"
    assert "artifacts/datasets/monthly.csv" in broken.error

    corrupt_sidecar = sidecar_path(tmp_path, "monthly")
    write_dataset(tmp_path, "monthly", [{"month": "2025-01-01", "revenue": 10}])
    corrupt_sidecar.write_text("{", encoding="utf-8")
    assert load_dataset(tmp_path, "monthly", DEFINITION).code == "snapshot_stale"

    assert load_dataset(tmp_path, "x", "nope").code == "dataset_unreadable"
    assert load_dataset(tmp_path, "x", {}).code == "dataset_unreadable"
    assert load_dataset(tmp_path, "x", {"rows": 3}).code == "dataset_unreadable"
    assert (
        load_dataset(tmp_path, "x", {"file": "artifacts/x.csv"}).code
        == "dataset_unreadable"
    )


def test_load_datasets_selects_names(tmp_path: Path):
    write_dataset(tmp_path, "b", [{"x": 2}])
    spec = {
        "datasets": {
            "a": {"rows": [{"x": 1}]},
            "b": DEFINITION,
            "c": DEFINITION,
        }
    }
    everything = load_datasets(tmp_path, spec)
    assert set(everything) == {"a", "b", "c"}
    assert everything["b"].rows == [{"x": 2}]
    assert everything["c"].code == "snapshot_missing"
    assert set(load_datasets(tmp_path, spec, {"b"})) == {"b"}
    assert json.loads(sidecar_path(tmp_path, "b").read_text())["row_count"] == 1
