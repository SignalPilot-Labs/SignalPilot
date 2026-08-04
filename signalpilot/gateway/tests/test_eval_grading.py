"""Verify grading in gateway/evals/grading.py.

``grade_checks`` evaluates the numeric extraction matrix. ``grade_model_rebuilt``
grades a write task on its assigned branch through a caller-supplied QueryFn.
The tests use a scripted QueryFn test double.
"""

from __future__ import annotations

import pytest

from gateway.evals.grading import (
    extract_numbers,
    grade_checks,
    grade_model_rebuilt,
    quote_table,
)


def _check(value: float, tolerance: float = 0.15, name: str = "answer") -> dict:
    return {"name": name, "value": value, "tolerance": tolerance}


class TestExtractNumbers:
    def test_plain_and_formatted(self) -> None:
        assert extract_numbers("There are 1,234 orders totalling $56.7") == [1234.0, 56.7]

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("$1.2b", 1.2e9),
            ("revenue was 1.2 billion dollars", 1.2e9),
            ("$3.4m in refunds", 3.4e6),
            ("about 2 million", 2e6),
            ("500k rows", 500_000.0),
            ("9 thousand", 9000.0),
        ],
    )
    def test_magnitude_suffixes(self, text: str, expected: float) -> None:
        assert expected in extract_numbers(text)

    def test_no_numbers(self) -> None:
        assert extract_numbers("the fan-out is the bug") == []


class TestGradeChecks:
    def test_correct_within_tolerance(self) -> None:
        verdict, results = grade_checks([_check(100)], "I found about 110 orders")
        assert verdict == "CORRECT"
        assert results[0]["passed"] is True

    def test_correct_via_suffix(self) -> None:
        verdict, _ = grade_checks([_check(1.2e9, 0.05)], "revenue is $1.2b")
        assert verdict == "CORRECT"

    def test_off_when_outside_tolerance(self) -> None:
        verdict, results = grade_checks([_check(100, 0.15)], "the answer is 200")
        assert verdict == "OFF"
        assert results[0]["passed"] is False

    def test_partial_when_some_checks_pass(self) -> None:
        verdict, results = grade_checks(
            [_check(100, name="a"), _check(9999, name="b")], "100 orders and 42 refunds"
        )
        assert verdict == "PARTIAL"
        assert [r["passed"] for r in results] == [True, False]

    def test_unknown_when_the_answer_has_no_numbers(self) -> None:
        verdict, results = grade_checks([_check(100)], "I could not determine this")
        assert verdict == "UNKNOWN"
        assert results and results[0]["passed"] is False

    def test_ungraded_without_checks(self) -> None:
        assert grade_checks([], "whatever") == ("UNGRADED", [])

    def test_zero_target_requires_a_near_zero_number(self) -> None:
        assert grade_checks([_check(0)], "the count is 0")[0] == "CORRECT"
        assert grade_checks([_check(0)], "the count is 5")[0] == "OFF"


class TestQuoteTable:
    @pytest.mark.parametrize(
        "name,quoted",
        [
            ("orders", '"orders"'),
            ("marts.fct_orders", '"marts"."fct_orders"'),
            ("db.marts.fct_orders", '"db"."marts"."fct_orders"'),
        ],
    )
    def test_valid_names_are_quoted(self, name: str, quoted: str) -> None:
        assert quote_table(name) == quoted

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "1orders",
            "a.b.c.d",
            "orders; drop table x",
            'x"y',
            "sp ace",
            "a..b",
            "marts.fct-orders",
        ],
    )
    def test_everything_else_is_refused(self, bad: str) -> None:
        with pytest.raises(ValueError, match="invalid table identifier"):
            quote_table(bad)


class _FakeWarehouse:
    """A scripted QueryFn: dispatches on the SQL grade_model_rebuilt emits."""

    def __init__(
        self,
        *,
        exists: bool = True,
        row_count: int = 100,
        grain_dupes: int = 0,
        columns: list[str] | None = None,
        boom: bool = False,
    ) -> None:
        self.exists = exists
        self.row_count = row_count
        self.grain_dupes = grain_dupes
        self.columns = columns if columns is not None else ["order_id", "amount"]
        self.boom = boom
        self.queries: list[str] = []

    async def query(self, sql: str) -> list[tuple]:
        self.queries.append(sql)
        if self.boom:
            raise RuntimeError("connection reset by warehouse")
        if "information_schema.tables" in sql:
            return [(1,)] if self.exists else []
        if "information_schema.columns" in sql:
            return [(c,) for c in self.columns]
        if "row_number()" in sql:
            return [(self.grain_dupes,)]
        if sql.startswith("SELECT count(*)"):
            return [(self.row_count,)]
        raise AssertionError(f"unexpected SQL: {sql}")


