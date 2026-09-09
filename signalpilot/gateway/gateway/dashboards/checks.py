"""Chart checks for a dashboard spec against loaded datasets.

A port of the notebook-server ``_server/ai/dashboard/prepare.py`` rules. The
two services do not import each other; keep the rules identical by hand.

Issue codes: ``missing_dataset``, ``dataset_unreadable``, ``empty_dataset``,
``missing_column``, ``non_numeric_y``, ``unparseable_date``,
``too_many_rows``, ``series_with_multi_y``. The first, second, fourth, and
last make the chart ``failed``; the rest are warnings.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cmp_to_key
from typing import Any

Row = dict[str, Any]
Issue = dict[str, str]

ROW_CAP = 50_000
COLUMN_SAMPLE_ROWS = 50
PARSE_THRESHOLD = 0.9
FAILED_CODES = frozenset({"missing_dataset", "dataset_unreadable", "missing_column", "series_with_multi_y"})
CARTESIAN_TYPES = frozenset({"bar", "line", "area"})
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ].*)?$")


def js_string(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def parse_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def parse_iso_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and _ISO_DATE_RE.match(value.strip()):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def chart_is_failed(issues: Iterable[Issue]) -> bool:
    return any(issue.get("code") in FAILED_CODES for issue in issues)


def available_columns(rows: list[Row]) -> list[str]:
    seen: dict[str, None] = {}
    for row in rows[:COLUMN_SAMPLE_ROWS]:
        for key in row:
            seen.setdefault(str(key), None)
    return list(seen)


def referenced_columns(chart: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    names: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, dict):
            value = value.get("column")
        if isinstance(value, str) and value and value not in names:
            names.append(value)

    add(chart.get("x"))
    y_value = chart.get("y")
    if isinstance(y_value, list):
        for item in y_value:
            add(item)
    else:
        add(y_value)
    add(chart.get("value"))
    add(chart.get("comparison"))
    for item in chart.get("columns") or []:
        add(item)
    add(chart.get("label"))
    add(chart.get("size"))
    add(chart.get("color"))
    add(chart.get("series"))
    add(chart.get("sort"))
    for filter_def in spec.get("filters") or []:
        if isinstance(filter_def, dict) and filter_def.get("dataset") == chart.get("dataset"):
            add(filter_def)
    return names


def referenced_columns_by_dataset(spec: dict[str, Any]) -> dict[str, list[str]]:
    """{dataset name: columns} that charts and filters reference, in first-seen order."""
    columns: dict[str, list[str]] = {}
    for chart in spec.get("charts") or []:
        if not isinstance(chart, dict) or not chart.get("dataset"):
            continue
        names = columns.setdefault(str(chart["dataset"]), [])
        names.extend(name for name in referenced_columns(chart, spec) if name not in names)
    for filter_def in spec.get("filters") or []:
        # An unbound filter (no dataset) applies wherever its column exists;
        # it is never a required column.
        if not isinstance(filter_def, dict) or not filter_def.get("dataset"):
            continue
        column = filter_def.get("column")
        names = columns.setdefault(str(filter_def["dataset"]), [])
        if isinstance(column, str) and column and column not in names:
            names.append(column)
    return columns


def y_columns(chart: dict[str, Any]) -> list[str]:
    chart_type = chart.get("type")
    if chart_type in CARTESIAN_TYPES:
        return [str(item.get("column")) for item in chart.get("y") or [] if isinstance(item, dict) and item.get("column")]
    if chart_type in {"scatter", "pie", "kpi"}:
        target = chart.get("y") if chart_type == "scatter" else chart.get("value")
        if isinstance(target, dict) and target.get("column"):
            return [str(target["column"])]
    return []


def _filter_keeps(row: Row, filter_def: dict[str, Any]) -> bool:
    column = str(filter_def.get("column") or "")
    kind = filter_def.get("type")
    default = filter_def.get("default")
    value = row.get(column)
    if kind == "equals":
        if default is None:
            return True
        return js_string(value) == js_string(default)
    if kind == "in":
        if not isinstance(default, list) or not default:
            return True
        return js_string(value) in {js_string(item) for item in default}
    if kind == "date_range":
        bounds = default if isinstance(default, dict) else {}
        low = parse_iso_date(bounds.get("from"))
        high = parse_iso_date(bounds.get("to"))
        if low is None and high is None:
            return True
        parsed = parse_iso_date(value)
        if parsed is None:
            return False
        if low is not None and parsed < low:
            return False
        return not (high is not None and parsed > high)
    if kind == "number_range":
        bounds = default if isinstance(default, dict) else {}
        low = parse_number(bounds.get("min"))
        high = parse_number(bounds.get("max"))
        if low is None and high is None:
            return True
        number = parse_number(value)
        if number is None:
            return False
        if low is not None and number < low:
            return False
        return not (high is not None and number > high)
    return True


def apply_filters(rows: list[Row], chart: dict[str, Any], spec: dict[str, Any]) -> list[Row]:
    bound = [
        filter_def
        for filter_def in spec.get("filters") or []
        if isinstance(filter_def, dict) and filter_def.get("dataset") == chart.get("dataset")
    ]
    if not bound:
        return list(rows)
    return [row for row in rows if all(_filter_keeps(row, filter_def) for filter_def in bound)]


def _compare(left: Any, right: Any) -> int:
    left_number = parse_number(left)
    right_number = parse_number(right)
    if left_number is not None and right_number is not None:
        return (left_number > right_number) - (left_number < right_number)
    left_text = js_string(left)
    right_text = js_string(right)
    return (left_text > right_text) - (left_text < right_text)


def apply_sort(rows: list[Row], sort: Any) -> list[Row]:
    if not isinstance(sort, dict) or not sort.get("column"):
        return list(rows)
    column = str(sort["column"])
    descending = sort.get("direction") == "desc"
    present = [row for row in rows if row.get(column) is not None]
    missing = [row for row in rows if row.get(column) is None]
    ordered = sorted(
        present,
        key=cmp_to_key(lambda a, b: _compare(a.get(column), b.get(column))),
        reverse=descending,
    )
    return ordered + missing


def _ratio(values: list[Any], parser: Any) -> float | None:
    non_null = [value for value in values if value is not None]
    if not non_null:
        return None
    parsed = sum(1 for value in non_null if parser(value) is not None)
    return parsed / len(non_null)


def prepare_chart_rows(
    chart: dict[str, Any],
    spec: dict[str, Any],
    datasets: Mapping[str, list[Row] | None],
) -> tuple[list[Row], list[Issue]]:
    """Prepare rows for one chart and run every check.

    ``datasets`` maps a dataset name to its rows, or to None when the file
    could not be read.
    """
    chart_id = str(chart.get("id") or "?")
    dataset_name = str(chart.get("dataset") or "")
    issues: list[Issue] = []
    definitions = spec.get("datasets")
    definitions = definitions if isinstance(definitions, dict) else {}
    if dataset_name not in definitions:
        issues.append(
            {
                "code": "missing_dataset",
                "message": (
                    f"Chart '{chart_id}' uses dataset '{dataset_name}', which is not in spec.datasets. "
                    f"Datasets: {', '.join(sorted(definitions)) or 'none'}."
                ),
            }
        )
        return [], issues
    raw_rows = datasets.get(dataset_name)
    if raw_rows is None:
        issues.append(
            {
                "code": "dataset_unreadable",
                "message": f"Chart '{chart_id}' dataset '{dataset_name}' is unreadable.",
            }
        )
        return [], issues
    if not raw_rows:
        issues.append({"code": "empty_dataset", "message": f"Chart '{chart_id}' dataset '{dataset_name}' has no rows."})
        return [], issues

    columns = available_columns(raw_rows)
    column_set = set(columns)
    missing: set[str] = set()
    for name in referenced_columns(chart, spec):
        if name not in column_set:
            missing.add(name)
            issues.append(
                {
                    "code": "missing_column",
                    "message": (
                        f"Chart '{chart_id}': column '{name}' is not in dataset '{dataset_name}'. "
                        f"Columns: {', '.join(columns)}."
                    ),
                }
            )
    if chart.get("type") in CARTESIAN_TYPES and isinstance(chart.get("series"), dict) and len(chart.get("y") or []) > 1:
        issues.append(
            {
                "code": "series_with_multi_y",
                "message": (
                    f"Chart '{chart_id}' has 'series' ({chart['series'].get('column')}) and more than one y "
                    "column. Use one y column with series, or several y columns without series."
                ),
            }
        )

    rows = apply_filters(raw_rows, chart, spec)
    rows = apply_sort(rows, chart.get("sort"))
    limit = chart.get("limit")
    if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
        rows = rows[:limit]
    if len(rows) > ROW_CAP:
        issues.append(
            {
                "code": "too_many_rows",
                "message": (
                    f"Chart '{chart_id}' has {len(rows)} rows after preparation; only the first {ROW_CAP} are "
                    "used. Add a limit or aggregate the dataset."
                ),
            }
        )
        rows = rows[:ROW_CAP]
    if not rows:
        issues.append(
            {
                "code": "empty_dataset",
                "message": f"Chart '{chart_id}' has zero rows after filters, sort, and limit.",
            }
        )
        return rows, issues

    for name in y_columns(chart):
        if name in missing:
            continue
        ratio = _ratio([row.get(name) for row in rows], parse_number)
        if ratio is not None and ratio < PARSE_THRESHOLD:
            issues.append(
                {
                    "code": "non_numeric_y",
                    "message": (
                        f"Chart '{chart_id}': column '{name}' has only {ratio:.0%} numeric values. "
                        "A y or value column must be numeric."
                    ),
                }
            )
    x_axis = chart.get("x")
    if isinstance(x_axis, dict) and x_axis.get("type") == "date":
        name = str(x_axis.get("column") or "")
        if name and name not in missing:
            ratio = _ratio([row.get(name) for row in rows], parse_iso_date)
            if ratio is not None and ratio < PARSE_THRESHOLD:
                issues.append(
                    {
                        "code": "unparseable_date",
                        "message": (
                            f"Chart '{chart_id}': x column '{name}' has only {ratio:.0%} ISO dates "
                            "(YYYY-MM-DD). Write dates in ISO format or set x.type to 'category'."
                        ),
                    }
                )
    return rows, issues


# ── Whole-spec evaluation ───────────────────────────────────────────────────


@dataclass
class ChartCheck:
    id: str
    dataset: str
    failed: bool
    issues: list[Issue] = field(default_factory=list)


@dataclass
class SpecCheck:
    charts: list[ChartCheck] = field(default_factory=list)

    @property
    def failed_charts(self) -> list[ChartCheck]:
        return [chart for chart in self.charts if chart.failed]

    @property
    def ok(self) -> bool:
        return not self.failed_charts

    def failure_messages(self, *, except_datasets: Iterable[str] = ()) -> list[str]:
        """Messages of failing checks, skipping charts bound to the named datasets."""
        skipped = set(except_datasets)
        return [
            issue["message"]
            for chart in self.failed_charts
            if chart.dataset not in skipped
            for issue in chart.issues
            if issue["code"] in FAILED_CODES
        ]

    def as_detail(self) -> list[dict[str, Any]]:
        return [{"id": chart.id, "failed": chart.failed, "issues": chart.issues} for chart in self.charts]


def check_spec(spec: dict[str, Any], datasets: Mapping[str, list[Row] | None]) -> SpecCheck:
    """Run the chart checks for every chart. Never raises."""
    result = SpecCheck()
    for chart in spec.get("charts") or []:
        if not isinstance(chart, dict):
            continue
        _rows, issues = prepare_chart_rows(chart, spec, datasets)
        result.charts.append(
            ChartCheck(
                id=str(chart.get("id") or "?"),
                dataset=str(chart.get("dataset") or ""),
                failed=chart_is_failed(issues),
                issues=issues,
            )
        )
    return result
