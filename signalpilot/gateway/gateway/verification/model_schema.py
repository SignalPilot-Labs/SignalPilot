"""Structured model/output column comparison below presentation adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnComparison:
    expected: list[str]
    actual: list[str]
    matching: list[str]
    missing: list[str]
    extra: list[str]
    case_mismatches: list[str]

    @property
    def valid(self) -> bool:
        return not self.missing and not self.case_mismatches


def compare_columns(expected: list[str], actual: list[str]) -> ColumnComparison:
    expected_lower = {column.lower(): column for column in expected}
    actual_lower = {column.lower(): column for column in actual}
    return ColumnComparison(
        expected=expected,
        actual=actual,
        matching=[column for column in expected if column in actual],
        missing=[column for column in expected if column not in actual],
        extra=[column for column in actual if column not in expected],
        case_mismatches=[
            f"{expected_lower[key]} (expected) vs {actual_lower[key]} (actual)"
            for key in expected_lower
            if key in actual_lower and expected_lower[key] != actual_lower[key]
        ],
    )
