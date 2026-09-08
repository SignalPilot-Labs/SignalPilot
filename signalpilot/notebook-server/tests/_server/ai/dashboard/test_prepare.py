"""Row preparation and check codes for dashboard charts."""

from __future__ import annotations

from typing import Any

import pytest

from signalpilot._server.ai.dashboard.datasets import LoadedDataset
from signalpilot._server.ai.dashboard.prepare import (
    chart_is_failed,
    infer_column_types,
    prepare_chart_rows,
)


def _spec(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "version": 1,
        "title": "T",
        "datasets": {"monthly": {"connection": "w", "sql": "select 1"}},
        "filters": [],
        "charts": [],
    }
    spec.update(overrides)
    return spec


def _rows() -> list[dict[str, Any]]:
    return [
        {"month": "2025-01-01", "region": "east", "revenue": 10},
        {"month": "2025-02-01", "region": "west", "revenue": 30},
        {"month": "2025-03-01", "region": "east", "revenue": 20},
        {"month": "2025-04-01", "region": "north", "revenue": None},
    ]


def _line(**overrides: Any) -> dict[str, Any]:
    chart: dict[str, Any] = {
        "id": "rev",
        "type": "line",
        "title": "Revenue",
        "dataset": "monthly",
        "x": {"column": "month", "type": "date"},
        "y": [{"column": "revenue"}],
    }
    chart.update(overrides)
    return chart


def _datasets(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "monthly": LoadedDataset(
            rows=_rows() if rows is None else rows,
            resolved_file="artifacts/datasets/monthly.csv",
        )
    }


def _codes(issues: list[dict[str, str]]) -> list[str]:
    return [issue["code"] for issue in issues]


def test_filters_equals_in_date_range_number_range():
    spec = _spec(
        filters=[
            {
                "id": "r",
                "label": "R",
                "dataset": "monthly",
                "column": "region",
                "type": "equals",
                "default": "east",
            }
        ]
    )
    rows, issues = prepare_chart_rows(_line(), spec, _datasets())
    assert [row["month"] for row in rows] == ["2025-01-01", "2025-03-01"]
    assert issues == []

    spec["filters"][0].update(type="in", default=["west", "north"])
    rows, _ = prepare_chart_rows(_line(), spec, _datasets())
    assert [row["region"] for row in rows] == ["west", "north"]

    # Empty "in" default and null "equals" default apply no filter.
    spec["filters"][0].update(type="in", default=[])
    assert len(prepare_chart_rows(_line(), spec, _datasets())[0]) == 4
    spec["filters"][0].update(type="equals", default=None)
    assert len(prepare_chart_rows(_line(), spec, _datasets())[0]) == 4

    spec["filters"][0].update(
        column="month",
        type="date_range",
        default={"from": "2025-02-01", "to": "2025-03-31T23:59:59Z"},
    )
    rows, _ = prepare_chart_rows(_line(), spec, _datasets())
    assert [row["month"] for row in rows] == ["2025-02-01", "2025-03-01"]

    spec["filters"][0].update(
        column="revenue", type="number_range", default={"min": 15}
    )
    rows, _ = prepare_chart_rows(_line(), spec, _datasets())
    # The null revenue row is dropped because a bound is given.
    assert [row["revenue"] for row in rows] == [30, 20]

    spec["filters"][0].update(default={})
    assert len(prepare_chart_rows(_line(), spec, _datasets())[0]) == 4


def test_filters_bound_to_another_dataset_are_ignored():
    spec = _spec(
        datasets={
            "monthly": {"connection": "w", "sql": "select 1"},
            "o": {"rows": []},
        },
        filters=[
            {
                "id": "r",
                "label": "R",
                "dataset": "o",
                "column": "region",
                "type": "equals",
                "default": "east",
            }
        ],
    )
    rows, issues = prepare_chart_rows(_line(), spec, _datasets())
    assert len(rows) == 4
    assert issues == []


