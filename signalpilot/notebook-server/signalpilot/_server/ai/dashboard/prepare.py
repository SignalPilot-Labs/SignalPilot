"""Row preparation and chart checks for dashboard files.

This mirrors the web renderer's ``prepare.ts`` step for step. The renderer
never aggregates: it applies the filters bound to the chart's dataset (using
each filter's ``default``), then the chart's ``sort``, then ``limit``, then a
hard cap of 50 000 rows.

Issue codes: ``missing_dataset``, ``dataset_unreadable``, ``empty_dataset``,
``missing_column``, ``non_numeric_y``, ``unparseable_date``,
``too_many_rows``, ``series_with_multi_y``. The first, second, fourth, and
last make the chart ``failed``; the rest are warnings.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from functools import cmp_to_key
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from signalpilot._server.ai.dashboard.datasets import LoadedDataset, Row

Issue = dict[str, str]

ROW_CAP = 50_000
COLUMN_SAMPLE_ROWS = 50
PARSE_THRESHOLD = 0.9
FAILED_CODES = frozenset(
    {
        "missing_dataset",
        "dataset_unreadable",
        "missing_column",
        "series_with_multi_y",
    }
)
CARTESIAN_TYPES = frozenset({"bar", "line", "area"})
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ].*)?$")


def js_string(value: Any) -> str:
    """String(value) with JavaScript conventions for null, bool, and floats."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def parse_number(value: Any) -> float | None:
    """Return the numeric value or None when the value is not a number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
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
    """Parse YYYY-MM-DD or a full ISO datetime; naive UTC for comparisons."""
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
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def chart_is_failed(issues: Iterable[Issue]) -> bool:
    return any(issue.get("code") in FAILED_CODES for issue in issues)


def available_columns(rows: list[Row]) -> list[str]:
    """Union of keys across the first 50 rows, in first-seen order."""
    seen: dict[str, None] = {}
    for row in rows[:COLUMN_SAMPLE_ROWS]:
        for key in row:
            seen.setdefault(str(key), None)
    return list(seen)


def referenced_columns(
    chart: dict[str, Any], spec: dict[str, Any]
) -> list[str]:
    """Every column a chart and its bound filters reference, deduplicated."""
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
        if isinstance(filter_def, dict) and filter_def.get(
            "dataset"
        ) == chart.get("dataset"):
            add(filter_def)
    return names


def y_columns(chart: dict[str, Any]) -> list[str]:
    """Columns that must be numeric for this chart type."""
    chart_type = chart.get("type")
    if chart_type in CARTESIAN_TYPES:
        return [
            str(item.get("column"))
            for item in chart.get("y") or []
            if isinstance(item, dict) and item.get("column")
        ]
    if chart_type in {"scatter", "pie", "kpi"}:
        target = (
            chart.get("y") if chart_type == "scatter" else chart.get("value")
        )
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


def apply_filters(
    rows: list[Row], chart: dict[str, Any], spec: dict[str, Any]
) -> list[Row]:
    bound = [
        filter_def
        for filter_def in spec.get("filters") or []
        if isinstance(filter_def, dict)
        and filter_def.get("dataset") == chart.get("dataset")
    ]
    if not bound:
        return list(rows)
    return [
        row
        for row in rows
        if all(_filter_keeps(row, filter_def) for filter_def in bound)
    ]


def _compare(left: Any, right: Any) -> int:
    left_number = parse_number(left)
    right_number = parse_number(right)
    if left_number is not None and right_number is not None:
        return (left_number > right_number) - (left_number < right_number)
    left_text = js_string(left)
    right_text = js_string(right)
    return (left_text > right_text) - (left_text < right_text)


def apply_sort(rows: list[Row], sort: Any) -> list[Row]:
    """Stable sort by column; numeric when both numeric; nulls last."""
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
    datasets: Mapping[str, LoadedDataset],
) -> tuple[list[Row], list[Issue]]:
    """Prepare rows for one chart and run every check.

    Returns the prepared rows and the issue list. The caller decides what to
    do with a failed chart (``chart_is_failed``).
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
                    f"Chart '{chart_id}' uses dataset '{dataset_name}', which "
                    f"is not in spec.datasets. Datasets: "
                    f"{', '.join(sorted(definitions)) or 'none'}."
                ),
            }
        )
        return [], issues
    loaded = datasets.get(dataset_name)
    if loaded is None or loaded.error:
        detail = loaded.error if loaded is not None else "not loaded"
        issues.append(
            {
                "code": "dataset_unreadable",
                "message": (
                    f"Chart '{chart_id}' dataset '{dataset_name}' is "
                    f"unreadable: {detail}"
                ),
            }
        )
        return [], issues
    raw_rows = loaded.rows
    if not raw_rows:
        issues.append(
            {
                "code": "empty_dataset",
                "message": (
                    f"Chart '{chart_id}' dataset '{dataset_name}' has no rows."
                ),
            }
        )
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
                        f"Chart '{chart_id}': column '{name}' is not in "
                        f"dataset '{dataset_name}'. Columns: "
                        f"{', '.join(columns)}."
                    ),
                }
            )
    if (
        chart.get("type") in CARTESIAN_TYPES
        and isinstance(chart.get("series"), dict)
        and len(chart.get("y") or []) > 1
    ):
        issues.append(
            {
                "code": "series_with_multi_y",
                "message": (
                    f"Chart '{chart_id}' has 'series' "
                    f"({chart['series'].get('column')}) and more than one y "
                    "column. Use one y column with series, or several y "
                    "columns without series."
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
                    f"Chart '{chart_id}' has {len(rows)} rows after "
                    f"preparation; only the first {ROW_CAP} are used. Add a "
                    "limit or aggregate the dataset."
                ),
            }
        )
        rows = rows[:ROW_CAP]
    if not rows:
        issues.append(
            {
                "code": "empty_dataset",
                "message": (
                    f"Chart '{chart_id}' has zero rows after filters, sort, "
                    "and limit."
                ),
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
                        f"Chart '{chart_id}': column '{name}' has only "
                        f"{ratio:.0%} numeric values. A y or value column "
                        "must be numeric."
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
                            f"Chart '{chart_id}': x column '{name}' has only "
                            f"{ratio:.0%} ISO dates (YYYY-MM-DD). Write dates "
                            "in ISO format or set x.type to 'category'."
                        ),
                    }
                )
    return rows, issues


def infer_column_types(rows: list[Row]) -> list[dict[str, str]]:
    """Infer one type per column from the first 50 rows.

    Types: ``number``, ``date``, ``string``, ``boolean``, ``null``.
    """
    inferred: list[dict[str, str]] = []
    sample = rows[:COLUMN_SAMPLE_ROWS]
    for name in available_columns(rows):
        values = [row.get(name) for row in sample if row.get(name) is not None]
        if not values:
            kind = "null"
        elif all(isinstance(value, bool) for value in values):
            kind = "boolean"
        elif all(parse_number(value) is not None for value in values):
            kind = "number"
        elif all(parse_iso_date(value) is not None for value in values):
            kind = "date"
        else:
            kind = "string"
        inferred.append({"name": name, "inferred_type": kind})
    return inferred