def _grade(**expect) -> dict:
    return {"kind": "model_rebuilt", "model": "marts.fct_orders", "expect": expect}


def _by_name(results: list[dict]) -> dict[str, dict]:
    return {r["name"]: r for r in results}


class TestGradeModelRebuilt:
    async def test_everything_passing_is_correct(self) -> None:
        wh = _FakeWarehouse()
        verdict, results = await grade_model_rebuilt(
            _grade(row_count=100, grain=["order_id"], columns=["order_id", "amount"]),
            wh.query,
        )
        assert verdict == "CORRECT"
        checks = _by_name(results)
        assert set(checks) == {"exists", "row_count", "grain", "columns"}
        assert all(r["passed"] for r in results)

    async def test_missing_table_is_off_and_stops(self) -> None:
        wh = _FakeWarehouse(exists=False)
        verdict, results = await grade_model_rebuilt(_grade(row_count=100), wh.query)
        assert verdict == "OFF"
        assert results == [{"name": "exists", "passed": False, "detail": "marts.fct_orders not found"}]
        # Nothing else was queried once existence failed.
        assert len(wh.queries) == 1

    async def test_row_count_outside_tolerance_is_off(self) -> None:
        wh = _FakeWarehouse(row_count=150)
        verdict, results = await grade_model_rebuilt(_grade(row_count=100), wh.query)
        assert verdict == "OFF"
        assert _by_name(results)["row_count"]["passed"] is False

    async def test_row_count_tolerance_is_honoured(self) -> None:
        wh = _FakeWarehouse(row_count=104)
        verdict, _ = await grade_model_rebuilt(
            _grade(row_count=100, row_count_tolerance=0.05), wh.query
        )
        assert verdict == "CORRECT"

    async def test_duplicate_grain_is_off(self) -> None:
        wh = _FakeWarehouse(grain_dupes=7)
        verdict, results = await grade_model_rebuilt(_grade(grain=["order_id"]), wh.query)
        assert verdict == "OFF"
        grain = _by_name(results)["grain"]
        assert grain["passed"] is False
        assert "7 duplicate rows" in grain["detail"]

    async def test_missing_column_is_off(self) -> None:
        wh = _FakeWarehouse(columns=["order_id"])
        verdict, results = await grade_model_rebuilt(
            _grade(columns=["order_id", "amount"]), wh.query
        )
        assert verdict == "OFF"
        cols = _by_name(results)["columns"]
        assert cols["passed"] is False
        assert "amount" in cols["detail"]

    async def test_column_match_is_case_insensitive(self) -> None:
        wh = _FakeWarehouse(columns=["ORDER_ID"])
        verdict, _ = await grade_model_rebuilt(_grade(columns=["order_id"]), wh.query)
        assert verdict == "CORRECT"

    async def test_query_error_is_error_not_off(self) -> None:
        wh = _FakeWarehouse(boom=True)
        verdict, results = await grade_model_rebuilt(_grade(row_count=100), wh.query)
        assert verdict == "ERROR"
        assert _by_name(results)["query"]["passed"] is False

    async def test_bad_model_identifier_is_error_without_querying(self) -> None:
        wh = _FakeWarehouse()
        verdict, results = await grade_model_rebuilt(
            {"kind": "model_rebuilt", "model": "x; drop table y", "expect": {}}, wh.query
        )
        assert verdict == "ERROR"
        assert wh.queries == []
        assert _by_name(results)["identifier"]["passed"] is False

    async def test_bad_grain_column_is_error(self) -> None:
        """Grain columns are interpolated into SQL too."""
        wh = _FakeWarehouse()
        verdict, _ = await grade_model_rebuilt(
            _grade(grain=['order_id" OR 1=1 --']), wh.query
        )
        assert verdict == "ERROR"

    async def test_exists_only_grade_is_correct_when_present(self) -> None:
        wh = _FakeWarehouse()
        verdict, results = await grade_model_rebuilt(_grade(), wh.query)
        assert verdict == "CORRECT"
        assert [r["name"] for r in results] == ["exists"]