def test_sort_is_stable_numeric_and_nulls_last():
    chart = _line(sort={"column": "revenue", "direction": "desc"})
    rows, _ = prepare_chart_rows(chart, _spec(), _datasets())
    assert [row["revenue"] for row in rows] == [30, 20, 10, None]

    chart = _line(sort={"column": "revenue"})
    rows, _ = prepare_chart_rows(chart, _spec(), _datasets())
    assert [row["revenue"] for row in rows] == [10, 20, 30, None]

    mixed = [
        {"k": "10", "n": 1},
        {"k": "9", "n": 2},
        {"k": "b", "n": 3},
        {"k": "a", "n": 4},
        {"k": None, "n": 5},
    ]
    chart = _line(sort={"column": "k"})
    rows, _ = prepare_chart_rows(chart, _spec(), _datasets(mixed))
    # "10" and "9" compare numerically, others as strings; nulls last.
    ordered = [row["k"] for row in rows]
    assert ordered[-1] is None
    assert ordered.index("9") < ordered.index("10")
    assert ordered.index("a") < ordered.index("b")


def test_limit_applies_after_sort():
    chart = _line(sort={"column": "revenue", "direction": "desc"}, limit=2)
    rows, issues = prepare_chart_rows(chart, _spec(), _datasets())
    assert [row["revenue"] for row in rows] == [30, 20]
    assert issues == []


def test_missing_dataset_fails_the_chart():
    chart = _line(dataset="nope")
    rows, issues = prepare_chart_rows(chart, _spec(), _datasets())
    assert rows == []
    assert _codes(issues) == ["missing_dataset"]
    assert "'nope'" in issues[0]["message"]
    assert "'rev'" in issues[0]["message"]
    assert chart_is_failed(issues)


def test_dataset_unreadable_fails_the_chart():
    datasets = {
        "monthly": LoadedDataset(
            error="Dataset snapshot could not be parsed: artifacts/datasets/m.csv",
            resolved_file="artifacts/datasets/m.csv",
            code="dataset_unreadable",
        )
    }
    rows, issues = prepare_chart_rows(_line(), _spec(), datasets)
    assert rows == []
    assert _codes(issues) == ["dataset_unreadable"]
    assert "artifacts/datasets/m.csv" in issues[0]["message"]
    assert "'rev'" in issues[0]["message"]
    assert chart_is_failed(issues)

    not_loaded, issues = prepare_chart_rows(_line(), _spec(), {})
    assert not_loaded == []
    assert _codes(issues) == ["dataset_unreadable"]


@pytest.mark.parametrize("code", ["snapshot_missing", "snapshot_stale"])
def test_snapshot_codes_fail_the_chart_and_keep_the_loader_message(code: str):
    datasets = {
        "monthly": LoadedDataset(
            error="Dataset 'monthly' has no snapshot. Call sp.dashboard_dataset.",
            resolved_file="artifacts/datasets/monthly.csv",
            code=code,
        )
    }
    rows, issues = prepare_chart_rows(_line(), _spec(), datasets)
    assert rows == []
    assert _codes(issues) == [code]
    assert issues[0]["message"] == (
        "Chart 'rev': Dataset 'monthly' has no snapshot. Call "
        "sp.dashboard_dataset."
    )
    assert chart_is_failed(issues)


def test_empty_dataset_before_and_after_preparation():
    _, issues = prepare_chart_rows(_line(), _spec(), _datasets([]))
    assert _codes(issues) == ["empty_dataset"]
    assert not chart_is_failed(issues)

    spec = _spec(
        filters=[
            {
                "id": "r",
                "label": "R",
                "dataset": "monthly",
                "column": "region",
                "type": "equals",
                "default": "south",
            }
        ]
    )
    rows, issues = prepare_chart_rows(_line(), spec, _datasets())
    assert rows == []
    assert _codes(issues) == ["empty_dataset"]


def test_missing_column_lists_available_columns():
    spec = _spec(
        filters=[
            {
                "id": "f",
                "label": "F",
                "dataset": "monthly",
                "column": "segment",
                "type": "equals",
            }
        ]
    )
    chart = _line(
        y=[{"column": "revenue"}, {"column": "margin"}],
        sort={"column": "orders"},
    )
    _, issues = prepare_chart_rows(chart, spec, _datasets())
    missing = [issue for issue in issues if issue["code"] == "missing_column"]
    names = {issue["message"].split("'")[3] for issue in missing}
    assert names == {"margin", "orders", "segment"}
    assert "Columns: month, region, revenue." in missing[0]["message"]
    assert chart_is_failed(issues)


