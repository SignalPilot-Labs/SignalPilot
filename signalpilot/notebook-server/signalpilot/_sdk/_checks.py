"""Compact in-kernel data quality checks for governed runtime analyses."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any


def _records(frame: Any) -> list[dict[str, Any]]:
    if isinstance(frame, list):
        rows = frame
    elif hasattr(frame, "to_dicts"):
        rows = frame.to_dicts()
    elif hasattr(frame, "to_dict"):
        rows = frame.to_dict(orient="records")
    else:
        raise TypeError("Check expects a pandas or Polars DataFrame")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise TypeError("Check expects record-shaped rows")
    return rows


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class RuntimeChecks:
    def nulls(self, frame: Any) -> dict[str, Any]:
        rows = _records(frame)
        columns = sorted({str(column) for row in rows for column in row})
        counts = {column: sum(row.get(column) is None for row in rows) for column in columns}
        return {"row_count": len(rows), "null_counts": counts, "passed": not any(counts.values())}

    def duplicates(self, frame: Any, *, columns: list[str] | None = None) -> dict[str, Any]:
        rows = _records(frame)
        selected = columns or sorted({str(column) for row in rows for column in row})
        seen: set[str] = set()
        duplicate_count = 0
        for row in rows:
            key = json.dumps([row.get(column) for column in selected], default=str, sort_keys=True)
            if key in seen:
                duplicate_count += 1
            else:
                seen.add(key)
        return {
            "row_count": len(rows),
            "columns": selected,
            "duplicate_count": duplicate_count,
            "passed": duplicate_count == 0,
        }

    def date_range(self, frame: Any, *, column: str) -> dict[str, Any]:
        rows = _records(frame)
        values = [_parse_datetime(row.get(column)) for row in rows]
        present = [value for value in values if value is not None]
        return {
            "column": column,
            "minimum": min(present).isoformat() if present else None,
            "maximum": max(present).isoformat() if present else None,
            "missing_or_invalid_count": len(values) - len(present),
            "passed": bool(present),
        }

    def freshness(
        self,
        frame: Any,
        *,
        column: str,
        maximum_age_seconds: float,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        date_range = self.date_range(frame, column=column)
        latest = _parse_datetime(date_range["maximum"])
        reference = now or datetime.now(UTC)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=UTC)
        age_seconds = (reference - latest).total_seconds() if latest else None
        return {
            **date_range,
            "age_seconds": age_seconds,
            "maximum_age_seconds": maximum_age_seconds,
            "passed": age_seconds is not None and 0 <= age_seconds <= maximum_age_seconds,
        }

    def reconciliation(
        self,
        *,
        actual: float,
        expected: float,
        tolerance: float = 0.0,
    ) -> dict[str, Any]:
        absolute_difference = abs(float(actual) - float(expected))
        return {
            "actual": actual,
            "expected": expected,
            "absolute_difference": absolute_difference,
            "tolerance": tolerance,
            "passed": absolute_difference <= tolerance,
        }


checks = RuntimeChecks()