def test_missing_column_covers_every_chart_type():
    kpi = {
        "id": "k",
        "type": "kpi",
        "title": "K",
        "dataset": "monthly",
        "value": {"column": "total"},
        "comparison": {"column": "prev"},
    }
    _, issues = prepare_chart_rows(kpi, _spec(), _datasets())
    assert _codes(issues) == ["missing_column", "missing_column"]

    table = {
        "id": "t",
        "type": "table",
        "title": "T",
        "dataset": "monthly",
        "columns": [{"column": "region"}, {"column": "zip"}],
    }
    _, issues = prepare_chart_rows(table, _spec(), _datasets())
    assert _codes(issues) == ["missing_column"]

    pie = {
        "id": "p",
        "type": "pie",
        "title": "P",
        "dataset": "monthly",
        "label": "country",
        "value": {"column": "revenue"},
    }
    _, issues = prepare_chart_rows(pie, _spec(), _datasets())
    assert _codes(issues) == ["missing_column"]

    scatter = {
        "id": "s",
        "type": "scatter",
        "title": "S",
        "dataset": "monthly",
        "x": {"column": "revenue", "type": "number"},
        "y": {"column": "revenue"},
        "size": "customers",
        "color": "tier",
    }
    _, issues = prepare_chart_rows(scatter, _spec(), _datasets())
    assert _codes(issues) == ["missing_column", "missing_column"]

    bar = _line(type="bar", series={"column": "channel"})
    _, issues = prepare_chart_rows(bar, _spec(), _datasets())
    assert _codes(issues) == ["missing_column"]


def test_non_numeric_y_is_a_warning():
    rows = [
        {"month": "2025-01-01", "revenue": "ten"},
        {"month": "2025-02-01", "revenue": "20"},
        {"month": "2025-03-01", "revenue": None},
    ]
    prepared, issues = prepare_chart_rows(_line(), _spec(), _datasets(rows))
    assert len(prepared) == 3
    assert _codes(issues) == ["non_numeric_y"]
    assert "'revenue'" in issues[0]["message"]
    assert not chart_is_failed(issues)

    kpi = {
        "id": "k",
        "type": "kpi",
        "title": "K",
        "dataset": "monthly",
        "value": {"column": "region"},
    }
    _, issues = prepare_chart_rows(kpi, _spec(), _datasets())
    assert _codes(issues) == ["non_numeric_y"]


def test_unparseable_date_is_a_warning_only_for_date_axes():
    rows = [
        {"month": "Jan 2025", "revenue": 1},
        {"month": "Feb 2025", "revenue": 2},
        {"month": "2025-03-01", "revenue": 3},
    ]
    _, issues = prepare_chart_rows(_line(), _spec(), _datasets(rows))
    assert _codes(issues) == ["unparseable_date"]
    assert "'month'" in issues[0]["message"]

    chart = _line(x={"column": "month", "type": "category"})
    _, issues = prepare_chart_rows(chart, _spec(), _datasets(rows))
    assert issues == []


def test_too_many_rows_caps_at_fifty_thousand():
    rows = [{"month": "2025-01-01", "revenue": i} for i in range(50_010)]
    prepared, issues = prepare_chart_rows(_line(), _spec(), _datasets(rows))
    assert len(prepared) == 50_000
    assert _codes(issues) == ["too_many_rows"]
    assert not chart_is_failed(issues)


def test_series_with_multi_y_fails_the_chart():
    chart = _line(
        type="bar",
        y=[{"column": "revenue"}, {"column": "revenue"}],
        series={"column": "region"},
    )
    _, issues = prepare_chart_rows(chart, _spec(), _datasets())
    assert _codes(issues) == ["series_with_multi_y"]
    assert chart_is_failed(issues)


def test_infer_column_types():
    rows = [
        {"d": "2025-01-01", "n": 1, "s": "a", "b": True, "z": None, "f": "2"},
        {"d": "2025-02-01T10:00:00Z", "n": 2.5, "s": 1, "b": False, "z": None},
    ]
    assert infer_column_types(rows) == [
        {"name": "d", "inferred_type": "date"},
        {"name": "n", "inferred_type": "number"},
        {"name": "s", "inferred_type": "string"},
        {"name": "b", "inferred_type": "boolean"},
        {"name": "z", "inferred_type": "null"},
        {"name": "f", "inferred_type": "number"},
    ]
